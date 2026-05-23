import unittest
from pathlib import Path

from closed_loop_kernel.profile_registry import AgentProfileRegistry, ProfileRegistryError


REGISTRY_PATH = Path("data/agent-profile-registry-v0.json")


def valid_envelope(profile_id, output_type, **overrides):
    envelope = {
        "task_id": "task_1",
        "run_id": "run_1",
        "profile_id": profile_id,
        "output_type": output_type,
        "source_refs": ["src_1"],
        "artifact_refs": ["artifact_1"],
        "content_hash": "sha256:abc",
        "created_at": "2026-05-23T00:00:00+08:00",
        "sensitivity": "internal",
        "retention_policy": "artifact_long_term",
        "machine_record": {"summary": "valid output"},
    }
    envelope.update(overrides)
    return envelope


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

    def test_secret_scan_exempts_explicit_metadata_fields_only(self):
        registry = AgentProfileRegistry.from_path(REGISTRY_PATH)
        secret_like_value = "AIzaSyDUMMYDUMMYDUMMYDUMMYDUMMYDUMMYDUM"

        for exempt_field in [
            "content_hash",
            "created_at",
            "updated_at",
            "reviewed_at",
            "verified_at",
            "approved_at",
        ]:
            with self.subTest(exempt_field=exempt_field):
                registry.validate_output_envelope(
                    "gsc-analyst",
                    valid_envelope("gsc-analyst", "gsc_opportunity_report", **{exempt_field: secret_like_value}),
                )

        with self.assertRaisesRegex(ProfileRegistryError, "potential credential leak detected"):
            registry.validate_output_envelope(
                "gsc-analyst",
                valid_envelope(
                    "gsc-analyst",
                    "gsc_opportunity_report",
                    machine_record={"summary": secret_like_value},
                ),
            )

        with self.assertRaisesRegex(ProfileRegistryError, "potential credential leak detected"):
            registry.validate_output_envelope(
                "gsc-analyst",
                valid_envelope(
                    "gsc-analyst",
                    "gsc_opportunity_report",
                    machine_record={"content_hash": secret_like_value},
                ),
            )

    def test_secret_scan_blocks_high_entropy_strings_but_allows_hashes(self):
        registry = AgentProfileRegistry.from_path(REGISTRY_PATH)
        high_entropy_value = "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXo0123456789ABCD"
        sha256_value = "sha256:" + ("0123456789abcdef" * 4)

        with self.assertRaisesRegex(ProfileRegistryError, "potential credential leak detected"):
            registry.validate_output_envelope(
                "gsc-analyst",
                valid_envelope(
                    "gsc-analyst",
                    "gsc_opportunity_report",
                    machine_record={"summary": high_entropy_value},
                ),
            )

        registry.validate_output_envelope(
            "gsc-analyst",
            valid_envelope(
                "gsc-analyst",
                "gsc_opportunity_report",
                machine_record={"summary": f"artifact hash {sha256_value}"},
            ),
        )

    def test_content_producer_cannot_write_content_brief(self):
        registry = AgentProfileRegistry.from_path(REGISTRY_PATH)

        with self.assertRaisesRegex(ProfileRegistryError, "not allowed for profile 'content-producer'"):
            registry.validate_output_envelope(
                "content-producer",
                {
                    "task_id": "task_2",
                    "run_id": "run_2",
                    "profile_id": "content-producer",
                    "output_type": "content_brief",
                    "source_refs": ["src_2"],
                    "artifact_refs": ["artifact_2"],
                    "content_hash": "sha256:def",
                    "created_at": "2026-05-23T00:00:00+08:00",
                    "sensitivity": "internal",
                    "retention_policy": "artifact_long_term",
                    "machine_record": {"summary": "should fail writing content brief"},
                },
            )

    def test_seo_content_strategist_can_write_strategy_and_brief(self):
        registry = AgentProfileRegistry.from_path(REGISTRY_PATH)

        for output_type in ["seo_content_strategy", "content_brief"]:
            with self.subTest(output_type=output_type):
                registry.validate_output_envelope(
                    "seo-content-strategist",
                    valid_envelope("seo-content-strategist", output_type),
                )

    def test_content_producer_can_still_write_drafts(self):
        registry = AgentProfileRegistry.from_path(REGISTRY_PATH)

        for output_type in ["content_draft", "social_post_draft"]:
            with self.subTest(output_type=output_type):
                registry.validate_output_envelope(
                    "content-producer",
                    valid_envelope("content-producer", output_type),
                )

    def test_outcome_monitor_can_write_outcome_report(self):
        registry = AgentProfileRegistry.from_path(REGISTRY_PATH)

        registry.validate_output_envelope(
            "outcome-monitor",
            valid_envelope("outcome-monitor", "outcome_report"),
        )


if __name__ == "__main__":
    unittest.main()
