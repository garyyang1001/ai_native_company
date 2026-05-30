import json
import tempfile
import unittest
from pathlib import Path

from closed_loop_kernel.ohya_seo_profile_scaffold import (
    generate_scaffold,
    load_model_baseline,
)


REGISTRY_PATH = Path("data/agent-profile-registry-v0.json")


class OhyaSeoProfileScaffoldTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.root = Path(self.tmpdir.name)
        self.template = self.root / "template-config.yaml"
        self.template.write_text(
            """model:
  default: gpt-5.5
  provider: openai-codex
providers: {}
terminal:
  cwd: /ignored/live/path
""",
            encoding="utf-8",
        )
        self.output_dir = self.root / "scaffold"

    def test_load_model_baseline_reads_only_model_identity(self):
        baseline = load_model_baseline(self.template)

        self.assertEqual(baseline.default, "gpt-5.5")
        self.assertEqual(baseline.provider, "openai-codex")

    def test_generate_scaffold_creates_clean_profiles_and_report(self):
        manifest = generate_scaffold(
            template_config_path=self.template,
            registry_path=REGISTRY_PATH,
            output_dir=self.output_dir,
        )

        self.assertEqual(manifest["model"], {"default": "gpt-5.5", "provider": "openai-codex"})
        self.assertFalse(manifest["writes_live_runtime"])
        self.assertEqual(
            manifest["profiles"],
            ["growth-coordinator", "social-listener", "social-reply-advisor"],
        )

        manifest_path = self.output_dir / "manifest.json"
        self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8")), manifest)

        for profile_id in manifest["profiles"]:
            profile_dir = self.output_dir / "profiles" / profile_id
            self.assertTrue((profile_dir / "SOUL.md").is_file(), profile_id)
            self.assertTrue((profile_dir / "config.yaml").is_file(), profile_id)
            self.assertTrue((profile_dir / "workspace").is_dir(), profile_id)

            config = (profile_dir / "config.yaml").read_text(encoding="utf-8")
            self.assertIn("default: gpt-5.5", config)
            self.assertIn("provider: openai-codex", config)
            self.assertIn(str(profile_dir / "workspace"), config)
            self.assertNotIn("/ignored/live/path", config)

            soul = (profile_dir / "SOUL.md").read_text(encoding="utf-8")
            self.assertIn("Code is Law", soul)
            self.assertIn("Agent Output Envelope", soul)

        report = (self.output_dir / "REPORT.md").read_text(encoding="utf-8")
        self.assertIn("白話說", report)
        self.assertIn("growth-coordinator", report)
        self.assertIn("social-listener", report)
        self.assertIn("social-reply-advisor", report)

    def test_scaffold_does_not_create_legacy_state_directories(self):
        generate_scaffold(
            template_config_path=self.template,
            registry_path=REGISTRY_PATH,
            output_dir=self.output_dir,
        )

        generated_paths = {path.name for path in self.output_dir.rglob("*") if path.is_dir()}
        self.assertFalse({"sessions", "memories", "logs", "cache", "checkpoints"} & generated_paths)
        self.assertFalse(any(path.name == ".env" for path in self.output_dir.rglob("*")))
        self.assertFalse(any(path.name == "kanban.db" for path in self.output_dir.rglob("*")))

    def test_specs_must_match_registry_outputs(self):
        generate_scaffold(
            template_config_path=self.template,
            registry_path=REGISTRY_PATH,
            output_dir=self.output_dir,
        )

        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        outputs_by_profile = {
            profile["profile_id"]: set(profile["data_flow_policy"]["writable_outputs"])
            for profile in registry["profiles"]
        }
        self.assertGreaterEqual(outputs_by_profile["social-listener"], {"social_patrol_report", "brand_presence_signal"})
        self.assertGreaterEqual(outputs_by_profile["social-reply-advisor"], {"social_reply_recommendation"})


if __name__ == "__main__":
    unittest.main()
