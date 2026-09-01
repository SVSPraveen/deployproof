"""Pytest plugin for DeployProof coverage-guided test selection.

Switches coverage context to the current test nodeid during pytest execution,
allowing DeployProof to map each source line to the exact test cases covering it.
"""
try:
    import coverage

    def pytest_runtest_protocol(item, nextitem):
        cov = coverage.Coverage.current()
        if cov is not None:
            cov.switch_context(item.nodeid)
except ImportError:
    pass
