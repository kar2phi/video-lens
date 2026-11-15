"""Shared test setup.

Every test runs with the skill update check off (058 §2.6), so no test calls GitHub and
preflight's output stays the same between runs. Subprocesses inherit the env;
test_update_check.py clears it where it tests the check itself.
"""
import pytest


@pytest.fixture(autouse=True)
def _no_update_check(monkeypatch):
    monkeypatch.setenv("VIDEO_LENS_NO_UPDATE_CHECK", "1")
