import unittest,json,tempfile
def run(root):
    import next_services_tests,next_period_tests,next_patch_tests
    old=tempfile.tempdir;tempfile.tempdir=root
    try:
        suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromModule(m) for m in (next_services_tests,next_period_tests,next_patch_tests)])
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        if not result.wasSuccessful():raise AssertionError(str(result.errors)+str(result.failures))
        return json.dumps({'passed':True,'tests':result.testsRun})
    finally:tempfile.tempdir=old
