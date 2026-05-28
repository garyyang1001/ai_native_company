import sqlite3
import tempfile
import unittest

from wannavegtour.outbox import KernelOutbox


class KernelOutboxTests(unittest.TestCase):
    def test_enqueue_is_idempotent(self):
        with tempfile.NamedTemporaryFile() as tmp:
            outbox = KernelOutbox(tmp.name)
            payload = {"profile_id": "op-assistant-line", "task_id": "task-1"}

            first = outbox.enqueue("outbound_decision", payload, "idem-1")
            second = outbox.enqueue("outbound_decision", payload, "idem-1")

            self.assertEqual(first, second)
            self.assertEqual(outbox.pending_count(), 1)

    def test_flush_once_marks_success_as_acked(self):
        with tempfile.NamedTemporaryFile() as tmp:
            outbox = KernelOutbox(tmp.name)
            outbox.enqueue("outbound_decision", {"task_id": "task-1"}, "idem-1")

            seen = []

            def writer(payload):
                seen.append(payload)
                return "ack-1"

            self.assertEqual(outbox.flush_once(writer), (1, 0))
            self.assertEqual(outbox.pending_count(), 0)
            self.assertEqual(seen, [{"task_id": "task-1"}])

    def test_flush_once_keeps_failed_rows_pending(self):
        with tempfile.NamedTemporaryFile() as tmp:
            outbox = KernelOutbox(tmp.name)
            outbox.enqueue("outbound_decision", {"task_id": "task-1"}, "idem-1")

            def writer(_payload):
                raise RuntimeError("postgres down")

            self.assertEqual(outbox.flush_once(writer), (0, 1))
            self.assertEqual(outbox.pending_count(), 1)

            with sqlite3.connect(tmp.name) as con:
                row = con.execute(
                    """
                    SELECT attempt_count, last_error
                    FROM kernel_outbox
                    WHERE idempotency_key = 'idem-1'
                    """
                ).fetchone()

            self.assertEqual(row[0], 1)
            self.assertIn("postgres down", row[1])


if __name__ == "__main__":
    unittest.main()
