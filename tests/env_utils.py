import os
import unittest

PLACEHOLDER_TEST_DATABASE_URL = "postgresql://test:test@localhost/none"


def skip_unless_real_postgres_url(testcase: unittest.TestCase) -> str:
    url = os.environ.get("KERNEL_DATABASE_URL")
    if not url:
        testcase.skipTest("KERNEL_DATABASE_URL is required for PostgreSQL integration tests")
    if url == PLACEHOLDER_TEST_DATABASE_URL:
        testcase.skipTest("KERNEL_DATABASE_URL points at an op-assistant unit-test placeholder")
    try:
        import psycopg  # noqa: F401
    except ModuleNotFoundError:
        testcase.skipTest("psycopg is required for PostgreSQL integration tests")
    return url


def enable_destructive_reset_for_test(testcase: unittest.TestCase) -> None:
    previous = os.environ.get("KERNEL_ALLOW_DESTRUCTIVE_RESET")
    os.environ["KERNEL_ALLOW_DESTRUCTIVE_RESET"] = "1"

    def restore() -> None:
        if previous is None:
            os.environ.pop("KERNEL_ALLOW_DESTRUCTIVE_RESET", None)
        else:
            os.environ["KERNEL_ALLOW_DESTRUCTIVE_RESET"] = previous

    testcase.addCleanup(restore)
