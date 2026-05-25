"""Tests for the credential file permission fail-closed check
(codex review 2026-05-25 P2)."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from wannavegtour.config import CredentialError, load_config


VALID_CONTENT = {
    "site": "wannavegtour",
    "base_url": "https://example.com",
    "api_namespace": "wc/v3",
    "consumer_key": "ck_test",
    "consumer_secret": "cs_test",
    "permissions": "read",
}


def _write_temp_cred(content: dict, mode: int) -> Path:
    fd, name = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    p = Path(name)
    p.write_text(json.dumps(content), encoding="utf-8")
    os.chmod(p, mode)
    return p


class TestCredentialPermissions(unittest.TestCase):

    def setUp(self):
        self._created: list[Path] = []

    def tearDown(self):
        for p in self._created:
            try:
                p.unlink()
            except OSError:
                pass

    @unittest.skipUnless(os.name == "posix", "POSIX-only permission semantics")
    def test_strict_600_passes(self):
        p = _write_temp_cred(VALID_CONTENT, 0o600)
        self._created.append(p)
        cfg = load_config(p)
        self.assertEqual(cfg.consumer_key, "ck_test")

    @unittest.skipUnless(os.name == "posix", "POSIX-only permission semantics")
    def test_group_readable_644_rejected(self):
        p = _write_temp_cred(VALID_CONTENT, 0o644)
        self._created.append(p)
        with self.assertRaises(CredentialError) as ctx:
            load_config(p)
        self.assertIn("0o644", str(ctx.exception))
        self.assertIn("chmod 600", str(ctx.exception))

    @unittest.skipUnless(os.name == "posix", "POSIX-only permission semantics")
    def test_world_writable_666_rejected(self):
        p = _write_temp_cred(VALID_CONTENT, 0o666)
        self._created.append(p)
        with self.assertRaises(CredentialError):
            load_config(p)

    @unittest.skipUnless(os.name == "posix", "POSIX-only permission semantics")
    def test_allow_loose_perms_bypass(self):
        # Test escape hatch — explicit opt-in for known-loose temp files.
        p = _write_temp_cred(VALID_CONTENT, 0o644)
        self._created.append(p)
        cfg = load_config(p, allow_loose_perms=True)
        self.assertEqual(cfg.consumer_key, "ck_test")

    @unittest.skipUnless(os.name == "posix", "POSIX-only permission semantics")
    def test_owner_only_400_also_passes(self):
        # 400 (read-only owner) is stricter than 600 — should also pass.
        p = _write_temp_cred(VALID_CONTENT, 0o400)
        self._created.append(p)
        cfg = load_config(p)
        self.assertEqual(cfg.consumer_key, "ck_test")


if __name__ == "__main__":
    unittest.main()
