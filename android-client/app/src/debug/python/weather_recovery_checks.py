import io,json,unittest
import weather_recovery_tests
def run():
 stream=io.StringIO();result=unittest.TextTestRunner(stream=stream).run(unittest.defaultTestLoader.loadTestsFromModule(weather_recovery_tests))
 if not result.wasSuccessful():raise AssertionError(stream.getvalue())
 return json.dumps(dict(passed=True,tests=result.testsRun))
