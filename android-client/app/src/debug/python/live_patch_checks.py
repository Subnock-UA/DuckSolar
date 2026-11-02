import json,unittest
def run():
 import live_patch_tests
 result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(live_patch_tests))
 if not result.wasSuccessful():raise AssertionError(str(result.errors)+str(result.failures))
 return json.dumps(dict(passed=True,tests=result.testsRun))
