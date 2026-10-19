import json,tempfile,unittest,csv
from pathlib import Path
import parse_health as p
class Tests(unittest.TestCase):
 def test_two_layers_and_timezone(self):
  raw={'value':'{"bpm":65}'};v,status=p.decoded_value(raw);self.assertEqual(v,{'bpm':65});self.assertEqual(status,'json_decoded');self.assertEqual(p.iso_seconds(1700000000),'2023-11-15T06:13:20+08:00')
 def test_unknown_and_arrays_preserved(self):
  self.assertEqual(p.flatten({'x':{'y':7},'a':[{'state':9}]}),{'value.x.y':7,'value.a':'[{"state":9}]'})
 def test_bad_json_not_dropped(self):self.assertEqual(p.decoded_value({'value':'NOT_JSON'}),('NOT_JSON','text_preserved'))
 def test_csv_formula_protection(self):self.assertEqual(p.safe_cell('=1+1'),"'=1+1");self.assertEqual(p.safe_cell(-3),-3)
 def test_milliseconds_not_misread_as_seconds(self):self.assertEqual(p.iso_seconds(1700000000000),'')
 def test_end_to_end(self):
  rows=[{'stream':'fitness','raw':{'key':'heart_rate','time':1700000000,'update_time':1700000428,'value':'{"bpm":65,"unknown":"KEEP"}'}},{'stream':'fitness','raw':{'key':'sleep','time':1700000000,'value':json.dumps({'items':[{'state':9,'start_time':1700000000,'end_time':1700000060}]})}}]
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);src=root/'records.jsonl';src.write_text(''.join(json.dumps(x)+'\n' for x in rows));out=root/'parsed';r=p.parse(src,out);self.assertEqual(r['records'],2);self.assertEqual(r['sleep_segments'],1)
   with (out/'sleep_segments.csv').open(encoding='utf-8-sig') as f:seg=list(csv.DictReader(f));self.assertEqual(seg[0]['state_raw'],'9');self.assertEqual(seg[0]['duration_seconds'],'60')
   self.assertIn('KEEP',(out/'parsed.jsonl').read_text());self.assertEqual((out/'parsed.jsonl').stat().st_mode&0o777,0o600)
if __name__=='__main__':unittest.main(verbosity=2)
