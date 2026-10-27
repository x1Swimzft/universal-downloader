"""Stable, machine-readable error codes shared by the API, adapters and the UI.

The wire values already shipped in 0.7.1 are kept: the frontend maps them in
DownloadCard.tsx and page.tsx, and the Phase 1 tests assert them. The names in
the Phase 2 work order map onto them rather than replacing them:

    NETWORK      -> NETWORK_TRANSIENT
    UNSUPPORTED  -> UNSUPPORTED_URL
"""

from enum import Enum


class ErrorCode(str, Enum):
    AUTH_403 = "AUTH_403"
    COOKIE_REQUIRED = "COOKIE_REQUIRED"
    COOKIE_LOCKED = "COOKIE_LOCKED"
    RATE_LIMIT = "RATE_LIMIT"
    NETWORK_TRANSIENT = "NETWORK_TRANSIENT"
    UNSUPPORTED_URL = "UNSUPPORTED_URL"
    LINK_EXPIRED = "LINK_EXPIRED"
    PLATFORM_CHANGED = "PLATFORM_CHANGED"
    UNKNOWN = "UNKNOWN"
