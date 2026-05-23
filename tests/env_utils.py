import os
import unittest


def enable_destructive_reset_for_test(testcase: unittest.TestCase) -> None:
    previous = os.environ.get("KERNEL_ALLOW_DESTRUCTIVE_RESET")
    os.environ["KERNEL_ALLOW_DESTRUCTIVE_RESET"] = "1"

    def restore() -> None:
        if previous is None:
            os.environ.pop("KERNEL_ALLOW_DESTRUCTIVE_RESET", None)
        else:
            os.environ["KERNEL_ALLOW_DESTRUCTIVE_RESET"] = previous

    testcase.addCleanup(restore)
