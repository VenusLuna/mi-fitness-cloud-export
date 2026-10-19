#!/usr/bin/env python3
"""Own-account bounded cloud pull and crash-safe incremental exports. No public server."""
import argparse,asyncio,csv,datetime,fcntl,hashlib,json,os,shutil,sys,time,uuid
from pathlib import Path
import cloud_export_web as c
from parse_health import decoded_value,iso_seconds,safe_cell
RECENT='/app/v1/data/get_fitness_data_by_time'
KEYS=('heart_rate','sleep','steps','spo2','stress','calories')
c.READ_PATHS.add(RECENT)
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def filehash(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def meta(db,k,default):
 r=db.execute('SELECT v FROM meta WHERE k=?',(k,)).fetchone()
 return json.loads(r[0]) if r else default
def delta_export(store,parent):
 db=store.db;lo=meta(db,'server_export_rowid',0);hi=db.execute('SELECT coalesce(max(rowid),0) FROM records').fetchone()[0]
 latest=meta(db,'server_latest_times',{})
 folder=c.ensure_private(parent)/(datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]);folder.mkdir(mode=0o700)
 count=0;fields=['stream','content_sha256','key','source_sid','record_time','record_time_beijing','update_time','updated_beijing','value_json','raw_json']
 with (folder/'records.jsonl').open('w',encoding='utf-8') as jf,(folder/'records.csv').open('w',encoding='utf-8-sig',newline='') as cf:
  writer=csv.DictWriter(cf,fieldnames=fields);writer.writeheader()
  for rowid,stream,identity,body in db.execute('SELECT rowid,stream,id,body FROM records WHERE rowid>? AND rowid<=? ORDER BY rowid',(lo,hi)):
   raw=json.loads(body);val,parse_status=decoded_value(raw);key=str(raw.get('key','UNKNOWN'));t=raw.get('time');u=raw.get('update_time')
   jf.write(c.canonical({'stream':stream,'content_sha256':identity,'raw':raw,'value_decoded':val,'value_parse_status':parse_status,'record_time_beijing':iso_seconds(t),'updated_beijing':iso_seconds(u)})+'\n')
   out=dict(zip(fields,[stream,identity,key,raw.get('sid'),t,iso_seconds(t),u,iso_seconds(u),c.canonical(val),body]));writer.writerow({k:safe_cell(v) for k,v in out.items()});count+=1
   label=stream+':'+key
   if iso_seconds(t) and t>latest.get(label,{}).get('time',0):latest[label]={'time':t,'beijing':iso_seconds(t),'update_time':u,'updated_beijing':iso_seconds(u)}
  for f in (jf,cf):f.flush();os.fsync(f.fileno())
 for p in folder.iterdir():p.chmod(0o600)
 manifest={'created_utc':now(),'rows':count,'after_rowid':lo,'through_rowid':hi,'full_history_verified':False,'format':'incremental content-addressed records; retain raw and unknown fields; times are seconds, units unscaled','files':{p.name:filehash(p) for p in folder.iterdir()}}
 c.private_json(folder/'manifest.json',manifest)
 # Export manifest and data must be durable before advancing the database checkpoint.
 fd=os.open(folder,os.O_RDONLY)
 try:os.fsync(fd)
 finally:os.close(fd)
 with db:
  db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('server_export_rowid',json.dumps(hi)))
  db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('server_latest_times',c.canonical(latest)))
 return {'path':str(folder),'new_exported_records':count,'through_rowid':hi,'latest_times':latest}
async def recent(api,store):
 end=int(time.time()*1000);out=[]
 for key in KEYS:
  body,transport=await api.call(RECENT,{'key':key,'startTime':end-7*86400000,'endTime':end,'reverse':True,'next_key':None,'limit':1})
  # Archive every response, including unexpected schemas, before validation.
  store.raw_only('fitness_recent:'+key,body,transport)
  result=body.get('result',{});rows=result.get('data_list') if isinstance(result,dict) else None
  if not isinstance(rows,list) or any(not isinstance(x,dict) for x in rows):raise c.ExportError('RECENT_SCHEMA_UNKNOWN_RAW_SAVED')
  before=store.db.total_changes
  with store.db:
   for raw in rows:store.db.execute('INSERT OR IGNORE INTO records VALUES(?,?,?)',('fitness',c.digest(raw),c.canonical(raw)))
  out.append({'key':key,'rows_returned':len(rows),'new_rows':store.db.total_changes-before,'has_more':result.get('has_more'),'window_enforced':False,'full_window_verified':False})
  await asyncio.sleep(1)
 return out
async def pull(state,pages):
 tok=c.token_load(state/'token.json');store=c.Store(state/'health.sqlite',tok['user_id']);errors=[];results=[]
 started=now();c.private_json(state/'running.json',{'started_utc':started,'pid':os.getpid()})
 try:
  if shutil.disk_usage(state).free<4*1024**3:raise c.ExportError('DISK_FREE_BELOW_4GiB')
  async with c.LiveAPI(state/'token.json') as api:
   try:results.append({'recent':await recent(api,store)})
   except Exception as e:errors.append(str(e) if isinstance(e,c.ExportError) else type(e).__name__)
   for stream,cap in [('aggregated',5),('sports',5),('project',3),('fitness',pages)]:
    try:results.append(await c.sync_stream(api,store,stream,cap,1.0))
    except c.ExportError as e:
     if str(e)=='PAGE_LIMIT_INCOMPLETE_RESUME_AVAILABLE':results.append({'stream':stream,'status':'page_limit_incomplete_resumable'})
     else:errors.append(stream+':'+str(e))
    except Exception as e:errors.append(stream+':'+type(e).__name__)
  export=delta_export(store,state/'exports')
  manifest=store.manifest();status={'started_utc':started,'finished_utc':now(),'state':'partial_failure' if errors else 'success','errors':errors,'results':results,'export':export,**manifest,'history_pending':any(x['status']!='server_reported_end_not_full_history' for x in manifest['streams']),'coverage_note':'Four observed watermark feeds + six latest first-page queries. project returned an empty end in preflight; FDS/other channels unverified; no all-data or Apple Health claim.'}
  c.private_json(state/'status.json',status)
  print(c.canonical({'state':status['state'],'finished_utc':status['finished_utc'],'records':manifest['unique_raw_records'],'new_exported_records':export['new_exported_records'],'export_path':export['path'],'history_pending':status['history_pending'],'errors':errors}),flush=True)
  return 2 if errors else 0
 finally:
  store.close();(state/'running.json').unlink(missing_ok=True)
def main():
 os.umask(0o077);p=argparse.ArgumentParser();p.add_argument('--state',required=True,type=Path);p.add_argument('--history-pages',type=int,default=40);a=p.parse_args()
 if not 1<=a.history_pages<=100:p.error('history-pages must be 1..100')
 state=c.ensure_private(a.state)
 with (state/'.sync.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:print('ALREADY_RUNNING',file=sys.stderr);return 75
  try:return asyncio.run(asyncio.wait_for(pull(state,a.history_pages),timeout=480))
  except BaseException as e:
   if isinstance(e,(SystemExit,KeyboardInterrupt)):raise
   label=str(e) if isinstance(e,c.ExportError) else type(e).__name__
   c.private_json(state/'failure.json',{'failed_utc':now(),'error':label});print('ERROR '+label,file=sys.stderr);return 3
if __name__=='__main__':raise SystemExit(main())
