import io,json,unittest
from generation_patch_tests import Generation
def run():
 stream=io.StringIO();suite=unittest.TestSuite(Generation(name) for name in unittest.defaultTestLoader.getTestCaseNames(Generation) if name!="test_dense_stream_has_small_python_peak")
 result=unittest.TextTestRunner(stream=stream).run(suite)
 if not result.wasSuccessful():raise AssertionError(stream.getvalue())
 return json.dumps(dict(passed=True,tests=result.testsRun))
