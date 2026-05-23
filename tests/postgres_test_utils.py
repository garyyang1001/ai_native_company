import os
import unittest

from closed_loop_kernel import KernelStore
from closed_loop_kernel.store import RESET_CONFIRMATION


def build_postgres_store():
    url = os.environ.get("KERNEL_DATABASE_URL")
    if not url:
        raise unittest.SkipTest("KERNEL_DATABASE_URL is required for PostgreSQL integration tests")
    store = KernelStore.from_url(url)
    try:
        store.reset_for_test(confirm=RESET_CONFIRMATION)
        store.initialize()
    except Exception:
        store.close()
        raise
    return store
