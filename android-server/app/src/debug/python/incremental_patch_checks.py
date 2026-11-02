import json,tempfile,unittest
def run(root):
 import incremental_patch_tests,background_patch_tests
 old=tempfile.tempdir;tempfile.tempdir=root
 try:
  suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromModule(module) for module in (incremental_patch_tests,background_patch_tests)])
  result=unittest.TextTestRunner(verbosity=2).run(suite)
  if not result.wasSuccessful():raise AssertionError(str(result.errors)+str(result.failures))
  return json.dumps(dict(passed=True,tests=result.testsRun))
 finally:tempfile.tempdir=old
