#!/usr/bin/env python3
"""Offline decoder for this project's records.jsonl / SQLite snapshot.
Decodes raw.value JSON text; preserves unknown fields and raw state codes.
"""
from __future__ import annotations
import argparse,collections,csv,datetime,hashlib,json,os,re,sqlite3,tempfile
from pathlib import Path
TZ=datetime.timezone(datetime.timedelta(hours=8))

def iso_seconds(value):
 if isinstance(value,bool) or not isinstance(value,(int,float)) or value<=0 or value>=100_000_000_000:return ''
 try:return datetime.datetime.fromtimestamp(value,TZ).isoformat()
 except (ValueError,OverflowError,OSError):return ''
def decoded_value(raw):
 v=raw.get('value')
 if isinstance(v,str):
  try:return json.loads(v),'json_decoded'
  except ValueError:return v,'text_preserved'
 return v,'already_structured'
def flatten(value,prefix='value'):
 out={}
 if isinstance(value,dict):
  for k,v in value.items():
   key=prefix+'.'+str(k)
   if isinstance(v,dict) and v:out.update(flatten(v,key))
   elif isinstance(v,(dict,list)):out[key]=json.dumps(v,ensure_ascii=False,separators=(',',':'))
   else:out[key]=v
 else:out[prefix]=json.dumps(value,ensure_ascii=False) if isinstance(value,(list,dict)) else value
 return out
def safe_cell(value):
 if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')):return "'"+value
 if isinstance(value,str) and value.startswith(('\t','\r')):return "'"+value
 return value

def iter_records(path,sqlite=False):
 if sqlite:
  d=__import__('sqlite3').connect('file:'+str(path.resolve())+'?mode=ro',uri=True)
  try:
   d.execute('BEGIN')
   for stream,body in d.execute('SELECT stream,body FROM records ORDER BY stream,id'):yield stream,json.loads(body)
  finally:d.close()
 else:
  with path.open(encoding='utf-8-sig') as f:
   for line in f:
    if line.strip():
     e=json.loads(line);raw=e['raw']
     if not isinstance(raw,dict):raise ValueError('record raw is not an object')
     yield str(e['stream']),raw

def parse(source,out,sqlite=False):
 os.umask(0o077);out.mkdir(mode=0o700,parents=True,exist_ok=False)
 group_fields=collections.defaultdict(set);groups={};summaries={};spool_files={};count=0;segments_count=0
 decoded_path=out/'parsed.jsonl';segments_path=out/'sleep_segments.csv'
 with tempfile.TemporaryDirectory(prefix='mi-health-spools-') as tmp,decoded_path.open('w',encoding='utf-8') as decoded,segments_path.open('w',encoding='utf-8-sig',newline='') as sf:
  seg_fields=['stream','key','source_sid','parent_record_time','segment_index','state_raw','start_time','end_time','start_beijing','end_beijing','duration_seconds','raw_segment_json'];sw=csv.DictWriter(sf,fieldnames=seg_fields);sw.writeheader()
  try:
   for stream,raw in iter_records(source,sqlite):
    count+=1;key=str(raw.get('key','UNKNOWN'));group=(stream,key);v,status=decoded_value(raw)
    slug=re.sub(r'[^A-Za-z0-9_-]','_',stream+'__'+key)[:100]+'-'+hashlib.sha256((stream+'\0'+key).encode()).hexdigest()[:8]
    if group not in spool_files:spool_files[group]=(Path(tmp)/slug).open('w',encoding='utf-8');groups[group]=slug
    row={'stream':stream,'key':key,'source_sid':raw.get('sid'),'record_time':raw.get('time'),'record_time_beijing':iso_seconds(raw.get('time')),'record_update_time':raw.get('update_time'),'updated_beijing':iso_seconds(raw.get('update_time')),'source_zone_name':raw.get('zone_name'),'source_zone_offset':raw.get('zone_offset'),'value_parse_status':status,**flatten(v)}
    group_fields[group].update(row);spool_files[group].write(json.dumps(row,ensure_ascii=False)+'\n')
    decoded.write(json.dumps({'stream':stream,'raw':raw,'value_decoded':v,'record_time_beijing':row['record_time_beijing'],'updated_beijing':row['updated_beijing'],'value_parse_status':status},ensure_ascii=False)+'\n')
    summary=summaries.setdefault(group,{'stream':stream,'key':key,'records':0,'untimed_records':0,'first_time':None,'latest_time':None,'latest_record_update_time':None,'max_update_time':None,'value_fields':set(),'parse_status_counts':collections.Counter()});summary['records']+=1;summary['parse_status_counts'][status]+=1;summary['value_fields'].update(flatten(v))
    t=raw.get('time');u=raw.get('update_time')
    if iso_seconds(t):
     if summary['first_time'] is None or t<summary['first_time']:summary['first_time']=t
     if summary['latest_time'] is None or t>summary['latest_time']:summary['latest_time']=t;summary['latest_record_update_time']=u
    else:summary['untimed_records']+=1
    if iso_seconds(u) and (summary['max_update_time'] is None or u>summary['max_update_time']):summary['max_update_time']=u
    if key=='sleep' and isinstance(v,dict) and isinstance(v.get('items'),list):
     for i,item in enumerate(v['items']):
      if not isinstance(item,dict):item={'unparsed':item}
      start=item.get('start_time');end=item.get('end_time');duration=end-start if isinstance(start,(float,int)) and isinstance(end,(float,int)) and end>=start else None
      sr={'stream':stream,'key':key,'source_sid':raw.get('sid'),'parent_record_time':t,'segment_index':i,'state_raw':item.get('state'),'start_time':start,'end_time':end,'start_beijing':iso_seconds(start),'end_beijing':iso_seconds(end),'duration_seconds':duration,'raw_segment_json':json.dumps(item,ensure_ascii=False)};sw.writerow({k:safe_cell(x) for k,x in sr.items()});segments_count+=1
  finally:
   for f in spool_files.values():f.close()
  for group,slug in groups.items():
   fields=sorted(group_fields[group]);dest=out/(slug+'.csv')
   with (Path(tmp)/slug).open() as inp,dest.open('w',encoding='utf-8-sig',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
    for line in inp:writer.writerow({k:safe_cell(x) for k,x in json.loads(line).items()})
 for summary in summaries.values():
  summary['first_beijing']=iso_seconds(summary['first_time']);summary['latest_beijing']=iso_seconds(summary['latest_time']);summary['latest_record_updated_beijing']=iso_seconds(summary['latest_record_update_time']);summary['max_update_beijing']=iso_seconds(summary['max_update_time']);summary['value_fields']=sorted(summary['value_fields']);summary['parse_status_counts']=dict(summary['parse_status_counts']);summary['csv_file']=groups[(summary['stream'],summary['key'])]+'.csv'
 report={'source':str(source.resolve()),'records':count,'sleep_segments':segments_count,'display_timezone':'UTC+08:00 / Asia/Shanghai for these dates','timestamp_unit':'seconds; millisecond-looking values are deliberately not guessed','value_units':'preserved; no scaling or sleep-state-name mapping assumed','full_history_verified':False,'groups':sorted(summaries.values(),key=lambda x:(x['stream'],x['key']))}
 (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 base=['stream','key','records','first_beijing','latest_beijing','latest_record_updated_beijing','max_update_beijing','csv_file']
 with (out/'latest_times.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=base);w.writeheader();w.writerows({k:safe_cell(g.get(k)) for k in base} for g in report['groups'])
 hashes={}
 for p in out.iterdir():
  if p.is_file():p.chmod(0o600);hashes[p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
 (out/'SHA256SUMS.json').write_text(json.dumps(hashes,indent=2)+'\n');(out/'SHA256SUMS.json').chmod(0o600)
 return report

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('input',type=Path);p.add_argument('--out',required=True,type=Path);p.add_argument('--sqlite',action='store_true');a=p.parse_args();r=parse(a.input,a.out,a.sqlite);print(json.dumps({'output':str(a.out.resolve()),'records':r['records'],'groups':len(r['groups']),'sleep_segments':r['sleep_segments']},ensure_ascii=False))
if __name__=='__main__':main()
