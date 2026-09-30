from datetime import date
from io import BytesIO
from PIL import Image, UnidentifiedImageError
from django import forms
from django.utils import timezone
from django.contrib.auth.forms import UserCreationForm,SetPasswordForm
from .models import Purchase
class RegisterForm(UserCreationForm):
    def clean_username(self):return super().clean_username().lower()
class PurchaseForm(forms.ModelForm):
    submission_id=forms.UUIDField(required=False,widget=forms.HiddenInput)
    receipt_file=forms.FileField(required=False,label='Receipt (JPEG, PNG or PDF · maximum 2 MB)')
    class Meta:
        model=Purchase
        fields=['title','retailer','amount','currency','bought','return_by','warranty_until','status','notes']
        widgets={key:forms.DateInput(attrs={'type':'date'}) for key in ['bought','return_by','warranty_until']}
        widgets['notes']=forms.Textarea(attrs={'rows':3})
    def clean(self):
        data=super().clean()
        bought=data.get('bought')
        if data.get('amount') is not None and data['amount']<0:self.add_error('amount','Use a positive amount or zero.')
        if bought and bought>timezone.localdate():self.add_error('bought','Purchase date cannot be in the future.')
        for key in ['return_by','warranty_until']:
            if bought and data.get(key) and data[key]<bought:self.add_error(key,'Deadline cannot be earlier than the purchase.')
        return data
    def clean_receipt_file(self):
        upload=self.cleaned_data.get('receipt_file')
        if not upload:return None
        raw=upload.read(2*1024*1024+1)
        if len(raw)>2*1024*1024:raise forms.ValidationError('Receipt must be 2 MB or smaller.')
        if raw.startswith(b'%PDF-'):
            if b'%%EOF' not in raw[-2048:]:raise forms.ValidationError('This PDF is incomplete.')
            return (raw,'receipt.pdf','application/pdf')
        try:
            Image.MAX_IMAGE_PIXELS=12_000_000
            with Image.open(BytesIO(raw)) as image:
                if image.format not in ['JPEG','PNG'] or image.width*image.height>12_000_000:raise ValueError()
                image.load();image.thumbnail((2400,2400));out=BytesIO()
                image.convert('RGB').save(out,format='JPEG',quality=85)
                encoded=out.getvalue()
                if len(encoded)>2*1024*1024:raise ValueError()
                return (encoded,'receipt.jpg','image/jpeg')
        except (UnidentifiedImageError,ValueError,OSError,Image.DecompressionBombError,Image.DecompressionBombWarning):
            raise forms.ValidationError('Use a valid JPEG, PNG or PDF. Images are saved without metadata.')
class RecoveryForm(forms.Form):
    username=forms.CharField(max_length=150)
    recovery_code=forms.CharField(widget=forms.PasswordInput,max_length=100)
    password1=forms.CharField(label='New password',widget=forms.PasswordInput)
    password2=forms.CharField(label='Confirm new password',widget=forms.PasswordInput)
class SettingsForm(forms.Form):
    timezone=forms.ChoiceField(choices=[('Asia/Kolkata','India'),('America/Chicago','US Central'),('America/New_York','US Eastern'),('America/Los_Angeles','US Pacific'),('Europe/London','UK'),('UTC','UTC')])
