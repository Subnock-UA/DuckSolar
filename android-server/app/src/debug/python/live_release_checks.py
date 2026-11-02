import io,json,unittest
import live_patch_tests
def run():
    stream=io.StringIO()
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(live_patch_tests))
    if not result.wasSuccessful():raise AssertionError(stream.getvalue())
    return json.dumps(dict(passed=True,tests=result.testsRun))
