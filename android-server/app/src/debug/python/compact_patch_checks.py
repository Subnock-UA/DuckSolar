import json,tempfile,unittest
def run(root):
 import compact_format_tests
 from ducksolar.server_runtime import ServerRuntime
 from ducksolar.config import AppConfig
 from ducksolar.client_sessions import SessionError
 class Maintenance(unittest.TestCase):
  def test_api_stays_available_and_restart_keeps_maintenance(self):
   with tempfile.TemporaryDirectory() as folder:
    cfg=AppConfig(root_dir=folder,api_port=0,cloud_proxy_enabled=False)
    rt=ServerRuntime(cfg)
    try:
     rt.api.start();rt.active=True;rt.enter_maintenance()
     self.assertTrue(rt.api.thread.is_alive());self.assertTrue(rt.snapshot()['maintenance']['active'])
     with self.assertRaises(SessionError):rt.api.call('history','graph_data',[],{})
     restored=ServerRuntime(cfg)
     try:self.assertTrue(restored.maintenance_mode)
     finally:restored.stop()
    finally:rt.stop()
 old=tempfile.tempdir;tempfile.tempdir=root
 try:
  suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromModule(compact_format_tests),unittest.defaultTestLoader.loadTestsFromTestCase(Maintenance)])
  result=unittest.TextTestRunner(verbosity=2).run(suite)
  if not result.wasSuccessful():raise AssertionError(str(result.errors)+str(result.failures))
  return json.dumps(dict(passed=True,tests=result.testsRun))
 finally:tempfile.tempdir=old
