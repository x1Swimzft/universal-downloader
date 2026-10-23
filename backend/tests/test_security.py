import os
import sys
import shutil
import tempfile
import unittest
import unittest.mock
import httpx
import yt_dlp

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.main import app
from app.services.queue_manager import queue_mgr, is_safe_save_dir


class TestBackendSecurity(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.test_token = "secret-session-token-12345"
        self.old_token = os.environ.get("APP_SESSION_TOKEN")
        os.environ["APP_SESSION_TOKEN"] = self.test_token

        self.temp_save_dir = tempfile.mkdtemp(prefix="ud_test_save_")
        self.old_save_dir = queue_mgr.save_dir
        queue_mgr.set_save_dir(self.temp_save_dir)

    def tearDown(self):
        if self.old_token is not None:
            os.environ["APP_SESSION_TOKEN"] = self.old_token
        else:
            os.environ.pop("APP_SESSION_TOKEN", None)
        queue_mgr.set_save_dir(self.old_save_dir)
        shutil.rmtree(self.temp_save_dir, ignore_errors=True)

    # -------------------------------------------------------------
    # 1. Existing baseline security tests
    # -------------------------------------------------------------
    async def test_token_authentication(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
            # 1. Mutating request without token -> 403
            r_no_token = await client.post("/api/settings", json={"max_concurrent": 3})
            self.assertEqual(r_no_token.status_code, 403)
            self.assertIn("Forbidden", r_no_token.json().get("detail", ""))

            # 2. Mutating request with invalid token -> 403
            r_bad_token = await client.post(
                "/api/settings",
                json={"max_concurrent": 3},
                headers={"X-App-Token": "wrong-token"},
            )
            self.assertEqual(r_bad_token.status_code, 403)

            # 3. Mutating request with valid token -> passes (200)
            r_ok_token = await client.post(
                "/api/settings",
                json={"max_concurrent": 3},
                headers={"X-App-Token": self.test_token},
            )
            self.assertEqual(r_ok_token.status_code, 200)

            # 4. Non-mutating public GET request does not require token
            r_get = await client.get("/api/settings")
            self.assertEqual(r_get.status_code, 200)

            # 5. Sensitive GET without token -> 403
            r_stream_no_tok = await client.get("/api/stream", params={"url": "https://example.com/video"})
            self.assertEqual(r_stream_no_tok.status_code, 403)

            r_file_no_tok = await client.get("/api/file/dummy-job-id")
            self.assertEqual(r_file_no_tok.status_code, 403)

            # 6. Sensitive GET with invalid token -> 403
            r_file_bad_tok = await client.get("/api/file/dummy-job-id", params={"token": "invalid"})
            self.assertEqual(r_file_bad_tok.status_code, 403)

            # 7. Sensitive GET with valid token (query param or header) passes token check
            r_file_query_tok = await client.get("/api/file/dummy-job-id", params={"token": self.test_token})
            self.assertEqual(r_file_query_tok.status_code, 404)  # 404 Job not found proves token passed

            r_file_hdr_tok = await client.get("/api/file/dummy-job-id", headers={"X-App-Token": self.test_token})
            self.assertEqual(r_file_hdr_tok.status_code, 404)

    async def test_reject_drive_root_and_system_dirs(self):
        transport = httpx.ASGITransport(app=app)
        headers = {"X-App-Token": self.test_token}
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
            # Drive root C:\
            r_drive_root = await client.post(
                "/api/settings",
                json={"save_folder": "C:\\"},
                headers=headers,
            )
            self.assertEqual(r_drive_root.status_code, 400)
            self.assertIn("drive root", r_drive_root.json().get("detail", "").lower())

            # System directory C:\Windows
            r_sys = await client.post(
                "/api/settings",
                json={"save_folder": r"C:\Windows"},
                headers=headers,
            )
            self.assertEqual(r_sys.status_code, 400)
            self.assertIn("system directory", r_sys.json().get("detail", "").lower())

    async def test_reject_open_file_not_directory(self):
        dummy_exe = os.path.join(self.temp_save_dir, "malicious.exe")
        with open(dummy_exe, "w", encoding="utf-8") as f:
            f.write("dummy executable")

        transport = httpx.ASGITransport(app=app)
        headers = {"X-App-Token": self.test_token}
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
            r = await client.post(
                "/api/open-folder",
                json={"path": dummy_exe},
                headers=headers,
            )
            self.assertEqual(r.status_code, 400)
            self.assertIn("not a directory", r.json().get("detail", "").lower())

    async def test_reject_path_traversal(self):
        transport = httpx.ASGITransport(app=app)
        headers = {"X-App-Token": self.test_token}
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
            traversal_path = os.path.join(self.temp_save_dir, r"..\..\Windows")
            r = await client.post(
                "/api/open-folder",
                json={"path": traversal_path},
                headers=headers,
            )
            self.assertEqual(r.status_code, 403)
            self.assertIn("outside the configured save folder", r.json().get("detail", ""))

    # -------------------------------------------------------------
    # 2. Host Header Validation (Patch A)
    # -------------------------------------------------------------
    async def test_host_header_validation(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
            # Unauthorized Host headers must be rejected (400 or 403)
            unauthorized_hosts = [
                "evil.com",
                "192.168.1.100:8000",
                "attacker.net:8000",
                "internal.corp",
            ]
            for host in unauthorized_hosts:
                with self.subTest(host=host):
                    r = await client.get("/health", headers={"host": host})
                    self.assertIn(
                        r.status_code,
                        (400, 403),
                        f"Host '{host}' should be rejected with 400 or 403, got {r.status_code}",
                    )

            # Authorized Host headers must pass
            for valid_host in ("127.0.0.1:8000", "localhost:8000", "127.0.0.1", "localhost"):
                with self.subTest(valid_host=valid_host):
                    r_ok = await client.get("/health", headers={"host": valid_host})
                    self.assertEqual(r_ok.status_code, 200)

    # -------------------------------------------------------------
    # 3. CORS Restriction (Patch B)
    # -------------------------------------------------------------
    async def test_cors_restriction(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
            unauthorized_origins = [
                "http://evil.com",
                "https://attacker.org",
                "http://localhost:9999",
                "http://127.0.0.1:9999",
            ]
            for origin in unauthorized_origins:
                with self.subTest(origin=origin):
                    # Simple GET
                    r_get = await client.get("/health", headers={"origin": origin})
                    acao = r_get.headers.get("access-control-allow-origin")
                    self.assertNotEqual(
                        acao,
                        origin,
                        f"Origin {origin} must not receive matching Access-Control-Allow-Origin header",
                    )

                    # Preflight OPTIONS
                    r_preflight = await client.options(
                        "/api/settings",
                        headers={
                            "origin": origin,
                            "access-control-request-method": "POST",
                        },
                    )
                    acao_preflight = r_preflight.headers.get("access-control-allow-origin")
                    self.assertNotEqual(
                        acao_preflight,
                        origin,
                        f"Preflight origin {origin} must not receive matching Access-Control-Allow-Origin header",
                    )

    # -------------------------------------------------------------
    # 4. SSRF / Private IP Protection (Patch C)
    # -------------------------------------------------------------
    async def test_ssrf_media_extract_private_ips_rejected(self):
        private_urls = [
            "http://127.0.0.1:8080/test",
            "http://localhost:8080/test",
            "http://169.254.169.254/latest/meta-data",
            "http://192.168.1.1/admin",
            "http://10.0.0.1/admin",
            "http://172.16.0.1/admin",
        ]
        transport = httpx.ASGITransport(app=app)
        headers = {"X-App-Token": self.test_token}

        for url in private_urls:
            with self.subTest(url=url):
                # Ensure extract_info is never reached for private/loopback targets
                with unittest.mock.patch.object(yt_dlp.YoutubeDL, "extract_info") as mock_extract:
                    mock_extract.return_value = {"title": "mock"}
                    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
                        r = await client.post("/api/info", json={"url": url}, headers=headers)
                        self.assertIn(
                            r.status_code,
                            (400, 403),
                            f"SSRF URL '{url}' in /api/info should return 400 or 403, got {r.status_code}",
                        )
                        self.assertFalse(
                            mock_extract.called,
                            f"SSRF URL '{url}' should be blocked BEFORE calling yt-dlp extract_info",
                        )

    async def test_ssrf_media_stream_private_ips_rejected(self):
        private_urls = [
            "http://127.0.0.1:8080/test",
            "http://169.254.169.254/latest/meta-data",
            "http://192.168.1.1/stream",
            "http://10.0.0.1/stream",
        ]
        transport = httpx.ASGITransport(app=app)
        for url in private_urls:
            with self.subTest(url=url):
                with unittest.mock.patch.object(yt_dlp.YoutubeDL, "extract_info") as mock_extract:
                    mock_extract.return_value = {"title": "mock"}
                    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
                        r = await client.get("/api/stream", params={"url": url})
                        self.assertIn(
                            r.status_code,
                            (400, 403),
                            f"SSRF URL '{url}' in /api/stream should return 400 or 403, got {r.status_code}",
                        )
                        self.assertFalse(
                            mock_extract.called,
                            f"SSRF URL '{url}' should be blocked BEFORE calling yt-dlp in stream",
                        )

    async def test_ssrf_quick_fetch_private_ips_rejected(self):
        transport = httpx.ASGITransport(app=app)
        headers = {"X-App-Token": self.test_token}
        url = "http://127.0.0.1:8080/test"

        with unittest.mock.patch.object(yt_dlp.YoutubeDL, "extract_info") as mock_extract:
            mock_extract.return_value = {"title": "mock"}
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
                r = await client.post(
                    "/api/rio/quick-fetch",
                    json={"url": url, "save_to_dir": self.temp_save_dir},
                    headers=headers,
                )
                self.assertIn(
                    r.status_code,
                    (400, 403),
                    f"SSRF URL '{url}' in /api/rio/quick-fetch should return 400 or 403, got {r.status_code}",
                )
                self.assertFalse(
                    mock_extract.called,
                    f"SSRF URL '{url}' should be blocked BEFORE calling yt-dlp in quick-fetch",
                )

    async def test_ssrf_stream_redirect_to_private_ip_rejected(self):
        # Media stream redirecting to private/loopback IP must be rejected
        urls_requested = []

        class RedirectTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                urls_requested.append(str(request.url))
                if str(request.url) == "http://public-cdn.com/video.mp4":
                    return httpx.Response(302, headers={"Location": "http://127.0.0.1:8080/secret"})
                return httpx.Response(200, content=b"forbidden internal data")

        async def mock_direct_url(url, quality):
            return {
                "url": "http://public-cdn.com/video.mp4",
                "title": "sample",
                "filesize": 100,
                "http_headers": {},
            }

        transport = httpx.ASGITransport(app=app)
        with unittest.mock.patch("app.api.routes.get_direct_stream_url", side_effect=mock_direct_url):
            orig_init = httpx.AsyncClient.__init__

            def patched_init(client_self, *args, **kwargs):
                if "base_url" not in kwargs and "transport" not in kwargs:
                    kwargs["transport"] = RedirectTransport()
                orig_init(client_self, *args, **kwargs)

            with unittest.mock.patch.object(httpx.AsyncClient, "__init__", patched_init):
                async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
                    r = await client.get(
                        "/api/stream",
                        params={"url": "http://public-cdn.com/video.mp4", "token": self.test_token},
                    )
                    self.assertNotIn(
                        "http://127.0.0.1:8080/secret",
                        urls_requested,
                        "Stream client must NOT follow redirect to private/loopback IP",
                    )
                    self.assertIn(
                        r.status_code,
                        (400, 403),
                        f"Stream redirect to private IP must be rejected with 400 or 403, got {r.status_code}",
                    )

    # -------------------------------------------------------------
    # 5. Windows Path Edge Cases in is_safe_save_dir (Patch D)
    # -------------------------------------------------------------
    def test_is_safe_save_dir_windows_edge_cases(self):
        edge_cases = [
            (r"c:\windows", "system directory"),
            (r"C:\Windows\System32", "system directory"),
            ("C:\\", "drive root"),
            ("C:foo", None),  # drive-relative without slash
            ("PROGRA~1", None),  # relative 8.3 short filename
            (r"C:\PROGRA~1", None),  # 8.3 short filename to Program Files
            (r"\\server\share", ("unc", "network")),  # UNC path
        ]
        for path, expected_keyword in edge_cases:
            with self.subTest(path=path):
                ok, err = is_safe_save_dir(path)
                self.assertFalse(ok, f"Path '{path}' must be rejected by is_safe_save_dir, but got ok=True")
                if expected_keyword:
                    if isinstance(expected_keyword, tuple):
                        self.assertTrue(
                            any(k in err.lower() for k in expected_keyword),
                            f"Path '{path}' rejection reason must mention one of {expected_keyword}, got: '{err}'",
                        )
                    else:
                        self.assertIn(
                            expected_keyword,
                            err.lower(),
                            f"Path '{path}' rejection reason must mention '{expected_keyword}', got: '{err}'",
                        )

    async def test_settings_api_rejects_windows_path_edge_cases(self):
        transport = httpx.ASGITransport(app=app)
        headers = {"X-App-Token": self.test_token}
        edge_cases = [
            r"c:\windows",
            "PROGRA~1",
            r"C:\PROGRA~1",
            r"\\server\share",
            "C:foo",
            "C:\\",
            r"C:\Windows\System32",
        ]
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
            for path in edge_cases:
                with self.subTest(path=path):
                    r = await client.post(
                        "/api/settings",
                        json={"save_folder": path},
                        headers=headers,
                    )
                    self.assertEqual(
                        r.status_code,
                        400,
                        f"POST /api/settings with save_folder='{path}' must return 400 Bad Request, got {r.status_code}",
                    )


if __name__ == "__main__":
    unittest.main()
