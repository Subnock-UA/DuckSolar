import json,tempfile,unittest
_battery_fixture=None

def prepare_battery(root):
 global _battery_fixture
 import android_bridge
 from pathlib import Path
 from types import SimpleNamespace
 from ducksolar.push_alerts import PushAlerts
 temp=tempfile.TemporaryDirectory(dir=root)
 hub=PushAlerts(Path(temp.name)/'alerts.json');hub.settings('test','a'*32,['inverter-1'])
 _battery_fixture=(android_bridge._runtime,temp,hub)
 android_bridge._runtime=SimpleNamespace(push_alerts=hub)

def verify_battery():
 return _battery_fixture[2].feed('test','a'*32,['inverter-1'])[0]['percent']==49

def restore_battery():
 global _battery_fixture
 import android_bridge
 android_bridge._runtime=_battery_fixture[0];_battery_fixture[1].cleanup();_battery_fixture=None

def run(root):
 import push_alert_tests,push_tls_tests,graph_summary_tests
 old=tempfile.tempdir;tempfile.tempdir=root
 try:
  suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in (push_alert_tests,push_tls_tests,graph_summary_tests))
  result=unittest.TextTestRunner(verbosity=2).run(suite)
  if not result.wasSuccessful():raise AssertionError(str(result.errors)+str(result.failures))
  return json.dumps(dict(passed=True,tests=result.testsRun))
 finally:tempfile.tempdir=old
