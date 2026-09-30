"""Private pg_dump archives; restores are restricted to empty drill databases."""
import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
import psycopg

def connection_env(url):
    parsed=urlparse(url)
    if parsed.scheme not in ('postgres','postgresql') or not parsed.hostname or not parsed.path.strip('/'):
        raise ValueError('A PostgreSQL URL is required')
    if '-pooler.' in parsed.hostname:raise ValueError('Use a direct PostgreSQL connection for backups and restore drills')
    query=parse_qs(parsed.query)
    sslmode=query.get('sslmode',['require'])[0]
    if sslmode not in {'require','verify-ca','verify-full'} and not (os.getenv('LOCAL_POSTGRES')=='1' and parsed.hostname in {'localhost','127.0.0.1'}):
        raise ValueError('TLS is required outside isolated localhost testing')
    env=os.environ.copy()
    # Passwords and full URLs never appear in subprocess arguments or output.
    env.update(PGHOST=parsed.hostname,PGPORT=str(parsed.port or 5432),PGDATABASE=unquote(parsed.path.lstrip('/')),PGUSER=unquote(parsed.username or ''),PGPASSWORD=unquote(parsed.password or ''),PGSSLMODE=sslmode,PGCONNECT_TIMEOUT='10')
    return env

def pg_tool(name):
    directory=os.getenv('PG_BIN_DIR')
    if directory and not Path(directory).is_absolute():raise ValueError('PG_BIN_DIR must be absolute')
    return str(Path(directory)/name) if directory else name

def archive_hash(path):
    digest=hashlib.sha256()
    with open(path,'rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()

def backup(destination,url=None):
    env=connection_env(url or os.environ.get('DATABASE_URL',''))
    path=Path(destination).resolve()
    if path.exists():raise ValueError('Refusing to overwrite an existing backup')
    if not path.parent.is_dir():raise ValueError('Create a private backup directory first')
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(prefix='.returnready-',dir=path.parent,delete=False) as handle:temporary=Path(handle.name)
        subprocess.run([pg_tool('pg_dump'),'--format=custom','--no-owner','--no-privileges','--file',str(temporary)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True,timeout=300)
        subprocess.run([pg_tool('pg_restore'),'--list',str(temporary)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True,timeout=30)
        digest=archive_hash(temporary)
        os.link(temporary,path) # Atomic no-overwrite publication, even if another writer races.
        return {'sha256':digest,'bytes':path.stat().st_size,'format':'pg_dump_custom'}
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)

def restore(path,expected_hash,url=None):
    target=url or os.environ.get('RESTORE_DATABASE_URL','')
    env=connection_env(target)
    if os.getenv('ALLOW_ISOLATED_RESTORE')!='1' or not env['PGDATABASE'].endswith('_restore_drill'):
        raise ValueError('Restore is restricted to explicitly authorized *_restore_drill databases')
    if not expected_hash or archive_hash(path)!=expected_hash:raise ValueError('Backup integrity check failed')
    with psycopg.connect(target,connect_timeout=10) as con:
        count=con.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r','p','v','m','f','S')").fetchone()[0]
        if count:raise ValueError('Restore target must be empty; never clean or overwrite an existing database')
    subprocess.run([pg_tool('pg_restore'),'--exit-on-error','--single-transaction','--no-owner','--no-privileges','--dbname',env['PGDATABASE'],str(Path(path).resolve())],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True,timeout=300)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('backup').add_argument('destination')
    r=sub.add_parser('restore');r.add_argument('archive');r.add_argument('--sha256',required=True)
    args=parser.parse_args()
    try:
        if args.command=='backup':print(json.dumps(backup(args.destination)))
        else:restore(args.archive,args.sha256);print('Isolated restore completed.')
    except (ValueError,OSError,subprocess.SubprocessError,psycopg.Error):
        # Native client diagnostics can contain hostnames, roles and connection details.
        parser.exit(1,'Backup or restore failed. Verify private configuration, tool versions, permissions and target isolation.\n')
if __name__=='__main__':main()
