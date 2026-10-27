import os
import sys
import unittest

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.services import extractor
from app.services.errors import ErrorCode


class TestNewErrorCodes(unittest.TestCase):
    def test_expired_links_are_classified(self):
        for message in (
            "ERROR: link has expired",
            "The URL has expired",
            "410 Gone",
        ):
            self.assertEqual(extractor.classify_error(message), "LINK_EXPIRED")

    def test_parser_failures_are_classified_as_platform_changed(self):
        for message in (
            "Failed to parse the player response",
            "Unexpected response from the site",
            "extractor is out of date",
        ):
            self.assertEqual(extractor.classify_error(message), "PLATFORM_CHANGED")

    def test_existing_mappings_are_untouched(self):
        # Phase 1 contract: these must keep their old codes.
        self.assertEqual(
            extractor.classify_error("No video formats found!"), "UNSUPPORTED_URL"
        )
        self.assertEqual(extractor.classify_error("Something odd"), "UNKNOWN")
        self.assertEqual(
            extractor.classify_error("HTTP Error 429: Too Many Requests"), "RATE_LIMIT"
        )

    def test_new_codes_have_messages_and_no_settings_action(self):
        for code in (ErrorCode.LINK_EXPIRED, ErrorCode.PLATFORM_CHANGED):
            message = extractor._ERROR_MESSAGES[code.value]
            self.assertTrue(message)
            self.assertIsNone(extractor.error_action(code.value))

    def test_diagnostic_message_carries_the_code(self):
        code, message = extractor.diagnostic_message("Failed to parse the page")
        self.assertEqual(code, "PLATFORM_CHANGED")
        self.assertIn("update", message.lower())


if __name__ == "__main__":
    unittest.main()
