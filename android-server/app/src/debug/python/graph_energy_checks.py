import json, tempfile, unittest

def run(root):
    import graph_energy_tests
    old=tempfile.tempdir
    tempfile.tempdir=root
    try:
        suite=unittest.defaultTestLoader.loadTestsFromModule(graph_energy_tests)
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        if not result.wasSuccessful():
            raise AssertionError(str(result.errors)+str(result.failures))
        return json.dumps(dict(passed=True,tests=result.testsRun))
    finally:
        tempfile.tempdir=old
