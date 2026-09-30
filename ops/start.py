"""Validate, migrate once per deployment, then replace this process with Gunicorn."""
import os
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent

def bounded(name,default,maximum):
    value=int(os.getenv(name,str(default)))
    if not 1<=value<=maximum:raise ValueError(f'Invalid {name}')
    return str(value)
def main():
    os.chdir(ROOT)
    if os.getenv('DEBUG','0')!='1':subprocess.run([sys.executable,'manage.py','check','--deploy','--fail-level','WARNING'],check=True)
    subprocess.run([sys.executable,'manage.py','migrate','--noinput'],check=True)
    subprocess.run([sys.executable,'manage.py','housekeeping'],check=True)
    args=['gunicorn','config.wsgi:application','--bind','0.0.0.0:'+bounded('PORT',10000,65535),'--workers',bounded('WEB_CONCURRENCY',1,8),'--threads',bounded('WEB_THREADS',4,8),'--timeout','60','--graceful-timeout','30','--max-requests','500','--max-requests-jitter','50','--access-logfile','/dev/null']
    os.execvp(args[0],args)
if __name__=='__main__':main()
