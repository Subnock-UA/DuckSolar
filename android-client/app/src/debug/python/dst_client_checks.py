import sys,unittest
from pathlib import Path
from unittest.mock import patch
from ducksolar import clock
class ClientDST(unittest.TestCase):
 def test_offline_clock_follows_both_transitions(self):
  for wall,utc,expected in [('2026-03-29T02:59:55+02:00','2026-03-29T00:59:55+00:00','2026-03-29T04:00:05'),('2026-10-25T03:59:55+03:00','2026-10-25T00:59:55+00:00','2026-10-25T03:00:05')]:
   with patch.object(clock.time,'monotonic',return_value=100):clock.update(wall,utc)
   with patch.object(clock.time,'monotonic',return_value=110):self.assertEqual(clock.now().isoformat(),expected)
 def test_historical_display_uses_date_offset(self):
  clock.update('2026-10-21T12:00:00+03:00','2026-10-21T09:00:00+00:00')
  self.assertEqual(clock.display_datetime('2026-01-01T10:00:00+00:00').hour,12)
  self.assertEqual(clock.display_datetime('2026-07-01T10:00:00+00:00').hour,13)
if __name__=='__main__':unittest.main(verbosity=2)
def run():
 import io,json
 stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
 return json.dumps(dict(passed=result.wasSuccessful(),tests=result.testsRun,output=stream.getvalue()))
