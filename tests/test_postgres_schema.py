import unittest

from closed_loop_kernel.postgres import render_postgres_schema


class PostgresSchemaTests(unittest.TestCase):
    def test_schema_uses_pgcrypto_uuid_and_core_foreign_keys(self):
        ddl = render_postgres_schema()

        self.assertIn("CREATE EXTENSION IF NOT EXISTS pgcrypto;", ddl)
        self.assertIn("id UUID PRIMARY KEY DEFAULT gen_random_uuid()", ddl)
        self.assertIn("attempt_id UUID NOT NULL REFERENCES attempts(id)", ddl)
        self.assertIn("failure_id UUID NOT NULL REFERENCES failures(id)", ddl)
        self.assertIn("candidate_id UUID NOT NULL REFERENCES improvement_candidates(id)", ddl)

    def test_schema_installs_append_only_triggers_on_audit_tables(self):
        ddl = render_postgres_schema()

        self.assertIn("CREATE OR REPLACE FUNCTION prevent_mutation()", ddl)
        for table in [
            "events",
            "attempt_lifecycle_events",
            "attempts",
            "tool_calls",
            "decisions",
            "approvals",
        ]:
            self.assertIn(f"BEFORE UPDATE OR DELETE ON {table}", ddl)

    def test_schema_includes_orphan_attempt_view(self):
        ddl = render_postgres_schema()

        self.assertIn("CREATE OR REPLACE VIEW view_orphan_attempts AS", ddl)
        self.assertIn("LEFT JOIN attempts a ON le.attempt_id = a.id", ddl)
        self.assertIn("HAVING MAX(le.created_at) < NOW() - INTERVAL '5 minutes'", ddl)


if __name__ == "__main__":
    unittest.main()
