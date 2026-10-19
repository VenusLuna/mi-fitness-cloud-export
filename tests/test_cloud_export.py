import asyncio,base64,json,sqlite3,tempfile,unittest
from pathlib import Path
import cloud_export_web as c

class Fake:
 def __init__(self,pages):self.pages=iter(pages);self.calls=[]
 async def call(self,path,params):self.calls.append((path,params));return next(self.pages),{'fixture':True}
def page(rows,wm,more):return {'code':0,'result':{'data_list':rows,'watermark':wm,'has_more':more}}

class Tests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.s=c.Store(self.root/'db.sqlite','SYNTHETIC_ACCOUNT')
 def tearDown(self):self.s.close();self.tmp.cleanup()
 def run_sync(self,pages,**kwargs):return asyncio.run(c.sync_stream(Fake(pages),self.s,'fitness',interval=0,**kwargs))
 def test_seed_then_records(self):
  a=Fake([page([],10,False),page([{'sid':'fixture','time':1,'value':{'heart_rate':65}}],20,False)])
  asyncio.run(c.sync_stream(a,self.s,'fitness',interval=0));self.assertEqual([x[1]['waterMark'] for x in a.calls],[0,10]);self.assertEqual(self.s.cursor('fitness'),20)
 def test_zero_tail_preserves_cursor(self):
  self.run_sync([page([{'time':1}],10,True),page([],0,False)]);self.assertEqual(self.s.cursor('fitness'),10)
 def test_no_loss_when_same_time_different_source(self):
  self.run_sync([page([{'time':1,'sid':'A','value':60},{'time':1,'sid':'B','value':65}],10,False)])
  self.assertEqual(self.s.manifest()['unique_raw_records'],2)
 def test_repeat_is_idempotent(self):
  p=page([{'time':1,'value':60}],10,False);self.run_sync([p]);self.run_sync([p]);self.assertEqual(self.s.manifest()['unique_raw_records'],1)
 def test_stalled_incomplete(self):
  with self.assertRaisesRegex(c.ExportError,'CURSOR_STALLED'):self.run_sync([page([],0,True)])
  self.assertEqual(self.s.cursor('fitness'),0)
 def test_page_cap_incomplete(self):
  with self.assertRaisesRegex(c.ExportError,'PAGE_LIMIT'):self.run_sync([page([{'time':1}],10,True)],max_pages=1)
  self.assertEqual(self.s.manifest()['streams'][0]['status'],'page_limit_incomplete')
 def test_missing_schema_preserves_raw_without_cursor(self):
  with self.assertRaisesRegex(c.ExportError,'RECORD_FIELD_UNKNOWN'):self.run_sync([{'code':0,'result':{'watermark':10,'has_more':False,'unknown_records':[{'a':1}]}}])
  self.assertEqual(self.s.cursor('fitness'),0);self.assertEqual(self.s.manifest()['pages'],1)
 def test_nonzero_business_status_rejected(self):
  with self.assertRaisesRegex(c.ExportError,'BUSINESS'):self.run_sync([{'code':-1}])
  self.assertEqual(self.s.manifest()['pages'],0)
 def test_account_mixing_rejected(self):
  with self.assertRaisesRegex(c.ExportError,'ACCOUNT_MISMATCH'):c.Store(self.root/'db.sqlite','OTHER_ACCOUNT')
 def test_write_paths_blocked(self):
  for p in ['/app/v1/data/up_fitness_data','/app/v1/relatives/delete_relative','https://example.com/']:
   with self.assertRaises(c.ExportError):c.allow_path(p)
 def test_export_and_hashes(self):
  self.run_sync([page([{'time':1,'value':{'sleep':[1,2],'unknown':'KEEP_ME'}}],10,False)])
  out=self.s.export(self.root/'exports');m=json.loads((out/'manifest.json').read_text());self.assertFalse(m['full_history_verified'])
  for name,h in m['export_files'].items():self.assertEqual(c.hashlib.sha256((out/name).read_bytes()).hexdigest(),h)
  self.assertIn('KEEP_ME',(out/'records.jsonl').read_text());self.assertEqual((out/'records.csv').stat().st_mode&0o777,0o600)
 def test_sqlite_transaction_rolls_back(self):
  self.s.db.execute("CREATE TRIGGER fail_records BEFORE INSERT ON records BEGIN SELECT RAISE(ABORT,'fixture');END;")
  with self.assertRaises(sqlite3.IntegrityError):self.run_sync([page([{'time':1}],10,False)])
  self.assertEqual(self.s.cursor('fitness'),0);self.assertEqual(self.s.manifest()['pages'],0)
 def test_token_permissions(self):
  p=self.root/'token.json';c.private_json(p,{'user_id':'fixture','c_user_id':'fixture','service_token':'FAKE_TOKEN','ssecurity':base64.b64encode(b'fixture').decode()})
  self.assertEqual(c.token_load(p)['user_id'],'fixture');p.chmod(0o644)
  with self.assertRaisesRegex(c.ExportError,'PERMISSIONS'):c.token_load(p)
 def test_crypto_roundtrip_and_stream_signatures(self):
  from mi_fitness.crypto import compute_signed_nonce,encrypt_data,decrypt_response,build_encrypted_params,_rc4_crypt
  security=base64.b64encode(b'0123456789abcdef').decode();nonce=base64.b64encode(bytes(range(12))).decode();data={'code':0,'result':{'sleep':{'unknown':'preserved'}}}
  key=compute_signed_nonce(security,nonce);enc=encrypt_data(key,c.canonical(data));self.assertEqual(decrypt_response(security,nonce,enc),data)
  params=build_encrypted_params('POST','/app/v1/data/get_max_watermark',security,{'type':0})
  sk=base64.b64decode(compute_signed_nonce(security,params['_nonce']));plaintext=_rc4_crypt(sk,base64.b64decode(params['data'])+base64.b64decode(params['rc4_hash__']))
  self.assertTrue(plaintext.startswith(b'{"type":0}'));self.assertEqual(len(plaintext)-10,28)
 def test_auth_destination_guard(self):
  import httpx
  asyncio.run(c.official_auth_request(httpx.Request('GET','https://account.xiaomi.com/pass/serviceLogin')))
  for u in ['https://xiaomi.com.evil.test/','http://account.xiaomi.com/','https://example.com/']:
   with self.assertRaises(c.ExportError):asyncio.run(c.official_auth_request(httpx.Request('GET',u)))
if __name__=='__main__':unittest.main(verbosity=2)
