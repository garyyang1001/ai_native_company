import unittest
from pathlib import Path

from closed_loop_kernel.profile_registry import AgentProfileRegistry, ProfileRegistryError


REGISTRY_PATH = Path("data/agent-profile-registry-v0.json")


class AgentProfileRegistryTests(unittest.TestCase):
    def test_v0_seed_profiles_declare_ai_native_data_flow_policy(self):
        registry = AgentProfileRegistry.from_path(REGISTRY_PATH)

        registry.validate()

        self.assertEqual(
            registry.permanent_profile_ids(),
            [
                "growth-coordinator",
                "gsc-analyst",
                "ga4-analyst",
                "seo-content-strategist",
                "reviewer",
                "sandbox-verifier",
                "memory-curator",
                "profile-maintainer",
                "outcome-monitor",
            ],
        )
        self.assertEqual(
            registry.dynamic_profile_ids(),
            [
                "social-listener",
                "competitor-monitor",
                "research-analyst",
                "youtube-transcript-agent",
                "content-producer",
                "social-operator",
            ],
        )

        for profile in registry.profiles:
            policy = profile["data_flow_policy"]
            required_fields = set(policy["required_fields"])
            self.assertTrue(policy["record_required"], profile["profile_id"])
            self.assertTrue(policy["machine_record_required"], profile["profile_id"])
            self.assertTrue(policy["source_refs_required"], profile["profile_id"])
            self.assertTrue(policy["artifact_refs_required"], profile["profile_id"])
            self.assertTrue(policy["cleanup_required"], profile["profile_id"])
            self.assertGreaterEqual(
                required_fields,
                {
                    "task_id",
                    "run_id",
                    "profile_id",
                    "source_refs",
                    "artifact_refs",
                    "content_hash",
                    "created_at",
                    "sensitivity",
                    "retention_policy",
                    "machine_record",
                },
            )
            self.assertFalse(policy["promoted_memory_allowed"], profile["profile_id"])

    def test_output_envelope_must_be_readable_recordable_reviewable_and_cleanable(self):
        registry = AgentProfileRegistry.from_path(REGISTRY_PATH)

        with self.assertRaisesRegex(ProfileRegistryError, "source_refs"):
            registry.validate_output_envelope(
                "gsc-analyst",
                {
                    "task_id": "task_1",
                    "run_id": "run_1",
                    "profile_id": "gsc-analyst",
                    "output_type": "gsc_opportunity_report",
                    "artifact_refs": ["artifact_1"],
                    "content_hash": "sha256:abc",
                    "created_at": "2026-05-23T00:00:00+08:00",
                    "sensitivity": "internal",
                    "retention_policy": "artifact_long_term",
                    "machine_record": {},
                },
            )

        registry.validate_output_envelope(
            "gsc-analyst",
            {
                "task_id": "task_1",
                "run_id": "run_1",
                "profile_id": "gsc-analyst",
                "output_type": "gsc_opportunity_report",
                "source_refs": ["src_1"],
                "artifact_refs": ["artifact_1"],
                "content_hash": "sha256:abc",
                "created_at": "2026-05-23T00:00:00+08:00",
                "sensitivity": "internal",
                "retention_policy": "artifact_long_term",
                "machine_record": {"summary": "query opportunity"},
                "memory_candidates": [],
            },
        )

        with self.assertRaisesRegex(ProfileRegistryError, "run_id"):
            registry.validate_output_envelope(
                "gsc-analyst",
                {
                    "task_id": "task_1",
                    "profile_id": "gsc-analyst",
                    "output_type": "gsc_opportunity_report",
                    "source_refs": ["src_1"],
                    "artifact_refs": ["artifact_1"],
                    "content_hash": "sha256:abc",
                    "created_at": "2026-05-23T00:00:00+08:00",
                    "sensitivity": "internal",
                    "retention_policy": "artifact_long_term",
                    "machine_record": {"summary": "query opportunity"},
                },
            )

        with self.assertRaisesRegex(ProfileRegistryError, "artifact_refs"):
            registry.validate_output_envelope(
                "gsc-analyst",
                {
                    "task_id": "task_1",
                    "run_id": "run_1",
                    "profile_id": "gsc-analyst",
                    "output_type": "gsc_opportunity_report",
                    "source_refs": ["src_1"],
                    "artifact_refs": [],
                    "content_hash": "sha256:abc",
                    "created_at": "2026-05-23T00:00:00+08:00",
                    "sensitivity": "internal",
                    "retention_policy": "artifact_long_term",
                    "machine_record": {"summary": "query opportunity"},
                },
            )

        with self.assertRaisesRegex(ProfileRegistryError, "promoted memory"):
            registry.validate_output_envelope(
                "gsc-analyst",
                {
                    "task_id": "task_1",
                    "run_id": "run_1",
                    "profile_id": "gsc-analyst",
                    "output_type": "gsc_opportunity_report",
                    "source_refs": ["src_1"],
                    "artifact_refs": ["artifact_1"],
                    "content_hash": "sha256:abc",
                    "created_at": "2026-05-23T00:00:00+08:00",
                    "sensitivity": "internal",
                    "retention_policy": "artifact_long_term",
                    "machine_record": {"summary": "query opportunity"},
                    "promoted_memory": {"fact": "raw data should not become memory directly"},
                },
            )

    def test_profile_update_roles_must_be_isolated(self):
        registry = AgentProfileRegistry.from_path(REGISTRY_PATH)

        registry.validate_role_isolation(
            {
                "operation": "profile_update",
                "executor_profile": "gsc-analyst",
                "maintainer_profile": "profile-maintainer",
                "verifier_profile": "sandbox-verifier",
                "reviewer_profile": "reviewer",
                "approver": "human_dri:gary",
                "applier": "kernel-engine",
            }
        )

        with self.assertRaisesRegex(ProfileRegistryError, "self-review"):
            registry.validate_role_isolation(
                {
                    "operation": "profile_update",
                    "executor_profile": "gsc-analyst",
                    "maintainer_profile": "profile-maintainer",
                    "verifier_profile": "sandbox-verifier",
                    "reviewer_profile": "gsc-analyst",
                    "approver": "human_dri:gary",
                    "applier": "kernel-engine",
                }
            )

        with self.assertRaisesRegex(ProfileRegistryError, "profile-maintainer"):
            registry.validate_role_isolation(
                {
                    "operation": "profile_update",
                    "executor_profile": "gsc-analyst",
                    "maintainer_profile": "profile-maintainer",
                    "verifier_profile": "profile-maintainer",
                    "reviewer_profile": "reviewer",
                    "approver": "human_dri:gary",
                    "applier": "kernel-engine",
                }
            )

        with self.assertRaisesRegex(ProfileRegistryError, "missing required role"):
            registry.validate_role_isolation(
                {
                    "operation": "profile_update",
                    "executor_profile": "gsc-analyst",
                    "maintainer_profile": "profile-maintainer",
                    "reviewer_profile": "reviewer",
                    "approver": "human_dri:gary",
                    "applier": "kernel-engine",
                }
            )

        with self.assertRaisesRegex(ProfileRegistryError, "gsc-analyst"):
            registry.validate_role_isolation(
                {
                    "operation": "profile_update",
                    "executor_profile": "gsc-analyst",
                    "maintainer_profile": "gsc-analyst",
                    "verifier_profile": "sandbox-verifier",
                    "reviewer_profile": "reviewer",
                    "approver": "human_dri:gary",
                    "applier": "kernel-engine",
                }
            )

    def test_output_envelope_blocks_potential_credential_leaks(self):
        registry = AgentProfileRegistry.from_path(REGISTRY_PATH)

        with self.assertRaisesRegex(ProfileRegistryError, "potential credential leak detected"):
            registry.validate_output_envelope(
                "gsc-analyst",
                {
                    "task_id": "task_1",
                    "run_id": "run_1",
                    "profile_id": "gsc-analyst",
                    "output_type": "gsc_opportunity_report",
                    "source_refs": ["src_1"],
                    "artifact_refs": ["artifact_1"],
                    "content_hash": "sha256:abc",
                    "created_at": "2026-05-23T00:00:00+08:00",
                    "sensitivity": "internal",
                    "retention_policy": "artifact_long_term",
                    "machine_record": {
                        "summary": "Potential leak: AIzaSyDUMMYDUMMYDUMMYDUMMYDUMMYDUMMYDUM"
                    },
                },
            )


if __name__ == "__main__":
    unittest.main()
