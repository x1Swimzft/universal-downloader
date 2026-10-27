import os
import sys
import unittest

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.services import extractor
from app.services.adapters.registry import AdapterRegistry
from app.services.errors import ErrorCode


class _FakeAdapter:
    """Minimal adapter: only matches() matters for dispatch."""

    def __init__(self, name, host):
        self.name = name
        self.host = host

    def matches(self, url):
        return self.host in url

    async def probe(self, url):
        return None

    async def entries(self, url):
        return None

    async def download(self, ctx):
        return None


class TestAdapterRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = AdapterRegistry()
        self.tiktok = _FakeAdapter("tiktok", "tiktok.com")
        self.instagram = _FakeAdapter("instagram", "instagram.com")

    def test_first_registered_match_wins(self):
        self.registry.register(self.tiktok)
        self.registry.register(self.instagram)

        self.assertIs(
            self.registry.resolve("https://www.tiktok.com/@a/photo/1"), self.tiktok
        )
        self.assertIs(self.registry.resolve("https://instagram.com/p/x"), self.instagram)

    def test_no_match_returns_none_so_callers_can_fall_back(self):
        self.registry.register(self.tiktok)

        self.assertIsNone(self.registry.resolve("https://youtube.com/watch?v=1"))

    def test_registering_the_same_name_replaces_it(self):
        self.registry.register(self.tiktok)
        replacement = _FakeAdapter("tiktok", "vm.tiktok.com")
        self.registry.register(replacement)

        self.assertEqual(self.registry.adapters, (replacement,))
        self.assertIs(self.registry.resolve("https://vm.tiktok.com/x"), replacement)

    def test_clear_removes_everything(self):
        self.registry.register(self.tiktok)
        self.registry.clear()

        self.assertEqual(self.registry.adapters, ())
        self.assertIsNone(self.registry.resolve("https://www.tiktok.com/@a/photo/1"))


class TestErrorCodes(unittest.TestCase):
    def test_existing_classifier_output_is_a_declared_code(self):
        samples = [
            "ERROR: 403 Forbidden",
            "Sign in to confirm your age",
            "HTTP Error 429: Too Many Requests",
            "Connection timed out",
            "Unsupported URL: https://example.invalid/x",
            "something nobody has seen before",
        ]
        codes = {extractor.classify_error(message) for message in samples}

        self.assertTrue(codes)
        for code in codes:
            self.assertIn(code, {member.value for member in ErrorCode})

    def test_every_user_facing_message_has_a_code(self):
        declared = {member.value for member in ErrorCode}
        for code in extractor._ERROR_MESSAGES:
            self.assertIn(code, declared)

    def test_codes_are_plain_strings_on_the_wire(self):
        self.assertEqual(ErrorCode.COOKIE_REQUIRED, "COOKIE_REQUIRED")
        self.assertEqual(ErrorCode("NETWORK_TRANSIENT"), ErrorCode.NETWORK_TRANSIENT)


if __name__ == "__main__":
    unittest.main()
