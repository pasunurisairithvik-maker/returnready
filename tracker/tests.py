import io
from datetime import timedelta
from django.test import TestCase,Client,override_settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image
from .models import Purchase,Receipt,Profile
from .views import digest,csv_safe,fold
from .forms import PurchaseForm
User=get_user_model()
class AppTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a=User.objects.create_user('alice',password='private-battery-shelf-482!')
        cls.b=User.objects.create_user('bob',password='different-private-shelf-763!')
        for u in [cls.a,cls.b]:Profile.objects.create(user=u,recovery_hash=digest('recovery-'+u.username))
        cls.p=Purchase.objects.create(owner=cls.a,title='Headphones',retailer='Example Store',amount='2499.00',bought=timezone.localdate(),return_by=timezone.localdate()+timedelta(days=3),warranty_until=timezone.localdate()+timedelta(days=365))
        Receipt.objects.create(purchase=cls.p,data=b'%PDF-1.4\n%%EOF',name='receipt.pdf',content_type='application/pdf')
    def setUp(self):self.client.force_login(self.a)
    def data(self,**extra):
        result={'title':'Mixer','retailer':'Example','amount':'3200.00','currency':'INR','bought':str(timezone.localdate()),'return_by':str(timezone.localdate()+timedelta(days=30)),'status':'keeping','notes':'Saved for repair'};result.update(extra);return result
    def test_public_pages(self):
        self.client.logout()
        for url in ['/','/privacy/','/login/','/signup/','/recover/']:self.assertEqual(self.client.get(url).status_code,200)
    def test_dashboard_counts_and_currency(self):
        Purchase.objects.create(owner=self.a,title='Lamp',retailer='US shop',amount='25',currency='USD',bought=timezone.localdate())
        response=self.client.get('/dashboard/')
        self.assertContains(response,'INR 2499.00');self.assertContains(response,'USD 25.00');self.assertEqual(response.context['due_count'],1)
    def test_login_required(self):
        self.client.logout();self.assertEqual(self.client.get('/dashboard/').status_code,302)
    def test_user_isolation(self):
        self.client.force_login(self.b)
        for suffix in ['', 'edit/','receipt/']:self.assertEqual(self.client.get(f'/purchases/{self.p.pk}/'+suffix).status_code,404)
        for suffix in ['trash/','restore/','status/']:self.assertEqual(self.client.post(f'/purchases/{self.p.pk}/'+suffix,{'status':'returned'}).status_code,404)
        self.assertNotContains(self.client.get('/dashboard/'),'Headphones')
        self.assertNotIn(b'Headphones',self.client.get('/export/').content)
    def test_create_and_edit(self):
        response=self.client.post('/purchases/new/',self.data());self.assertEqual(response.status_code,302)
        p=Purchase.objects.get(title='Mixer');self.assertEqual(p.owner,self.a)
        self.client.post(f'/purchases/{p.pk}/edit/',self.data(title='Kitchen mixer'));p.refresh_from_db();self.assertEqual(p.title,'Kitchen mixer')
    def test_validation(self):
        for extra in [{'amount':'-1'},{'bought':str(timezone.localdate()+timedelta(days=1))},{'return_by':'2000-01-01'}]:self.assertFalse(PurchaseForm(self.data(**extra)).is_valid())
    def test_receipt_is_private_attachment(self):
        r=self.client.get(f'/purchases/{self.p.pk}/receipt/');self.assertEqual(r.status_code,200);self.assertIn('attachment',r['Content-Disposition']);self.assertIn('no-store',r['Cache-Control'])
    def test_valid_image_normalised(self):
        out=io.BytesIO();Image.new('RGB',(12,12),'blue').save(out,'PNG')
        data=self.data();data['receipt_file']=SimpleUploadedFile('receipt.png',out.getvalue(),'image/png')
        self.assertEqual(self.client.post('/purchases/new/',data).status_code,302)
        self.assertEqual(Receipt.objects.get(purchase__title='Mixer').content_type,'image/jpeg')
    def test_invalid_upload_rejected(self):
        data=self.data();data['receipt_file']=SimpleUploadedFile('receipt.png',b'<script>oops</script>','image/png')
        r=self.client.post('/purchases/new/',data);self.assertEqual(r.status_code,200);self.assertFalse(Purchase.objects.filter(title='Mixer').exists())
    def test_oversize_upload_rejected(self):
        data=self.data();data['receipt_file']=SimpleUploadedFile('huge.pdf',b'%PDF-'+b'x'*(2*1024*1024))
        r=self.client.post('/purchases/new/',data);self.assertIn(r.status_code,[200,413]);self.assertFalse(Purchase.objects.filter(title='Mixer').exists())
    def test_csv_injection(self):
        self.p.title='=HYPERLINK("bad")';self.p.save();self.assertIn(b"'=HYPERLINK",self.client.get('/export/').content)
        self.assertEqual(csv_safe(' +123'),"' +123")
    def test_calendar_dates_and_alarms(self):
        content=self.client.get('/calendar/').content.decode();self.assertIn('TRIGGER:-P1D',content);self.assertIn(f'DTSTART;VALUE=DATE:{self.p.return_by:%Y%m%d}',content)
        self.client.post(f'/purchases/{self.p.pk}/status/',{'status':'returned'});self.assertNotIn('Headphones',self.client.get('/calendar/').content.decode())
    def test_calendar_utf8_folding(self):self.assertTrue(all(len(x.encode())<=75 for x in fold('SUMMARY:'+'తెలుగు'*30).split('\r\n')))
    def test_trash_restore(self):
        self.client.post(f'/purchases/{self.p.pk}/trash/');self.assertEqual(self.client.get(f'/purchases/{self.p.pk}/').status_code,404)
        self.assertContains(self.client.get('/trash/'),'Headphones');self.client.post(f'/purchases/{self.p.pk}/restore/');self.assertEqual(self.client.get(f'/purchases/{self.p.pk}/').status_code,200)
    def test_get_cannot_modify(self):
        for suffix in ['trash/','restore/','status/']:self.assertEqual(self.client.get(f'/purchases/{self.p.pk}/'+suffix).status_code,405)
    def test_csrf(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.a);self.assertEqual(client.post('/purchases/new/',self.data()).status_code,403)
    def test_search_and_html_escaping(self):
        self.p.title='<script>alert(1)</script>';self.p.save();r=self.client.get('/dashboard/',{'q':'script'});self.assertContains(r,'&lt;script&gt;');self.assertNotContains(r,'<script>')
    def test_recovery_rotates_code(self):
        self.client.logout();r=self.client.post('/recover/',{'username':'alice','recovery_code':'recovery-alice','password1':'new-private-battery-982!','password2':'new-private-battery-982!'})
        self.assertContains(r,'Save your recovery code');self.a.refresh_from_db();self.assertTrue(self.a.check_password('new-private-battery-982!'))
        self.client.logout();r=self.client.post('/recover/',{'username':'alice','recovery_code':'recovery-alice','password1':'other-private-battery-982!','password2':'other-private-battery-982!'})
        self.assertContains(r,'incorrect')
    @override_settings(MAX_PURCHASES=1)
    def test_purchase_quota(self):self.client.post('/purchases/new/',self.data());self.assertEqual(Purchase.objects.filter(owner=self.a).count(),1)
    @override_settings(MAX_RECEIPTS=0)
    def test_receipt_quota(self):
        data=self.data();data['receipt_file']=SimpleUploadedFile('receipt.pdf',b'%PDF-1.4\n%%EOF')
        self.client.post('/purchases/new/',data);self.assertFalse(Purchase.objects.filter(title='Mixer').exists())
    def test_wrong_account_delete_password(self):
        self.client.post('/account/delete/',{'password':'wrong','confirmation':'DELETE'});self.assertTrue(User.objects.filter(pk=self.a.pk).exists())
    def test_account_delete_cascades(self):
        self.client.post('/account/delete/',{'password':'private-battery-shelf-482!','confirmation':'DELETE'});self.assertFalse(User.objects.filter(pk=self.a.pk).exists());self.assertEqual(Receipt.objects.count(),0)
    def test_rate_limit(self):
        self.client.logout()
        for _ in range(11):r=self.client.post('/login/',{'username':'alice','password':'wrong'})
        self.assertContains(r,'Too many attempts')
    def test_timezone(self):
        self.client.post('/account/',{'timezone':'America/Chicago'});self.a.profile.refresh_from_db();self.assertEqual(self.a.profile.timezone,'America/Chicago')
    def test_health(self):self.assertEqual(self.client.get('/healthz').json()['status'],'ok')
