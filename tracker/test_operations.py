import io,json,logging,tempfile,unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from django.test import TestCase,Client,override_settings,RequestFactory
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.contrib.sessions.models import Session
from django.db import IntegrityError,OperationalError,transaction
from django.utils import timezone
from config.observability import SafeJSONFormatter,RequestTelemetry
from tracker.models import Profile,Purchase,Receipt,Throttle
from tracker.views import canonical_username
from ops.db_backup import connection_env,backup,restore

class OperationTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('ops_fixture',password='synthetic-operations-only-1!')
        Profile.objects.create(user=self.user,recovery_hash='fixture')
        self.client.force_login(self.user)
    def test_trace_header_and_private_logs(self):
        with self.assertLogs('returnready',level='INFO') as captured:
            r=self.client.get('/dashboard/?q=private-query',HTTP_X_REQUEST_ID='untrusted\nsecret',HTTP_COOKIE='private-cookie')
        self.assertRegex(r['X-Request-ID'],r'^[a-f0-9]{32}$')
        logs=' '.join(captured.output)
        for secret in ['private-query','private-cookie','untrusted','ops_fixture']:self.assertNotIn(secret,logs)
    def test_logger_does_not_serialize_exception_or_message(self):
        record=logging.LogRecord('django',logging.ERROR,'',1,'password=private-token',(),(ValueError,ValueError('private-token'),None))
        result=SafeJSONFormatter().format(record)
        self.assertNotIn('private-token',result);self.assertEqual(json.loads(result)['exception_type'],'ValueError')
    def test_database_failure_uses_retryable_response(self):
        with patch('tracker.views.owned',side_effect=OperationalError('password=private-token')):
            r=self.client.get('/dashboard/')
        self.assertEqual(r.status_code,503);self.assertEqual(r['Retry-After'],'30');self.assertNotIn(b'private-token',r.content)
    def test_liveness_does_not_require_database(self):
        self.client.logout()
        with self.assertNumQueries(0):self.assertEqual(self.client.get('/livez').status_code,200)
    def test_invalid_content_length(self):
        for value in ['not-an-int','-1']:
            r=self.client.get('/',CONTENT_LENGTH=value);self.assertEqual(r.status_code,400)
    def test_database_invariants(self):
        data=dict(owner=self.user,title='Fixture',retailer='Fictional',amount=1,bought=timezone.localdate())
        for changed in [{'amount':-1},{'status':'wrong'},{'currency':'XYZ'},{'return_by':timezone.localdate()-timedelta(days=1)},{'warranty_until':timezone.localdate()-timedelta(days=1)}]:
            with self.assertRaises(IntegrityError),transaction.atomic():Purchase.objects.create(**dict(data,**changed))
        purchase=Purchase.objects.create(**data)
        with self.assertRaises(IntegrityError),transaction.atomic():Receipt.objects.create(purchase=purchase,data=b'x'*(2*1024*1024+1),name='receipt.pdf',content_type='application/pdf')
    def test_authentication_normalization_cannot_bypass_key(self):
        self.assertEqual(canonical_username('  OPS_FIXTURE  '),'ops_fixture')
        self.assertEqual(canonical_username('ＯＰＳ＿ＦＩＸＴＵＲＥ'),'ops_fixture')
        self.client.logout()
        for name in ['ops_fixture',' OPS_FIXTURE ','ＯＰＳ＿ＦＩＸＴＵＲＥ']:
            self.client.post('/login/',{'username':name,'password':'wrong'})
        from tracker.views import digest
        self.assertEqual(Throttle.objects.get(key=digest('login:ops_fixture')).count,3)
    def test_sensitive_action_rate_limit(self):
        from tracker.views import digest
        Throttle.objects.create(key=digest('sensitive:'+str(self.user.pk)),bucket=__import__('time').time()//900,count=10)
        r=self.client.post('/account/delete/',{'password':'synthetic-operations-only-1!','confirmation':'DELETE'})
        self.assertEqual(r.status_code,302);self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())
    def test_housekeeping_preserves_live_sessions_and_lock_rows(self):
        Session.objects.create(session_key='expired',session_data='',expire_date=timezone.now()-timedelta(days=1))
        Session.objects.create(session_key='live',session_data='',expire_date=timezone.now()+timedelta(days=1))
        Throttle.objects.create(key='old',bucket=0)
        Throttle.objects.create(key='receipt-capacity',bucket=0)
        call_command('housekeeping',stdout=io.StringIO())
        self.assertFalse(Session.objects.filter(pk='expired').exists());self.assertTrue(Session.objects.filter(pk='live').exists())
        self.assertFalse(Throttle.objects.filter(pk='old').exists());self.assertTrue(Throttle.objects.filter(pk='receipt-capacity').exists())

class BackupSafetyTests(unittest.TestCase):
    def test_credentials_are_environment_only(self):
        env=connection_env('postgresql://fixture:private-password@db.example/fixture?sslmode=require')
        self.assertEqual(env['PGPASSWORD'],'private-password')
        with tempfile.TemporaryDirectory() as tmp,patch('ops.db_backup.subprocess.run') as run:
            backup(Path(tmp)/'fixture.dump','postgresql://fixture:private-password@db.example/fixture?sslmode=require')
            for call in run.call_args_list:self.assertNotIn('private-password',str(call.args))
    def test_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'existing';path.write_bytes(b'important')
            with self.assertRaises(ValueError):backup(path,'postgresql://fixture:password@db.example/fixture')
            self.assertEqual(path.read_bytes(),b'important')
    def test_restore_rejects_operational_database_and_bad_hash(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',{'ALLOW_ISOLATED_RESTORE':'1'}):
            path=Path(tmp)/'fixture';path.write_bytes(b'fixture')
            with self.assertRaises(ValueError):restore(path,'bad','postgresql://fixture:password@db.example/production')
            with self.assertRaises(ValueError):restore(path,'bad','postgresql://fixture:password@db.example/test_restore_drill')
    def test_requires_tls_and_direct_connection(self):
        for url in ['postgres://fixture:password@db.example/fixture?sslmode=disable','postgres://fixture:password@ep-test-pooler.example/fixture']:
            with self.assertRaises(ValueError):connection_env(url)

class SubmissionTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('submission_fixture',password='synthetic-submit-only-82!')
        Profile.objects.create(user=self.user,recovery_hash='fixture')
        self.client.force_login(self.user)
    def payload(self):
        import uuid
        return {'submission_id':str(uuid.uuid4()),'title':'Fixture','retailer':'Fictional','amount':'0.00','currency':'INR','bought':str(timezone.localdate()),'status':'keeping'}
    def test_duplicate_form_submission_returns_original_purchase(self):
        data=self.payload()
        first=self.client.post('/purchases/new/',data)
        second=self.client.post('/purchases/new/',data)
        self.assertEqual(first.status_code,302);self.assertEqual(first['Location'],second['Location']);self.assertEqual(Purchase.objects.count(),1)
    def test_changed_payload_reusing_nonce_is_rejected(self):
        data=self.payload();self.client.post('/purchases/new/',data)
        r=self.client.post('/purchases/new/',dict(data,title='Changed'))
        self.assertEqual(r.status_code,200);self.assertContains(r,'already submitted with different data');self.assertEqual(Purchase.objects.get().title,'Fixture')
    def test_form_contains_nonce_and_trash_retry_does_not_recreate(self):
        self.assertContains(self.client.get('/purchases/new/'),'name="submission_id"')
        data=self.payload();self.client.post('/purchases/new/',data)
        item=Purchase.objects.get();item.deleted_at=timezone.now();item.save()
        r=self.client.post('/purchases/new/',data)
        self.assertEqual(r['Location'],'/trash/');self.assertEqual(Purchase.objects.count(),1)

from django.test import TransactionTestCase
from django.db import connection,close_old_connections
class ConcurrentSubmissionTests(TransactionTestCase):
    @unittest.skipUnless(connection.vendor=='postgresql','Requires isolated PostgreSQL row locks')
    def test_concurrent_nonce_creates_one_purchase(self):
        import threading,uuid
        from concurrent.futures import ThreadPoolExecutor
        user=get_user_model().objects.create_user('concurrent_fixture',password='synthetic-submit-only-93!')
        Profile.objects.create(user=user,recovery_hash='fixture')
        payload={'submission_id':str(uuid.uuid4()),'title':'Fixture','retailer':'Fictional','amount':'0.00','currency':'INR','bought':str(timezone.localdate()),'status':'keeping'}
        barrier=threading.Barrier(2)
        def submit(_):
            close_old_connections()
            try:
                client=Client();client.force_login(user);barrier.wait(timeout=10)
                response=client.post('/purchases/new/',payload)
                return response.status_code,response.get('Location')
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(submit,range(2)))
        self.assertEqual(responses[0],responses[1]);self.assertEqual(responses[0][0],302);self.assertEqual(Purchase.objects.count(),1)
