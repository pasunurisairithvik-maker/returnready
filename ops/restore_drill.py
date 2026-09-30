"""CI-only full PostgreSQL dump/restore using synthetic purchases and receipts."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse
import psycopg
from psycopg import sql
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from ops.db_backup import backup, restore

def main():
    source=os.environ.get('DATABASE_URL','')
    parsed=urlparse(source)
    database=parsed.path.lstrip('/')
    if os.getenv('RESTORE_DRILL')!='1' or not database.endswith('_ci') or parsed.hostname not in {'localhost','127.0.0.1'}:
        raise RuntimeError('Restore drill requires an isolated localhost *_ci database')
    os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
    import django
    django.setup()
    from django.core.management import call_command
    from django.contrib.auth import get_user_model
    from django.utils import timezone
    from tracker.models import Profile, Purchase, Receipt
    call_command('migrate',verbosity=0)
    user=get_user_model().objects.create_user('restore_drill_fixture',password='synthetic-drill-only-81!')
    Profile.objects.create(user=user,recovery_hash='synthetic-hash')
    purchase=Purchase.objects.create(owner=user,title='Synthetic restore receipt',retailer='Fictional store',amount='0.00',bought=timezone.localdate())
    purchase.refresh_from_db()
    payload=b'%PDF-1.4\nSynthetic restore fixture only\n%%EOF'
    Receipt.objects.create(purchase=purchase,data=payload,name='receipt.pdf',content_type='application/pdf')
    target_name=database+'_restore_drill'
    target=urlunparse(parsed._replace(path='/'+target_name))
    # CREATE DATABASE fails if the drill database already exists; never reuse unknown data.
    with psycopg.connect(source,autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(target_name)))
    started=time.monotonic()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'fixture.dump'
            metadata=backup(path,source)
            os.environ['ALLOW_ISOLATED_RESTORE']='1'
            restore(path,metadata['sha256'],target)
            with psycopg.connect(target) as restored:
                row=restored.execute('SELECT p.title,p.amount,r.data FROM tracker_purchase p JOIN tracker_receipt r ON r.purchase_id=p.id WHERE p.id=%s',(purchase.pk,)).fetchone()
                assert row and row[0]==purchase.title and row[1]==purchase.amount and bytes(row[2])==payload
                assert restored.execute('SELECT count(*) FROM tracker_profile').fetchone()[0]==1
        print(json.dumps({'drill':'synthetic_postgresql_restore','passed':True,'elapsed_seconds':round(time.monotonic()-started,3)}))
    finally:
        # This specific database was created by this invocation, and holds synthetic fixtures only.
        with psycopg.connect(source,autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(target_name)))
if __name__=='__main__':main()
