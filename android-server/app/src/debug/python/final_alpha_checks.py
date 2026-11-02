import io,json,unittest
import final_alpha_tests

def run():
    stream=io.StringIO()
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(final_alpha_tests))
    if not result.wasSuccessful():raise AssertionError(stream.getvalue())
    return json.dumps(dict(passed=True,tests=result.testsRun,output=stream.getvalue()))
