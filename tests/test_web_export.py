import asyncio,base64,contextlib,io,json,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
import cloud_export_web as c
class FakeLive:
 def __init__(self,*_):pass
 async def __aenter__(self):return self
 async def __aexit__(self,*_):pass
 async def call(self,*_):return {'code':0,'result':{'data_list':[{'key':'heart_rate','time':1,'value':'{"bpm":65,"fixture":true}'}],'watermark':1,'has_more':False}},{'fixture':True}
class Tests(unittest.TestCase):
 def setup_args(self,root,no_export):
  t=root/'token.json';c.private_json(t,{'user_id':'FIXTURE','c_user_id':'FIXTURE','service_token':'FIXTURE','ssecurity':base64.b64encode(b'fixture').decode()})
  return types.SimpleNamespace(token=t,db=root/'db.sqlite',exports=root/'exports',streams='fitness',max_pages=2,interval=0,no_export=no_export)
 def test_no_export_avoids_full_snapshot(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=Path(tmp);a=self.setup_args(r,True);out=io.StringIO()
   with patch.object(c,'LiveAPI',FakeLive),contextlib.redirect_stdout(out):code=asyncio.run(c.sync_run(a))
   v=json.loads(out.getvalue());self.assertEqual(code,0);self.assertIsNone(v['output']);self.assertEqual(v['record_count'],1);self.assertFalse(a.exports.exists())
 def test_normal_export_still_works(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=Path(tmp);a=self.setup_args(r,False);out=io.StringIO()
   with patch.object(c,'LiveAPI',FakeLive),contextlib.redirect_stdout(out):code=asyncio.run(c.sync_run(a))
   v=json.loads(out.getvalue());self.assertEqual(code,0);self.assertEqual(json.loads((Path(v['output'])/'manifest.json').read_text())['unique_raw_records'],1)
 def test_aggregated_tag_is_required(self):
  class Capture(FakeLive):
   async def call(self,path,params):
    self.params=params
    return await super().call(path,params)
  with tempfile.TemporaryDirectory() as tmp:
   store=c.Store(Path(tmp)/'db.sqlite','FIXTURE');api=Capture()
   try:asyncio.run(c.sync_stream(api,store,'aggregated',interval=0));self.assertEqual(api.params['tag'],'daily_fitness')
   finally:store.close()
 def test_web_callback_never_requires_qr(self):
  class Auth:
   def __init__(self):self.token=types.SimpleNamespace(model_dump=lambda:{'user_id':'FIXTURE','c_user_id':'FIXTURE','service_token':'FIXTURE','ssecurity':'Zml4dHVyZQ=='});self.http=types.SimpleNamespace(event_hooks={'request':[]})
   async def __aenter__(self):return self
   async def __aexit__(self,*_):pass
   def _ensure_http(self):return self.http
   async def login_qr(self,qr_callback,max_wait):await qr_callback('https://account.xiaomi.com/image','https://ak.account.xiaomi.com/fixture-login')
  with tempfile.TemporaryDirectory() as tmp:
   r=Path(tmp)
   with patch('mi_fitness.auth.XiaomiAuth',Auth),patch('qrcode.make',side_effect=AssertionError('QR generated in web mode')),contextlib.redirect_stdout(io.StringIO()):asyncio.run(c.login(r/'token.json',r/'qr.png',web=True))
   self.assertTrue((r/'token.json').exists());self.assertFalse((r/'qr.png').exists());self.assertEqual((r/'web-login.private.json').stat().st_mode&0o777,0o600)
if __name__=='__main__':unittest.main(verbosity=2)
