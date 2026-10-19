#!/usr/bin/env python3
"""Mi Fitness own-account cloud reader. Nonofficial; read-only API allowlist.
No live calls unless `login` or `sync` is explicitly selected. Does not claim full history.
"""
from __future__ import annotations
import argparse,asyncio,base64,csv,datetime,hashlib,json,os,sqlite3,sys,tempfile,uuid
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parent
STREAMS={
 'fitness':('/app/v1/data/get_fitness_data_by_watermark','data_list'),
 'aggregated':('/app/v1/data/get_aggregated_fitness_data_by_watermark','data_list'),
 'sports':('/app/v1/data/get_sport_records_by_watermark','sport_records'),
 'project':('/app/v1/data/get_project_data_by_watermark','data_list'),
}
READ_PATHS={v[0] for v in STREAMS.values()}|{'/app/v1/data/get_max_watermark'}
class ExportError(Exception):pass

def canonical(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'),sort_keys=True)
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def private_json(path,value):
 path=Path(path);path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
 fd,name=tempfile.mkstemp(prefix='.'+path.name,dir=path.parent)
 try:
  with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(canonical(value)+'\n');f.flush();os.fsync(f.fileno())
  os.chmod(name,0o600);os.replace(name,path)
 finally:
  if os.path.exists(name):os.unlink(name)
def ensure_private(path):
 path=Path(path);path.mkdir(mode=0o700,parents=True,exist_ok=True);path.chmod(0o700);return path

def token_load(path):
 p=Path(path)
 if p.is_symlink() or not p.is_file():raise ExportError('TOKEN_FILE_MISSING_OR_SYMLINK')
 if p.stat().st_mode&0o077:raise ExportError('TOKEN_FILE_PERMISSIONS_REQUIRE_600')
 d=json.loads(p.read_text())
 for k in ['user_id','c_user_id','service_token','ssecurity']:
  if not isinstance(d.get(k),str) or not d[k]:raise ExportError('TOKEN_FIELD_MISSING:'+k)
 try:assert len(base64.b64decode(d['ssecurity'],validate=True))>0
 except Exception:raise ExportError('INVALID_SSECURITY_ENCODING') from None
 return d

def allow_path(path):
 if path not in READ_PATHS:raise ExportError('WRITE_OR_UNKNOWN_ENDPOINT_BLOCKED')

async def official_auth_request(request):
 u=urlsplit(str(request.url));h=u.hostname or ''
 if u.scheme!='https' or not(h in ['mi.com','xiaomi.com'] or h.endswith('.mi.com') or h.endswith('.xiaomi.com')):
  raise ExportError('NON_XIAOMI_AUTH_DESTINATION_BLOCKED')

async def login(token_path,qr_path,web=False):
 from loguru import logger
 logger.remove() # Upstream debug logs include user IDs / partial keys: never forward them.
 from mi_fitness.auth import XiaomiAuth
 import qrcode
 async def display(_image_url,login_url):
  u=urlsplit(login_url);h=u.hostname or ''
  if u.scheme!='https' or not(h=='xiaomi.com' or h.endswith('.xiaomi.com') or h=='mi.com' or h.endswith('.mi.com')):raise ExportError('UNEXPECTED_QR_URL')
  q=Path(qr_path);ensure_private(q.parent)
  if web:
   link=q.parent/'web-login.private.json';private_json(link,{'login_url':login_url})
   print('WEB_LOGIN_READY '+str(link.resolve()),flush=True)
   print('请在打开的小米官方网页完成登录；不要把密码或验证码发到聊天。',flush=True)
  else:
   qrcode.make(login_url).save(q);q.chmod(0o600)
   print('QR_READY '+str(q.resolve()),flush=True)
   print('请用本人小米账号扫码，并核对授权页面；二维码有效期由小米决定。',flush=True)
 async with XiaomiAuth() as auth:
  auth._ensure_http().event_hooks['request'].append(official_auth_request)
  await auth.login_qr(qr_callback=display,max_wait=300)
  data=auth.token.model_dump()
  # Validate paired session fields before replacing a previous working token.
  for k in ['user_id','c_user_id','service_token','ssecurity']:
   if not data.get(k):raise ExportError('LOGIN_INCOMPLETE:'+k)
  private_json(token_path,data)
 print('LOGIN_SAVED (no credential values printed)',flush=True)

class LiveAPI:
 def __init__(self,token_path):self.token_path=Path(token_path);self.token=token_load(token_path);self.http=None
 async def __aenter__(self):
  from loguru import logger
  logger.remove()
  import httpx
  self.http=httpx.AsyncClient(timeout=30,follow_redirects=False,trust_env=False,headers={'User-Agent':'iOS-27.0.1-3.53.0','region_tag':'cn','handleparams':'true'})
  return self
 async def __aexit__(self,*_):await self.http.aclose()
 async def refresh(self):
  if not self.token.get('pass_token'):raise ExportError('AUTH_EXPIRED_RESCAN_REQUIRED')
  from mi_fitness.auth import XiaomiAuth
  async with XiaomiAuth.from_token(self.token_path) as auth:
   auth._ensure_http().event_hooks['request'].append(official_auth_request)
   auth.save_token=lambda path:private_json(path,auth.token.model_dump())
   await auth.refresh()
   self.token=token_load(self.token_path)
 async def call(self,path,params):
  allow_path(path)
  from mi_fitness.crypto import build_encrypted_params,decrypt_response
  import httpx
  for auth_try in range(2):
   form=build_encrypted_params('POST',path,self.token['ssecurity'],params)
   # Only these own-account read paths can reach the network; never replay HAR uploads.
   response=None
   for attempt in range(3):
    try:
     response=await self.http.post('https://hlth.io.mi.com'+path,data=form,cookies={'cUserId':self.token['c_user_id'],'serviceToken':self.token['service_token'],'locale':'zh_cn'})
    except (httpx.NetworkError,httpx.TimeoutException):
     if attempt==2:raise ExportError('NETWORK_FAILURE') from None
     await asyncio.sleep(2**attempt);continue
    if response.status_code in [429,500,502,503,504] and attempt<2:await asyncio.sleep(2**attempt);continue
    break
   if response is None:raise ExportError('NO_RESPONSE')
   if response.status_code in [401,403] and not auth_try:await self.refresh();continue
   if response.status_code!=200:raise ExportError('HTTP_'+str(response.status_code))
   try:body=decrypt_response(self.token['ssecurity'],form['_nonce'],response.text)
   except Exception:
    try:body=response.json()
    except Exception:raise ExportError('RESPONSE_DECRYPTION_FAILED') from None
   if not isinstance(body,dict):raise ExportError('RESPONSE_NOT_OBJECT')
   if str(body.get('code'))=='2' and not auth_try:await self.refresh();continue
   if str(body.get('code'))!='0':raise ExportError('BUSINESS_CODE_'+str(body.get('code','MISSING'))[:30])
   return body,{'request_nonce':form['_nonce'],'response_ciphertext':response.text,'http_status':response.status_code}
  raise ExportError('AUTH_EXPIRED_RESCAN_REQUIRED')

class Store:
 def __init__(self,path,account):
  self.path=Path(path);ensure_private(self.path.parent);self.db=sqlite3.connect(self.path);self.path.chmod(0o600)
  self.db.execute('PRAGMA foreign_keys=ON');self.db.execute('PRAGMA journal_mode=DELETE')
  self.db.executescript('''CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY,v TEXT);
  CREATE TABLE IF NOT EXISTS cursor(stream TEXT PRIMARY KEY,watermark TEXT NOT NULL,status TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS pages(id TEXT PRIMARY KEY,stream TEXT NOT NULL,body TEXT NOT NULL,transport TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS records(stream TEXT NOT NULL,id TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(stream,id));''')
  self.account=digest(account);old=self.db.execute("SELECT v FROM meta WHERE k='account'").fetchone()
  if old and old[0]!=self.account:self.db.close();raise ExportError('ACCOUNT_MISMATCH_USE_SEPARATE_DATABASE')
  with self.db:self.db.execute("INSERT OR IGNORE INTO meta VALUES('account',?)",(self.account,))
 def close(self):self.db.close()
 def cursor(self,stream):
  r=self.db.execute('SELECT watermark FROM cursor WHERE stream=?',(stream,)).fetchone();return int(r[0]) if r else 0
 def save(self,stream,body,transport,records,watermark,status):
  with self.db:
   self.db.execute('INSERT OR IGNORE INTO pages VALUES(?,?,?,?)',(digest([stream,body]),stream,canonical(body),canonical(transport)))
   for item in records:self.db.execute('INSERT OR IGNORE INTO records VALUES(?,?,?)',(stream,digest(item),canonical(item)))
   self.db.execute('INSERT OR REPLACE INTO cursor VALUES(?,?,?)',(stream,str(watermark),status))
 def raw_only(self,stream,body,transport):
  with self.db:self.db.execute('INSERT OR IGNORE INTO pages VALUES(?,?,?,?)',(digest([stream,body]),stream,canonical(body),canonical(transport)))
 def manifest(self):
  return {'full_history_verified':False,'coverage_note':'Only observed watermark feeds; historical completeness and unqueried categories remain unverified.','streams':[{'stream':r[0],'watermark':r[1],'status':r[2]} for r in self.db.execute('SELECT stream,watermark,status FROM cursor ORDER BY stream')],'pages':self.db.execute('SELECT count(*) FROM pages').fetchone()[0],'unique_raw_records':self.db.execute('SELECT count(*) FROM records').fetchone()[0]}
 def export(self,parent):
  folder=ensure_private(parent)/(datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]);folder.mkdir(mode=0o700)
  for table in ['pages','records']:
   p=folder/(table+'.jsonl')
   with p.open('w',encoding='utf-8') as f:
    for stream,body in self.db.execute('SELECT stream,body FROM '+table+' ORDER BY stream,id'):f.write(canonical({'stream':stream,'raw':json.loads(body)})+'\n')
   p.chmod(0o600)
  p=folder/'records.csv'
  with p.open('w',encoding='utf-8-sig',newline='') as f:
   w=csv.writer(f);w.writerow(['stream','content_sha256','raw_json'])
   for row in self.db.execute('SELECT stream,id,body FROM records ORDER BY stream,id'):w.writerow(row)
  p.chmod(0o600);manifest=self.manifest();manifest['export_files']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
  private_json(folder/'manifest.json',manifest);return folder

async def sync_stream(api,store,stream,max_pages=200,interval=1.0):
 path,field=STREAMS[stream];watermark=store.cursor(stream);seen=set()
 for page in range(max_pages):
  if interval:await asyncio.sleep(interval)
  params={'waterMark':watermark}
  if stream=='aggregated':params['tag']='daily_fitness'
  body,transport=await api.call(path,params)
  if str(body.get('code'))!='0':raise ExportError('BUSINESS_STATUS_NOT_SUCCESS')
  r=body.get('result')
  if not isinstance(r,dict):store.raw_only(stream,body,transport);raise ExportError('RESULT_SCHEMA_UNKNOWN_RAW_PAGE_SAVED')
  # Do not silently treat a changed response schema as an empty, completed export.
  batch=r.get(field)
  if batch is None:store.raw_only(stream,body,transport);raise ExportError('RECORD_FIELD_UNKNOWN_RAW_PAGE_SAVED:'+field)
  more=r.get('has_more');n=r.get('watermark')
  if not isinstance(batch,list) or not isinstance(more,bool) or not isinstance(n,int) or isinstance(n,bool) or n<0:
   store.raw_only(stream,body,transport);raise ExportError('PAGINATION_SCHEMA_UNKNOWN_RAW_PAGE_SAVED')
  if any(not isinstance(item,dict) for item in batch):store.raw_only(stream,body,transport);raise ExportError('RECORD_SCHEMA_UNKNOWN_RAW_PAGE_SAVED')
  seed=(watermark==0 and n>0 and not batch)
  if more and n>0 and n<watermark:store.raw_only(stream,body,transport);raise ExportError('WATERMARK_REGRESSION_RAW_PAGE_SAVED')
  advancing=(n>watermark)
  stalled=more and (not advancing or n in seen)
  last=watermark if n==0 or stalled else max(watermark,n)
  status='stalled_incomplete' if stalled else 'more' if more or seed else 'server_reported_end_not_full_history'
  store.save(stream,body,transport,batch,last,status)
  if stalled:raise ExportError('CURSOR_STALLED_INCOMPLETE')
  if not more and not seed:return {'stream':stream,'pages_this_run':page+1,'status':status}
  seen.add(n);watermark=last
 # A page cap is an incomplete run, never a successful "all data" claim.
 with store.db:store.db.execute("UPDATE cursor SET status='page_limit_incomplete' WHERE stream=?",(stream,))
 raise ExportError('PAGE_LIMIT_INCOMPLETE_RESUME_AVAILABLE')

async def sync_run(args):
 tok=token_load(args.token);store=Store(args.db,tok['user_id']);results=[];failed=False
 try:
  async with LiveAPI(args.token) as api:
   for stream in args.streams.split(','):
    if stream not in STREAMS:raise ExportError('UNKNOWN_STREAM')
    try:results.append(await sync_stream(api,store,stream,args.max_pages,args.interval))
    except Exception as e:
     failed=True;results.append({'stream':stream,'status':'failed','error':str(e) if isinstance(e,ExportError) else type(e).__name__})
  out=None
  if not args.no_export:
   out=store.export(args.exports);private_json(out/'run.json',{'results':results,'full_history_verified':False})
  print(canonical({'output':str(out) if out else None,'results':results,'full_history_verified':False,'record_count':store.manifest()['unique_raw_records']}));return 2 if failed else 0
 finally:store.close()

def main():
 os.umask(0o077)
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['status','login','sync','export']);p.add_argument('--token',type=Path,default=ROOT/'private/token.json');p.add_argument('--db',type=Path,default=ROOT/'private/health.sqlite');p.add_argument('--exports',type=Path,default=ROOT/'private/exports');p.add_argument('--streams',default='fitness,aggregated,sports');p.add_argument('--web',action='store_true',help='Use the official browser login URL instead of displaying a QR code');p.add_argument('--no-export',action='store_true',help='Persist pages only; avoid repeated full snapshots during historical backfill');p.add_argument('--max-pages',type=int,default=200);p.add_argument('--interval',type=float,default=1.0);a=p.parse_args()
 if a.max_pages<1 or a.interval<0:p.error('invalid page cap or interval')
 try:
  if a.command=='status':
   ready=False
   if a.token.exists():token_load(a.token);ready=True
   print(canonical({'credentials_ready':ready,'live_cloud_verified':False,'data_host':'hlth.io.mi.com','streams':list(STREAMS),'full_history_verified':False}));return 0
  if a.command=='login':asyncio.run(login(a.token,ROOT/'private/login-qr.png',web=a.web));return 0
  if a.command=='sync':return asyncio.run(sync_run(a))
  tok=token_load(a.token)
  if not a.db.is_file():raise ExportError('DATABASE_MISSING')
  s=Store(a.db,tok['user_id'])
  try:print(s.export(a.exports))
  finally:s.close()
  return 0
 except KeyboardInterrupt:print('INTERRUPTED',file=sys.stderr);return 130
 except Exception as e:
  print('ERROR '+(str(e) if isinstance(e,ExportError) else type(e).__name__),file=sys.stderr);return 3
if __name__=='__main__':raise SystemExit(main())
