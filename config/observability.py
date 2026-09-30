"""Allowlisted structured logs: never serialize requests, messages or tracebacks."""
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from django.db import OperationalError, InterfaceError
from django.http import HttpResponse

EVENTS={'request_complete','database_unavailable','purchase_purged','account_deleted','backup_downloaded','password_changed','housekeeping_complete','recovery_code_replaced'}
class SafeJSONFormatter(logging.Formatter):
    def format(self,record):
        event=record.msg if isinstance(record.msg,str) and record.msg in EVENTS else 'application_event'
        result={'timestamp':datetime.now(timezone.utc).isoformat(),'level':record.levelname,'event':event}
        for key in ['request_id','route','method','status','duration_ms']:
            value=getattr(record,key,None)
            if isinstance(value,(str,int,float)):result[key]=value
        if record.exc_info:result['exception_type']=record.exc_info[0].__name__
        return json.dumps(result,separators=(',',':'))

LOGGING={'version':1,'disable_existing_loggers':False,
    'formatters':{'safe_json':{'()':'config.observability.SafeJSONFormatter'}},
    'handlers':{'console':{'class':'logging.StreamHandler','formatter':'safe_json'}},
    'root':{'handlers':['console'],'level':'INFO'},
    'loggers':{'django':{'handlers':['console'],'level':'WARNING','propagate':False},
               'returnready':{'handlers':['console'],'level':'INFO','propagate':False}}}
logger=logging.getLogger('returnready')

def audit(request,event):
    logger.info(event,extra={'request_id':getattr(request,'request_id','unavailable')})

class RequestTelemetry:
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        request.request_id=uuid.uuid4().hex
        started=time.monotonic()
        response=self.get_response(request)
        response['X-Request-ID']=request.request_id
        # Route names are developer constants. Never log paths, queries, cookies or bodies.
        route=getattr(getattr(request,'resolver_match',None),'view_name',None) or 'unmatched'
        logger.info('request_complete',extra={'request_id':request.request_id,'route':route,'method':request.method if request.method in {'GET','POST','HEAD','OPTIONS'} else 'OTHER','status':response.status_code,'duration_ms':round((time.monotonic()-started)*1000,2)})
        return response
    def process_exception(self,request,exception):
        if isinstance(exception,(OperationalError,InterfaceError)):
            audit(request,'database_unavailable')
            response=HttpResponse('Service temporarily unavailable. Try again shortly.',status=503,content_type='text/plain')
            response['Retry-After']='30';response['Cache-Control']='no-store'
            return response
