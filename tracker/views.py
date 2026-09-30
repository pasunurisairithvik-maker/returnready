import csv, hashlib, hmac, io, json, secrets, time, zipfile, unicodedata, uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm, AuthenticationForm, PasswordChangeForm
from django.contrib.auth.hashers import make_password
from django.contrib.auth import update_session_auth_hash
from django.db import transaction, connection
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from config.observability import audit
from .models import Purchase,Receipt,Profile,Throttle
from .forms import RegisterForm,PurchaseForm,RecoveryForm,SettingsForm
User=get_user_model()
def digest(value):return hmac.new(settings.SECRET_KEY.encode(),value.encode(),hashlib.sha256).hexdigest()
def limited(key,limit=10):
    key=digest(key);bucket=int(time.time()//900)
    with transaction.atomic():
        Throttle.objects.filter(bucket__lt=bucket-1).exclude(key__in=['account-capacity','receipt-capacity']).delete()
        Throttle.objects.get_or_create(key=key,defaults={'bucket':bucket})
        item=Throttle.objects.select_for_update().get(key=key)
        if item.bucket!=bucket:item.bucket=bucket;item.count=0
        item.count+=1;item.save()
        return item.count>limit
def home(request):return render(request,'home.html')
def sign_up(request):
    form=RegisterForm(request.POST or None)
    if request.method=='POST':
        if limited('registration',20):form.add_error(None,'Signup is temporarily busy. Try again in 15 minutes.')
        elif form.is_valid():
            with transaction.atomic():
                # Lock a stable row to serialize the free-tier account quota.
                lock,_=Throttle.objects.get_or_create(key='account-capacity',defaults={'bucket':int(time.time()//900)})
                Throttle.objects.select_for_update().get(pk=lock.pk)
                if User.objects.count()>=settings.MAX_USERS:form.add_error(None,'The free plan is currently full.')
                else:
                    user=form.save();code=secrets.token_urlsafe(32)
                    Profile.objects.create(user=user,recovery_hash=digest(code));login(request,user)
                    return render(request,'recovery_code.html',{'code':code})
    return render(request,'form.html',{'form':form,'heading':'Your purchases. Your private space.','intro':'Create a username and a unique password. No email address required.','button':'Create account'})
def canonical_username(value):return unicodedata.normalize('NFKC',value).strip().lower()
def sign_in(request):
    data=request.POST.copy() if request.method=='POST' else None
    if data is not None:data['username']=canonical_username(data.get('username',''))
    form=AuthenticationForm(request,data=data)
    if request.method=='POST':
        if limited('authentication-global',500) or limited('login:'+data.get('username',''),10):form.add_error(None,'Too many attempts. Try again in 15 minutes.')
        elif form.is_valid():login(request,form.get_user());return redirect('dashboard')
    return render(request,'form.html',{'form':form,'heading':'Welcome back.','intro':'Sign in to your private purchase vault.','button':'Sign in','recover':True})
def recover(request):
    form=RecoveryForm(request.POST or None)
    if request.method=='POST':
        if limited('authentication-global',500) or limited('recover:'+canonical_username(request.POST.get('username','')),5):form.add_error(None,'Too many attempts. Try again in 15 minutes.')
        elif form.is_valid():
            with transaction.atomic():
                user=User.objects.filter(username=canonical_username(form.cleaned_data['username'])).first()
                profile=Profile.objects.select_for_update().filter(user=user).first() if user else None
                if not profile or not secrets.compare_digest(profile.recovery_hash,digest(form.cleaned_data['recovery_code'])):form.add_error(None,'Username or recovery code is incorrect.')
                else:
                    password=SetPasswordForm(user,{'new_password1':form.cleaned_data['password1'],'new_password2':form.cleaned_data['password2']})
                    if password.is_valid():
                        password.save();code=secrets.token_urlsafe(32);profile.recovery_hash=digest(code);profile.save();login(request,user)
                        return render(request,'recovery_code.html',{'code':code})
                    else:
                        for errors in password.errors.values():
                            for error in errors:form.add_error(None,error)
    return render(request,'form.html',{'form':form,'heading':'Recover your account.','intro':'Use the recovery code you saved at signup. Without your password or code, we cannot recover your account.','button':'Reset password'})
@login_required
@require_POST
def sign_out(request):logout(request);return redirect('home')
def owned(request):return Purchase.objects.filter(owner=request.user,deleted_at__isnull=True)
@login_required
def dashboard(request):
    today=timezone.localdate();all_items=owned(request).select_related('receipt').defer('receipt__data')
    near=all_items.exclude(status='returned').filter(return_by__range=(today,today+timedelta(days=7))).order_by('return_by')
    warranties=all_items.exclude(status='returned').filter(warranty_until__gte=today).count()
    totals=defaultdict(Decimal)
    for p in all_items.exclude(status='returned'):totals[p.currency]+=p.amount
    q=request.GET.get('q','')[:100];kind=request.GET.get('filter','all')
    items=all_items
    if q:items=items.filter(Q(title__icontains=q)|Q(retailer__icontains=q)|Q(notes__icontains=q))
    if kind=='due':items=items.exclude(status='returned').filter(return_by__range=(today,today+timedelta(days=7)))
    if kind=='warranty':items=items.exclude(status='returned').filter(warranty_until__gte=today)
    if kind=='returned':items=items.filter(status='returned')
    return render(request,'dashboard.html',{'items':items,'q':q,'filter':kind,'total_count':all_items.count(),'due_count':near.count(),'warranties':warranties,'totals':dict(totals),'near':near[:3]})
@login_required
def edit_purchase(request,pk=None):
    purchase=get_object_or_404(owned(request),pk=pk) if pk else Purchase(owner=request.user,bought=timezone.localdate())
    form=PurchaseForm(request.POST or None,request.FILES or None,instance=purchase,initial={'submission_id':None if pk else uuid.uuid4()})
    if request.method=='POST':
        if getattr(request,'upload_rejected',False):form.add_error('receipt_file','Upload was rejected. Use a file smaller than 2 MB.')
        if form.is_valid():
            with transaction.atomic():
                User.objects.select_for_update().get(pk=request.user.pk)
                capacity,_=Throttle.objects.get_or_create(key='receipt-capacity',defaults={'bucket':int(time.time()//900)})
                Throttle.objects.select_for_update().get(pk=capacity.pk)
                file=form.cleaned_data.get('receipt_file')
                submission=form.cleaned_data.get('submission_id') if not pk else None
                fingerprint_data={k:str(v) if v is not None else None for k,v in form.cleaned_data.items() if k not in ['receipt_file','submission_id']}
                fingerprint_data['amount']=format(form.cleaned_data['amount'],'.2f')
                fingerprint_data['receipt']=hashlib.sha256(file[0]).hexdigest() if file else None
                fingerprint=hashlib.sha256(json.dumps(fingerprint_data,sort_keys=True).encode()).hexdigest()
                prior=Purchase.objects.filter(owner=request.user,submission_id=submission).first() if submission else None
                if prior:
                    if prior.submission_hash==fingerprint:
                        if prior.deleted_at:
                            messages.info(request,'This submission was already saved and is now in trash.');return redirect('trash_list')
                        return redirect('detail',pk=prior.pk)
                    form.add_error(None,'This form was already submitted with different data. Open a new purchase form.');return render(request,'form.html',{'form':form,'heading':'Keep your next purchase organised.','button':'Save purchase','multipart':True})
                if not pk and Purchase.objects.filter(owner=request.user).count()>=settings.MAX_PURCHASES:form.add_error(None,'Free plan limit: 100 purchases, including trash. Export records before removing them permanently.')
                elif file and not Receipt.objects.filter(purchase=purchase).exists() and Receipt.objects.filter(purchase__owner=request.user).count()>=settings.MAX_RECEIPTS:form.add_error('receipt_file','Free plan limit: 10 receipts. You can replace an existing receipt.')
                elif file and not Receipt.objects.filter(purchase=purchase).exists() and Receipt.objects.count()>=100:form.add_error('receipt_file','Receipt storage for the free plan is full. Purchase tracking is still available.')
                else:
                    purchase=form.save(commit=False)
                    if submission:purchase.submission_id=submission;purchase.submission_hash=fingerprint
                    purchase.save()
                    if file:Receipt.objects.update_or_create(purchase=purchase,defaults=dict(zip(['data','name','content_type'],file)))
                    messages.success(request,'Purchase saved.');return redirect('detail',pk=purchase.pk)
    return render(request,'form.html',{'form':form,'heading':'Edit purchase' if pk else 'Keep your next purchase organised.','intro':'Use the deadline printed on your receipt or retailer policy. We do not guess return rules.','button':'Save purchase','multipart':True})
@login_required
def detail(request,pk):return render(request,'detail.html',{'purchase':get_object_or_404(owned(request).select_related('receipt').defer('receipt__data'),pk=pk)})
@login_required
def receipt(request,pk):
    item=get_object_or_404(Receipt,purchase__id=pk,purchase__owner=request.user,purchase__deleted_at__isnull=True)
    response=HttpResponse(bytes(item.data),content_type=item.content_type)
    response['Content-Disposition']=f'attachment; filename="{item.name}"'
    response['Content-Security-Policy']="sandbox; default-src 'none'"
    return response
@login_required
@require_POST
def trash(request,pk):
    with transaction.atomic():
        User.objects.select_for_update().get(pk=request.user.pk)
        item=get_object_or_404(owned(request),pk=pk);item.deleted_at=timezone.now();item.save(update_fields=['deleted_at'])
    messages.success(request,'Moved to trash. You can restore it.');return redirect('dashboard')
@login_required
def trash_list(request):return render(request,'trash.html',{'items':Purchase.objects.filter(owner=request.user,deleted_at__isnull=False)})
@login_required
@require_POST
def restore(request,pk):
    with transaction.atomic():
        User.objects.select_for_update().get(pk=request.user.pk)
        item=get_object_or_404(Purchase,owner=request.user,pk=pk,deleted_at__isnull=False);item.deleted_at=None;item.save(update_fields=['deleted_at'])
    messages.success(request,'Purchase restored.');return redirect('detail',pk=pk)
@login_required
@require_POST
def purge(request,pk):
    with transaction.atomic():
        User.objects.select_for_update().get(pk=request.user.pk)
        item=get_object_or_404(Purchase.objects.select_for_update(),owner=request.user,pk=pk,deleted_at__isnull=False)
        if limited('purge:'+str(request.user.pk),10):
            messages.error(request,'Too many attempts. Try again in 15 minutes.')
        elif request.POST.get('confirmation')=='DELETE' and request.user.check_password(request.POST.get('password','')):
            item.delete();audit(request,'purchase_purged')
            messages.success(request,'Purchase and its receipt permanently deleted. Storage is available again.')
        else:messages.error(request,'Enter your current password and DELETE to confirm permanent deletion.')
    return redirect('trash_list')
@login_required
@require_POST
def set_status(request,pk):
    with transaction.atomic():
        User.objects.select_for_update().get(pk=request.user.pk)
        item=get_object_or_404(owned(request),pk=pk)
        status=request.POST.get('status')
        if status in dict(Purchase._meta.get_field('status').choices):item.status=status;item.save(update_fields=['status','updated'])
    return redirect('detail',pk=pk)
def csv_safe(value):
    value='' if value is None else str(value)
    return "'"+value if value.lstrip().startswith(('=','+','-','@','\t','\r')) else value
@login_required
def export(request):
    response=HttpResponse(content_type='text/csv; charset=utf-8');response['Content-Disposition']='attachment; filename="returnready-purchases.csv"'
    writer=csv.writer(response);writer.writerow(['item','retailer','amount','currency','purchased','return_by','warranty_until','status','notes','trashed'])
    for p in Purchase.objects.filter(owner=request.user):writer.writerow([csv_safe(v) for v in [p.title,p.retailer,p.amount,p.currency,p.bought,p.return_by,p.warranty_until,p.status,p.notes,bool(p.deleted_at)]])
    return response
@login_required
def backup(request):
    # Bound output by the account's existing receipt quota; never include other users.
    output=io.BytesIO()
    with transaction.atomic():
        User.objects.select_for_update().get(pk=request.user.pk)
        purchases=list(Purchase.objects.filter(owner=request.user).order_by('created','pk'))
        receipts=list(Receipt.objects.filter(purchase__owner=request.user))
        manifest=[{'id':str(p.pk),'title':p.title,'retailer':p.retailer,'amount':str(p.amount),'currency':p.currency,'bought':str(p.bought),'return_by':str(p.return_by) if p.return_by else None,'warranty_until':str(p.warranty_until) if p.warranty_until else None,'status':p.status,'notes':p.notes,'trashed':bool(p.deleted_at)} for p in purchases]
        with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED) as archive:
            archive.writestr('purchases.csv',export(request).content)
            archive.writestr('purchases.json',json.dumps({'format_version':1,'timezone':request.user.profile.timezone,'purchases':manifest},ensure_ascii=False,indent=2))
            for receipt in receipts:archive.writestr('receipts/'+str(receipt.purchase_id)+'/'+receipt.name,bytes(receipt.data))
            archive.writestr('README.txt','Private ReturnReady backup. Includes active and trashed purchases and receipt files. Keep this download securely. JSON identifiers match receipt folders. Automatic re-import is not supported. This archive contains no password or recovery code.\n')
    audit(request,'backup_downloaded')
    response=HttpResponse(output.getvalue(),content_type='application/zip')
    response['Content-Disposition']='attachment; filename="returnready-backup.zip"'
    return response
def ics_escape(value):return str(value).replace('\\','\\\\').replace('\r','').replace('\n','\\n').replace(';','\\;').replace(',','\\,')
def fold(line):
    parts=[];chunk='';size=0
    for char in line:
        n=len(char.encode())
        if size+n>73:parts.append(chunk);chunk=' ';size=1
        chunk+=char;size+=n
    return '\r\n'.join(parts+[chunk])
@login_required
def calendar(request):
    lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//ReturnReady//Purchase deadlines//EN','CALSCALE:GREGORIAN','METHOD:PUBLISH']
    for p in owned(request).exclude(status='returned'):
        for kind,label,day in [('return','Return deadline',p.return_by),('warranty','Warranty expiry',p.warranty_until)]:
            if not day or day<timezone.localdate():continue
            lines+=['BEGIN:VEVENT',f'UID:{p.pk}-{kind}@returnready',f'DTSTAMP:{timezone.now():%Y%m%dT%H%M%SZ}',f'DTSTART;VALUE=DATE:{day:%Y%m%d}',*([f'DTEND;VALUE=DATE:{day+timedelta(days=1):%Y%m%d}'] if day<date.max else []),f'SUMMARY:{ics_escape(label+": "+p.title)}',f'DESCRIPTION:{ics_escape("Retailer: "+p.retailer+". Verify the applicable policy and local closing time.")}', 'BEGIN:VALARM','TRIGGER:-P1D','ACTION:DISPLAY',f'DESCRIPTION:{ics_escape(label+": "+p.title)}','END:VALARM','END:VEVENT']
    lines+=['END:VCALENDAR'];response=HttpResponse('\r\n'.join(fold(x) for x in lines)+'\r\n',content_type='text/calendar; charset=utf-8');response['Content-Disposition']='attachment; filename="returnready-deadlines.ics"';return response
@login_required
def account(request):
    form=SettingsForm(request.POST or None,initial={'timezone':request.user.profile.timezone})
    if request.method=='POST' and form.is_valid():request.user.profile.timezone=form.cleaned_data['timezone'];request.user.profile.save();messages.success(request,'Timezone updated.');return redirect('account')
    return render(request,'account.html',{'form':form})
@login_required
def change_password(request):
    form=PasswordChangeForm(request.user,request.POST or None)
    if request.method=='POST':
        if limited('sensitive:'+str(request.user.pk),10):form.add_error(None,'Too many attempts. Try again in 15 minutes.')
        elif form.is_valid():
            user=form.save();update_session_auth_hash(request,user);audit(request,'password_changed');messages.success(request,'Password updated. Other sessions are invalidated.');return redirect('account')
    return render(request,'form.html',{'form':form,'heading':'Change your password','button':'Update password'})
@login_required
@require_POST
def delete_account(request):
    if limited('sensitive:'+str(request.user.pk),10):
        messages.error(request,'Too many attempts. Try again in 15 minutes.');return redirect('account')
    if request.POST.get('confirmation')=='DELETE' and request.user.check_password(request.POST.get('password','')):
        user=request.user;logout(request);user.delete();audit(request,'account_deleted');messages.success(request,'Account and active purchase records deleted. Provider backups may retain older copies temporarily.');return redirect('home')
    messages.error(request,'Enter your password and DELETE to confirm.');return redirect('account')
def privacy(request):return render(request,'privacy.html')
def health(request):
    try:
        with connection.cursor() as cursor:cursor.execute('SELECT 1 FROM tracker_purchase LIMIT 1')
        return JsonResponse({'status':'ok','service':'returnready'})
    except Exception:return JsonResponse({'status':'unavailable'},status=503)

def live(request):return JsonResponse({'status':'ok','service':'returnready'})
