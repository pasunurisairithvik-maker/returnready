from django.core.files.uploadhandler import MemoryFileUploadHandler, StopUpload
class LimitedUpload(MemoryFileUploadHandler):
    def new_file(self,*args,**kwargs):
        self.total=0
        super().new_file(*args,**kwargs)
    def receive_data_chunk(self,raw_data,start):
        self.total+=len(raw_data)
        if self.total>2*1024*1024:
            self.request.upload_rejected=True
            raise StopUpload(connection_reset=False)
        return super().receive_data_chunk(raw_data,start)
