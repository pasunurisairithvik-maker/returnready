import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone
class Profile(models.Model):
    user=models.OneToOneField(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='profile')
    timezone=models.CharField(max_length=50,default='Asia/Kolkata')
    recovery_hash=models.CharField(max_length=256)
class Purchase(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    owner=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE)
    title=models.CharField(max_length=100)
    retailer=models.CharField(max_length=100)
    amount=models.DecimalField(max_digits=10,decimal_places=2)
    currency=models.CharField(max_length=3,choices=[('INR','INR'),('USD','USD'),('EUR','EUR'),('GBP','GBP')],default='INR')
    bought=models.DateField()
    return_by=models.DateField(null=True,blank=True)
    warranty_until=models.DateField(null=True,blank=True)
    status=models.CharField(max_length=12,choices=[('keeping','Keeping'),('returning','Return planned'),('returned','Returned')],default='keeping')
    notes=models.TextField(max_length=1500,blank=True)
    created=models.DateTimeField(auto_now_add=True)
    updated=models.DateTimeField(auto_now=True)
    deleted_at=models.DateTimeField(null=True,blank=True)
    class Meta:
        ordering=['-created']
        indexes=[models.Index(fields=['owner','return_by']),models.Index(fields=['owner','warranty_until'])]
    @property
    def days_left(self):return (self.return_by-timezone.localdate()).days if self.return_by else None
    @property
    def return_label(self):
        if self.status=='returned':return 'Returned'
        if self.days_left is None:return 'No return date'
        if self.days_left<0:return 'Return window ended'
        if self.days_left==0:return 'Return by today'
        return f'{self.days_left} days to return'
class Receipt(models.Model):
    purchase=models.OneToOneField(Purchase,on_delete=models.CASCADE,related_name='receipt')
    data=models.BinaryField()
    name=models.CharField(max_length=120)
    content_type=models.CharField(max_length=50)
class Throttle(models.Model):
    key=models.CharField(primary_key=True,max_length=64)
    count=models.PositiveIntegerField(default=0)
    bucket=models.BigIntegerField()
