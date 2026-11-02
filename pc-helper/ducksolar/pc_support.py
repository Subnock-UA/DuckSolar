"""Optional LAN support role of the existing Windows Server 0.3.4.
Only APK delivery and resumable log/backup reception; never starts EyBond.
"""
import hashlib,ipaddress,json,os,re,shutil,threading,uuid,weakref,time,socket,sys,traceback
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from .config import AppConfig
from .logservice import LogService

CONTRACT='ducksolar.lan-support.v1'
CHUNK=256*1024
LOCAL=[ipaddress.ip_network(x) for x in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','127.0.0.0/8')]

def digest_file(path,size=None):
    result=hashlib.sha256()
    with Path(path).open('rb') as stream:
        remaining=size
        while remaining is None or remaining>0:
            data=stream.read(min(1024*1024,remaining) if remaining is not None else 1024*1024)
            if not data:break
            result.update(data)
            if remaining is not None:remaining-=len(data)
    return result.hexdigest()

class LanSupport:
    def __init__(self,root,host='127.0.0.1',port=28765,release_root=None):
        self.root=Path(root).resolve();self.release_root=Path(release_root).resolve() if release_root else self.root;self.folder=self.root/'Data'/'AndroidSupport'
        self.folder.mkdir(parents=True,exist_ok=True)
        from .preparation_service import PreparationService
        self.preparation=PreparationService(self.root)
        from .migration_service import MigrationService
        self.migration=MigrationService(self.root)
        from .sync_service import SyncService
        self.history_sync=SyncService(self.root)
        self.catalog_path=self.folder/'catalog.json';self.lock=threading.Lock()
        self.file_locks=weakref.WeakValueDictionary()
        self.active_sockets=set();self.requests_done=threading.Condition(self.lock)
        ident=self.folder/'helper-id.txt'
        try:
            with ident.open('x',encoding='ascii') as stream:stream.write(uuid.uuid4().hex)
        except FileExistsError:pass
        self.identity=ident.read_text(encoding='ascii').strip()
        if not re.fullmatch('[0-9a-f]{32}',self.identity):raise ValueError('Invalid PC helper identity')
        self.logs=LogService(AppConfig(root_dir=str(self.root),log_max_bytes=1024*1024,log_backups=3),event_filename='AndroidSupport.log',protocol=False)
        self.logs.version="b2.0.0"
        self.digest_cache={};self.digest_lock=threading.Lock()
        self.transfers=threading.BoundedSemaphore(6)
        self.installation_slots=weakref.WeakValueDictionary()
        self.connections=threading.BoundedSemaphore(16)
        owner=self
        class LimitedServer(ThreadingHTTPServer):
            daemon_threads=True
            request_queue_size=32
            # Windows SO_REUSEADDR permits a second listener on the same port.
            # Exclusive ownership prevents two helpers accepting the same stream.
            allow_reuse_address=sys.platform!='win32'
            def server_bind(server):
                if sys.platform=='win32':server.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
                super().server_bind()
            def handle_error(server,request,address):
                error=sys.exc_info()[1]
                if isinstance(error,OSError):
                    owner.logs.event('Transfer peer disconnected',code='android.support.connection_ended',error=type(error).__name__)
                    return
                super().handle_error(request,address)
            def get_request(server):
                sock,address=super().get_request();sock.settimeout(15);return sock,address
            def process_request(server,request,address):
                if not owner.connections.acquire(blocking=False):
                    try:request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\nRetry-After: 2\r\nContent-Length: 0\r\n\r\n')
                    except OSError:pass
                    owner.logs.event('Connection capacity reached',code='android.support.busy',status=503)
                    server.shutdown_request(request);return
                with owner.lock:owner.active_sockets.add(request)
                try:super().process_request(request,address)
                except BaseException:
                    with owner.requests_done:owner.active_sockets.discard(request);owner.requests_done.notify_all()
                    owner.connections.release();raise
            def process_request_thread(server,request,address):
                try:super().process_request_thread(request,address)
                finally:
                    with owner.requests_done:owner.active_sockets.discard(request);owner.requests_done.notify_all()
                    owner.connections.release()
        try:self.http=LimitedServer((host,port),self._handler())
        except Exception:
            self.logs.close()
            raise
        self.slots=threading.BoundedSemaphore(16);self.thread=None
        from .archive_sync import ArchiveExport
        self.archive=ArchiveExport(self.root)
        self.reconcile_inverter_backups()
    def reconcile_inverter_backups(self):
        for complete in (self.folder/'Received').glob('*/inverter/*/latest.log'):
            try:
                installation=complete.parents[2].name;name=complete.parent.name
                if not re.fullmatch('[0-9a-f]{32}',installation) or not re.fullmatch('[A-Za-z0-9_.-]{1,160}',name):continue
                metadata=json.loads(complete.with_suffix('.revision.json').read_text(encoding='utf-8'))
                sha=metadata['sha256']
                if not re.fullmatch('[0-9a-f]{64}',sha) or complete.stat().st_size!=metadata['bytes']:raise ValueError('Invalid completed backup metadata')
                self._mirror_inverter(installation,name,sha,complete)
            except Exception as exc:
                self.logs.event('Previous inverter backup requires attention',code='android.backup.reconcile_failed',error=str(exc))
    def catalog(self):
        try:raw=json.loads(self.catalog_path.read_text(encoding='utf-8-sig'))
        except FileNotFoundError:return dict(contract=CONTRACT,helper_id=self.identity,updates=[])
        updates=[]
        for item in raw.get('updates',[]):
            component=item['component']
            if component not in ('server','client'):raise ValueError('Invalid update component')
            path=Path(item['path']).resolve(strict=True)
            if path.suffix.lower()!='.apk' or not path.is_relative_to(self.release_root):raise ValueError('APK outside project root')
            size=path.stat().st_size
            if not 0<size<=128*1024*1024:raise ValueError('Invalid APK size')
            # Metadata is prepared by the local packaging step; file integrity is
            # rechecked before serving the manifest, not trusted solely by filename.
            key=(str(path),path.stat().st_size,path.stat().st_mtime_ns,path.stat().st_ctime_ns,item['sha256'])
            with self.digest_lock:
                sha=self.digest_cache.get(key)
                if sha is None:
                    sha=digest_file(path);self.digest_cache={k:v for k,v in self.digest_cache.items() if k[0]!=str(path)};self.digest_cache[key]=sha
            if sha!=item['sha256']:raise ValueError('APK changed since catalog publication')
            updates.append({k:item[k] for k in ('component','version','version_code','package','sha256','abis') }|dict(bytes=size,url='/v1/apk/'+component))
        return dict(contract=CONTRACT,helper_id=self.identity,apk_chunks=True,updates=updates)
    def desktop(self):
        path=self.folder/'desktop-client.json'
        if not path.is_file():raise ValueError('PC client update has not been published')
        item=json.loads(path.read_text(encoding='utf-8-sig'))
        if item.get('contract')!='ducksolar.desktop-client.v1' or item.get('component')!='desktop_client' or not re.fullmatch(r'b[0-9]+\.[0-9]+\.[0-9]+',item.get('version','')) or type(item.get('version_code')) is not int or item['version_code']<=0 or not re.fullmatch('[0-9a-f]{64}',item.get('sha256','')):raise ValueError('Invalid PC client manifest')
        file=Path(item['path']).resolve(strict=True)
        if not file.is_relative_to(self.release_root) or not re.fullmatch(r'DS_PC_Client_ver\.b[0-9]+\.[0-9]+\.[0-9]+\.zip',file.name):raise ValueError('Invalid PC package path')
        stat=file.stat()
        if not 0<stat.st_size<=512*1024*1024 or stat.st_size!=item['bytes']:raise ValueError('PC package size changed')
        key=(str(file),stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns,item['sha256'])
        with self.digest_lock:
            value=self.digest_cache.get(key)
            if value is None:
                value=digest_file(file);self.digest_cache={k:v for k,v in self.digest_cache.items() if k[0]!=str(file)};self.digest_cache[key]=value
        if value!=item['sha256']:raise ValueError('PC package checksum changed')
        return {k:item[k] for k in ('contract','component','version','version_code','bytes','sha256')}|dict(url='/v1/desktop/bundle'),file
    def _apk(self,component):
        raw=json.loads(self.catalog_path.read_text(encoding='utf-8-sig'))
        item=next(x for x in raw['updates'] if x['component']==component)
        path=Path(item['path']).resolve(strict=True)
        if not path.is_relative_to(self.release_root) or path.suffix.lower()!='.apk':raise ValueError('Invalid APK path')
        return path
    def _paths(self,query):
        def field(name):
            value=query.get(name,[''])[0]
            return value
        installation=field('installation');kind=field('kind');name=field('name');sha=field('sha256')
        if not re.fullmatch('[0-9a-f]{32}',installation):raise ValueError('Invalid installation')
        if kind not in ('diagnostic','inverter'):raise ValueError('Invalid category')
        if not re.fullmatch('[A-Za-z0-9_.-]{1,160}',name) or name.startswith('.'):raise ValueError('Invalid log filename')
        if not re.fullmatch('[0-9a-f]{64}',sha):raise ValueError('Invalid digest')
        size=int(field('bytes'))
        if not 0<=size<=128*1024*1024:raise ValueError('Log exceeds revision budget')
        directory=self.folder/'Received'/installation/kind/name
        directory.mkdir(parents=True,exist_ok=True)
        if not directory.resolve().is_relative_to((self.folder/'Received').resolve()):raise ValueError('Path escaped backup root')
        part=directory/(sha+'.part')
        # Keep at most one in-progress revision per original filename.
        for abandoned in directory.glob('*.part'):
            if abandoned!=part:abandoned.unlink(missing_ok=True)
        return part,directory/'latest.log',size,sha
    def _mirror_inverter(self, installation, name, sha, complete):
        # Canonical PC0.3.4 location comes from the same app_paths contract.
        from .config import app_paths
        base=app_paths(AppConfig(root_dir=str(self.root)))['inverter_logs']/'AndroidBackups'
        directory=base/installation/name
        directory.mkdir(parents=True,exist_ok=True)
        if not directory.resolve().is_relative_to(base.resolve()):raise ValueError('Backup escaped inverter root')
        suffix=Path(name).suffix or '.log'
        destination=directory/(sha+suffix)
        if destination.exists():
            if digest_file(destination)!=sha:raise ValueError('Existing inverter backup is corrupted')
            return destination
        temporary=destination.with_suffix(destination.suffix+'.part')
        with complete.open('rb') as source,temporary.open('wb') as target:
            shutil.copyfileobj(source,target,CHUNK);target.flush();os.fsync(target.fileno())
        if digest_file(temporary)!=sha:
            temporary.unlink(missing_ok=True);raise ValueError('Inverter backup checksum mismatch')
        os.replace(temporary,destination)
        self.logs.event('Inverter archive backed up to PC0.3.4',code='android.backup.inverter_mirrored',
            installation=installation,name=name,bytes=destination.stat().st_size)
        return destination

    def _file_lock(self, query):
        # A slow inverter upload must not block unrelated diagnostic journals.
        key=tuple(query.get(name,[''])[0] for name in ('installation','kind','name'))
        with self.lock:
            lock=self.file_locks.get(key)
            if lock is None:
                lock=threading.RLock();self.file_locks[key]=lock
            return lock

    def _append_path(self, query):
        installation=query.get('installation',[''])[0];name=query.get('name',[''])[0]
        if not re.fullmatch('[0-9a-f]{32}',installation):raise ValueError('Invalid installation')
        if not re.fullmatch('[A-Za-z0-9_.-]{1,160}',name) or name.startswith('.'):raise ValueError('Invalid filename')
        from .config import app_paths
        base=app_paths(AppConfig(root_dir=str(self.root)))['inverter_logs']/'AndroidBackups'
        destination=base/installation/name/'Live'/'current.csv'
        destination.parent.mkdir(parents=True,exist_ok=True)
        if not destination.resolve().is_relative_to(base.resolve()):raise ValueError('Append path escaped root')
        if not destination.exists():
            # Continue from a completed legacy backup instead of uploading its
            # entire imported history again. Original revisions remain intact.
            previous=self.folder/'Received'/installation/'inverter'/name/'latest.log'
            meta=previous.with_suffix('.revision.json')
            try:metadata=json.loads(meta.read_text(encoding='utf-8'))
            except (OSError,ValueError):metadata={}
            if previous.exists() and previous.stat().st_size==metadata.get('bytes') and digest_file(previous)==metadata.get('sha256'):
                part=destination.with_suffix('.seed-part');shutil.copyfile(previous,part);os.replace(part,destination)
            else:destination.touch()
        return destination

    @staticmethod
    def _append_status(path,limit=None):
        size=path.stat().st_size if limit is None else limit
        with path.open('rb') as stream:
            prefix=stream.read(min(size,65536));stream.seek(max(0,size-65536));tail=stream.read(min(size,65536))
        return dict(offset=size,prefix_sha256=hashlib.sha256(prefix).hexdigest(),
                    tail_sha256=hashlib.sha256(tail).hexdigest(),anchor_bytes=65536)

    def _handler(self):
        owner=self
        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def log_message(self,*args):pass
            def send_response(self,code,message=None):
                self.result_status=code
                super().send_response(code,message)
            def end_headers(self):
                self.send_header('Connection','close')
                if getattr(self,'result_status',0)==503:self.send_header('Retry-After','2')
                super().end_headers()
            def json(self,code,value):
                data=json.dumps(value,ensure_ascii=False).encode();self.send_response(code)
                self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            def dispatch(self,write=False):
                self.close_connection=True
                supplied=self.headers.get("X-DX-Request-ID","")
                self.request_id=supplied if re.fullmatch(r"[0-9a-f-]{32,36}",supplied) else uuid.uuid4().hex;self.result_status=0
                started=time.monotonic();query={};transfer=False;installation_slot=None
                address=ipaddress.ip_address(self.client_address[0])
                if not any(address in net for net in LOCAL):return self.json(403,{'error':'LAN only'})
                if not owner.slots.acquire(blocking=False):return self.json(503,{'error':'Busy'})
                try:
                    self.connection.settimeout(15)
                    url=urlsplit(self.path);query=parse_qs(url.query,strict_parsing=True)
                    details={k:query[k][0][:160] for k in ('installation','kind','name','offset','length') if k in query}
                    owner.logs.event('Transfer request started',code='android.support.request.started',request_id=self.request_id,operation=url.path,payload_bytes=self.headers.get('Content-Length','0'),**details)
                    heavy=write or url.path.startswith('/v1/apk/') or url.path in ('/v1/desktop/bundle','/v1/archive/catalog','/v1/archive/chunk','/v1/prepared/chunk','/v1/migration/chunk','/v1/sync/block')
                    if heavy:
                        transfer=owner.transfers.acquire(blocking=False)
                        if not transfer:return self.json(503,{'error':'Transfer capacity reached','retry_after':2})
                        installation=query.get('installation',[''])[0]
                        if installation:
                            with owner.lock:
                                installation_slot=owner.installation_slots.get(installation)
                                if installation_slot is None:installation_slot=threading.BoundedSemaphore(2);owner.installation_slots[installation]=installation_slot
                            if not installation_slot.acquire(blocking=False):
                                installation_slot=None
                                return self.json(503,{'error':'Device transfer capacity reached','retry_after':2})
                    if not write and url.path=='/v1/status':return self.json(200,dict(contract=CONTRACT,helper_version="b2.0.0",helper_id=owner.identity,inverter_append=True,archive_sync=1,prepared_history=1,prepared_start=1,history_sync=1,history_sync_compressed=1,history_sync_append=1,history_sync_cas=2,history_sync_streaming=1,history_migration=2,migration_reuse=1,migration_cancel=1,preparation_model=2,desktop_client=1))
                    if write and url.path=='/v1/sync/start':
                        size=int(self.headers.get('Content-Length','0'))
                        if not 0<size<=32*1024*1024 or self.headers.get('Transfer-Encoding'):raise ValueError('Invalid sync plan')
                        return self.json(200,owner.history_sync.start(json.loads(self.rfile.read(size))))
                    if not write and url.path=='/v1/sync/need':return self.json(200,owner.history_sync.need(query.get('id',[''])[0],int(query.get('cursor',['0'])[0])))
                    if write and url.path=='/v1/sync/upload':
                        size=int(self.headers.get('Content-Length','0'))
                        if not 0<size<=CHUNK:raise ValueError('Invalid sync block')
                        return self.json(200,owner.history_sync.upload(query.get('id',[''])[0],query.get('sha256',[''])[0],self.rfile.read(size)))
                    if write and url.path in ('/v1/sync/prepare','/v1/sync/cancel'):
                        size=int(self.headers.get('Content-Length','0'))
                        if not 0<=size<=1024:raise ValueError('Invalid sync control request')
                        self.rfile.read(size);ident=query.get('id',[''])[0]
                        return self.json(200,owner.history_sync.prepare(ident) if url.path.endswith('/prepare') else owner.history_sync.cancel(ident))
                    if not write and url.path=='/v1/sync/status':return self.json(200,owner.history_sync.status(query.get('id',[''])[0]))
                    if not write and url.path=='/v1/sync/block':
                        data=owner.history_sync.block(query.get('id',[''])[0],query.get('sha256',[''])[0])
                        self.send_response(200);self.send_header('Content-Type','application/octet-stream');self.send_header('Content-Length',str(len(data)));self.send_header('X-Chunk-SHA256',hashlib.sha256(data).hexdigest());self.end_headers();self.wfile.write(data);return
                    if write and url.path=='/v1/migration/start':
                        size=int(self.headers.get('Content-Length','0'))
                        if not 0<size<=32*1024*1024 or self.headers.get('Transfer-Encoding'):raise ValueError('Invalid migration plan request')
                        return self.json(200,owner.migration.start(json.loads(self.rfile.read(size))))
                    if write and url.path=='/v1/migration/cancel':
                        length=int(self.headers.get('Content-Length','0'))
                        if not 0<=length<=1024:raise ValueError('Invalid cancel request')
                        self.rfile.read(length)
                        return self.json(200,owner.migration.cancel(query.get('id',[''])[0]))
                    if not write and url.path=='/v1/migration/status':return self.json(200,owner.migration.status(query.get('id',[''])[0]))
                    if not write and url.path=='/v1/migration/file':return self.json(200,owner.migration.file_status(query.get('id',[''])[0],query.get('name',[''])[0]))
                    if write and url.path=='/v1/migration/upload':
                        length=int(self.headers.get('Content-Length','-1'))
                        if not 0<length<=CHUNK or self.headers.get('Transfer-Encoding'):raise ValueError('Invalid migration chunk length')
                        return self.json(200,owner.migration.upload(query.get('id',[''])[0],query.get('name',[''])[0],int(query.get('offset',['-1'])[0]),self.rfile.read(length),query.get('sha256',[''])[0]))
                    if not write and url.path=='/v1/migration/chunk':
                        data=owner.migration.chunk(query.get('id',[''])[0],query.get('sha256',[''])[0],int(query.get('offset',['-1'])[0]),int(query.get('length',['0'])[0]))
                        self.send_response(200);self.send_header('Content-Length',str(len(data)));self.send_header('X-Chunk-SHA256',hashlib.sha256(data).hexdigest());self.end_headers();self.wfile.write(data);return
                    if not write and url.path=='/v1/prepared/status':return self.json(200,owner.preparation.status())
                    if write and url.path=='/v1/prepared/start':
                        size=int(self.headers.get('Content-Length','0'))
                        if not 0<size<=4096 or self.headers.get('Transfer-Encoding'):raise ValueError('Invalid model request')
                        return self.json(200,owner.preparation.start(json.loads(self.rfile.read(size))))
                    if not write and url.path=='/v1/prepared/catalog':
                        from .prepared_export import catalog
                        return self.json(200,catalog(owner.root))
                    if not write and url.path=='/v1/prepared/chunk':
                        from .prepared_export import chunk
                        data=chunk(owner.root,query.get('sha256',[''])[0],int(query.get('offset',['-1'])[0]),int(query.get('length',['0'])[0]))
                        self.send_response(200);self.send_header('Content-Length',str(len(data)));self.send_header('X-Chunk-SHA256',hashlib.sha256(data).hexdigest());self.end_headers();self.wfile.write(data);return
                    if not write and url.path=='/v1/archive/sources':return self.json(200,dict(sources=owner.archive.sources()))
                    if not write and url.path=='/v1/archive/routes':return self.json(200,owner.archive.routes(query.get('source',[''])[0]))
                    if not write and url.path=='/v1/archive/catalog':
                        return self.json(200,owner.archive.catalog(query.get('source',[''])[0],int(query.get('cursor',['0'])[0]),int(query.get('limit',['32'])[0])))
                    if not write and url.path=='/v1/archive/chunk':
                        data=owner.archive.chunk(query.get('sha256',[''])[0],int(query.get('offset',['-1'])[0]),int(query.get('length',['0'])[0]))
                        self.send_response(200);self.send_header('Content-Type','text/csv');self.send_header('Content-Length',str(len(data)))
                        self.send_header('X-Chunk-SHA256',hashlib.sha256(data).hexdigest());self.end_headers();self.wfile.write(data);return
                    if not write and url.path=='/v1/manifest':return self.json(200,owner.catalog())
                    if not write and url.path=='/v1/desktop/manifest':return self.json(200,owner.desktop()[0])
                    if not write and (url.path.startswith('/v1/apk/') or url.path=='/v1/desktop/bundle'):
                        desktop=url.path=='/v1/desktop/bundle'
                        component=url.path.rsplit('/',1)[1]
                        if not desktop and component not in ('server','client'):raise ValueError('Invalid component')
                        path=owner.desktop()[1] if desktop else owner._apk(component);size=path.stat().st_size;offset=0;end=size-1;bounded=False
                        range_header=self.headers.get('Range')
                        if range_header:
                            match=re.fullmatch(r'bytes=(\d+)-(\d*)',range_header)
                            if not match:raise ValueError('Invalid Range')
                            offset=int(match[1]);bounded=bool(match[2])
                            if offset>=size:return self.json(416,{'error':'Range outside APK'})
                            end=min(int(match[2]),size-1) if bounded else size-1
                            if end<offset or bounded and end-offset+1>CHUNK:raise ValueError('Invalid APK chunk range')
                        length=end-offset+1
                        data=None
                        if bounded:
                            with path.open('rb') as stream:stream.seek(offset);data=stream.read(length)
                            if len(data)!=length:raise ValueError('APK changed during chunk read')
                        self.send_response(206 if range_header else 200);self.send_header('Content-Type','application/zip' if desktop else 'application/vnd.android.package-archive')
                        self.send_header('Content-Length',str(length));self.send_header('Accept-Ranges','bytes')
                        if range_header:self.send_header('Content-Range',f'bytes {offset}-{end}/{size}')
                        if data is not None:self.send_header('X-Chunk-SHA256',hashlib.sha256(data).hexdigest())
                        self.end_headers()
                        if data is not None:self.wfile.write(data)
                        else:
                            with path.open('rb') as stream:
                                stream.seek(offset)
                                while data:=stream.read(CHUNK):self.wfile.write(data)
                        return
                    if url.path in ('/v1/inverter/status','/v1/inverter/chunk','/v1/inverter/digest'):
                        query['kind']=['inverter']
                        with owner._file_lock(query):
                            path=owner._append_path(query);size=path.stat().st_size
                            if url.path=='/v1/inverter/digest' and not write:
                                prefix=int(query.get('bytes',['-1'])[0])
                                if not 0<=prefix<=size:raise ValueError('Invalid verified backup prefix')
                                return self.json(200,dict(bytes=prefix,sha256=digest_file(path,prefix)))
                            if url.path=='/v1/inverter/status' and not write:return self.json(200,owner._append_status(path))
                            if not write:return self.json(405,{'error':'Invalid method'})
                            length=int(self.headers.get('Content-Length','-1'));offset=int(query.get('offset',['-1'])[0])
                            sha=query.get('sha256',[''])[0];previous=query.get('previous_tail',[''])[0]
                            if not 0<length<=CHUNK or offset<0 or not re.fullmatch('[0-9a-f]{64}',sha):raise ValueError('Invalid append chunk')
                            data=self.rfile.read(length)
                            if len(data)!=length or hashlib.sha256(data).hexdigest()!=sha:raise ValueError('Append checksum mismatch')
                            if size>=offset+length:
                                with path.open('rb') as stream:stream.seek(offset);existing=stream.read(length)
                                if hashlib.sha256(existing).hexdigest()!=sha:raise ValueError('Append retry differs from committed bytes')
                                return self.json(200,owner._append_status(path,offset+length))
                            if offset!=size:return self.json(409,{'error':'Append offset changed','offset':size})
                            status=owner._append_status(path)
                            if status['tail_sha256']!=previous:raise ValueError('Append prefix changed')
                            if shutil.disk_usage(path.parent).free<length+16*1024*1024:raise ValueError('Insufficient backup disk space')
                            with path.open('ab') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
                            owner.logs.event('Inverter data appended',code='android.backup.inverter_appended',
                                installation=query['installation'][0],name=query['name'][0],bytes=length,offset=offset+length)
                            return self.json(200,owner._append_status(path))
                    if url.path not in ('/v1/log/status','/v1/log/chunk'):return self.json(404,{'error':'Unknown operation'})
                    with owner._file_lock(query):
                        part,complete,size,sha=owner._paths(query)
                        if url.path=='/v1/log/status' and not write:
                            revision=complete.with_suffix('.revision.json')
                            try:metadata=json.loads(revision.read_text(encoding='utf-8'))
                            except (FileNotFoundError,ValueError):metadata={}
                            done=complete.exists() and complete.stat().st_size==size and metadata.get('sha256')==sha
                            if done and query['kind'][0]=='inverter':owner._mirror_inverter(query['installation'][0],query['name'][0],sha,complete)
                            return self.json(200,dict(offset=size if done else part.stat().st_size if part.exists() else 0,complete=done))
                        if not write or url.path!='/v1/log/chunk':return self.json(405,{'error':'Invalid method'})
                        length=int(self.headers.get('Content-Length','-1'));offset=int(query.get('offset',['-1'])[0])
                        if not 0<length<=CHUNK or not 0<=offset<=size or offset+length>size:raise ValueError('Invalid chunk bounds')
                        revision=complete.with_suffix('.revision.json')
                        try:metadata=json.loads(revision.read_text(encoding='utf-8'))
                        except (FileNotFoundError,ValueError):metadata={}
                        if complete.exists() and metadata.get('sha256')==sha and complete.stat().st_size==size:
                            # Consume the retry's body even when the whole file was committed.
                            if len(self.rfile.read(length))!=length:raise ValueError('Incomplete chunk')
                            if query['kind'][0]=='inverter':owner._mirror_inverter(query['installation'][0],query['name'][0],sha,complete)
                            return self.json(200,dict(offset=size,complete=True))
                        current=part.stat().st_size if part.exists() else 0
                        if offset!=current:
                            self.close_connection=True
                            return self.json(409,dict(error='Offset mismatch',offset=current,complete=False))
                        if shutil.disk_usage(part.parent).free<length+16*1024*1024:raise ValueError('Insufficient backup disk space')
                        data=self.rfile.read(length)
                        if len(data)!=length:raise ValueError('Incomplete chunk')
                        with part.open('ab') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
                        current+=length;done=False
                        if current==size:
                            if digest_file(part)!=sha:
                                # Discard only the uncommitted transfer, never a source log or completed backup.
                                part.unlink();raise ValueError('Backup checksum mismatch')
                            # Revisions replace only derived PC backup copies after checksum
                            # validation. Android source logs are never touched.
                            part.replace(complete)
                            temp=revision.with_suffix('.tmp')
                            temp.write_text(json.dumps(dict(sha256=sha,bytes=size)),encoding='utf-8');temp.replace(revision)
                            if query['kind'][0]=='inverter':owner._mirror_inverter(query['installation'][0],query['name'][0],sha,complete)
                            done=True
                            owner.logs.event('Android log received',code='android.backup.received',kind=query['kind'][0],bytes=size,installation=query['installation'][0],name=query['name'][0],sha256=sha)
                        return self.json(200,dict(offset=current,complete=done))
                except (ValueError,KeyError,StopIteration,FileNotFoundError) as exc:
                    self.close_connection=True
                    details=getattr(exc,'details',{})
                    if details:owner.logs.event('History worker launch failed',code='history.worker_launch_failed',error=str(exc),**details)
                    self.json(400,dict(error=str(exc),**{k:v for k,v in details.items() if k!='details'}))
                except (BrokenPipeError,ConnectionResetError):self.close_connection=True
                except OSError as exc:
                    self.close_connection=True;owner.logs.event('LAN support I/O failed',code='android.support.io_error',error=str(exc),exception_class=type(exc).__name__,errno=getattr(exc,'errno',None),winerror=getattr(exc,'winerror',None),filename=str(getattr(exc,'filename',None)),traceback=traceback.format_exc())
                    self.json(503,dict(error=str(exc),error_code='support.io_error',exception_class=type(exc).__name__,errno=getattr(exc,'errno',None),winerror=getattr(exc,'winerror',None)))
                finally:
                    if installation_slot is not None:installation_slot.release()
                    if transfer:owner.transfers.release()
                    owner.slots.release()
                    owner.logs.event('Transfer request completed',code='android.support.request.completed',request_id=self.request_id,operation=urlsplit(self.path).path,payload_bytes=self.headers.get('Content-Length','0'),status=self.result_status,duration_ms=round((time.monotonic()-started)*1000,1),**{k:query[k][0][:160] for k in ('installation','kind','name','offset','length') if k in query})
            def do_GET(self):self.dispatch()
            def do_POST(self):self.dispatch(True)
            def do_PUT(self):self.json(405,{'error':'Method not allowed'})
        return Handler
    def start(self):
        self.thread=threading.Thread(target=self.http.serve_forever,name='AndroidLanSupport',daemon=True);self.thread.start()
    def stop(self):
        self.http.shutdown()
        with self.lock:active=list(self.active_sockets)
        for connection in active:
            try:connection.shutdown(socket.SHUT_RDWR)
            except OSError:pass
        with self.requests_done:self.requests_done.wait_for(lambda:not self.active_sockets,timeout=16)
        self.http.server_close();self.logs.close()
        if self.thread:self.thread.join(3)

def serve(root,host='0.0.0.0',port=28765):
    helper=LanSupport(root,host,port)
    try:helper.http.serve_forever()
    except KeyboardInterrupt:pass
    finally:helper.http.server_close();helper.logs.close()
