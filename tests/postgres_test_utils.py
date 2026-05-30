import os
import unittest

from closed_loop_kernel import KernelStore
from closed_loop_kernel.store import RESET_CONFIRMATION

# Known production DSN markers. build_postgres_store() runs DROP SCHEMA, so
# any URL matching one of these is refused with a loud RuntimeError rather
# than a silent SkipTest. Incident 2026-05-28: KERNEL_DATABASE_URL was
# exported to op_assistant_kernel and the test wiped Gary's sample data.
PRODUCTION_DSN_MARKERS = ("op_assistant_kernel",)
PLACEHOLDER_DSN_MARKERS = ("postgresql://test:test@localhost/none",)


def build_postgres_store():
    url = os.environ.get("KERNEL_DATABASE_URL")
    if not url:
        raise unittest.SkipTest("KERNEL_DATABASE_URL is required for PostgreSQL integration tests")
    for marker in PLACEHOLDER_DSN_MARKERS:
        if marker in url:
            raise unittest.SkipTest("KERNEL_DATABASE_URL points at an op-assistant unit-test placeholder")
    for marker in PRODUCTION_DSN_MARKERS:
        if marker in url:
            raise RuntimeError(
                f"PRODUCTION SAFEGUARD: refusing destructive test against DSN containing {marker!r}. "
                f"Point KERNEL_DATABASE_URL at a disposable test database "
                f"(e.g. postgresql://localhost/kernel_test) before retrying."
            )
    try:
        store = KernelStore.from_url(url)
    except RuntimeError as exc:
        if "optional 'psycopg' package" in str(exc):
            raise unittest.SkipTest("psycopg is required for PostgreSQL integration tests") from exc
        raise
    try:
        store.reset_for_test(confirm=RESET_CONFIRMATION)
        store.initialize()
    except Exception:
        store.close()
        raise
    return store
