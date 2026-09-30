import time
from django.core.management.base import BaseCommand
from django.contrib.sessions.models import Session
from django.utils import timezone
from django.db import transaction
from tracker.models import Throttle
from config.observability import logger
class Command(BaseCommand):
    help='Remove expired sessions and obsolete rate counters; never delete purchases or receipts.'
    def handle(self,*args,**kwargs):
        with transaction.atomic():
            Session.objects.filter(expire_date__lt=timezone.now()).delete()
            Throttle.objects.filter(bucket__lt=int(time.time()//900)-1).exclude(key__in=['account-capacity','receipt-capacity']).delete()
        logger.info('housekeeping_complete')
        self.stdout.write('Expired sessions and obsolete counters cleared.')
