import unittest

from wannavegtour.redact import hash_message, hash_user_id, redact_text


class RedactTests(unittest.TestCase):
    def test_redacts_phone_and_returns_full_message_hash(self):
        text = "明天 18:00 美鳳訂位 0912345678"
        preview, message_hash = redact_text(text)

        self.assertNotIn("0912345678", preview)
        self.assertIn("[phone:", preview)
        self.assertEqual(message_hash, hash_message(text))

    def test_redacts_email_and_line_user_id(self):
        text = "email test@example.com line U0123456789abcdef0123456789abcdef"
        preview, _ = redact_text(text)

        self.assertNotIn("test@example.com", preview)
        self.assertNotIn("U0123456789abcdef0123456789abcdef", preview)
        self.assertIn("[email:", preview)
        self.assertIn("[line_user:", preview)

    def test_hash_user_id_is_stable_and_non_raw(self):
        uid = "U0123456789abcdef0123456789abcdef"

        self.assertEqual(hash_user_id(uid), hash_user_id(uid))
        self.assertNotIn(uid, hash_user_id(uid))


if __name__ == "__main__":
    unittest.main()
