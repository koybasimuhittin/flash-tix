"""Repo-wide pytest hooks.

Database and Redis tests skip when the compose stack isn't running, which is convenient locally.
With REQUIRE_DB=1 (set in CI) every skip becomes a failure instead, so a broken stack can't
turn the integration tests into a silent green run.
"""

import os

import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.skipped and os.environ.get("REQUIRE_DB") == "1":
        report.outcome = "failed"
        report.longrepr = f"REQUIRE_DB=1 but the test was skipped: {report.longrepr}"
