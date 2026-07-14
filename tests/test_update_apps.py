import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "update_apps.py"
SPEC = importlib.util.spec_from_file_location("update_apps", SCRIPT)
update_apps = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(update_apps)


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "interfaces": [
                {
                    "id": "tv-config",
                    "name": "影视配置接口",
                    "url": "https://example.org/config.json",
                }
            ],
            "download_mirrors": [
                {
                    "id": "mirror-one",
                    "label": "CDN 1",
                    "provider": "Mirror One",
                    "url_template": "https://mirror.example/{url}",
                }
            ],
            "sources": [
                {
                    "id": "demo",
                    "name": "Demo",
                    "repository": "owner/repo",
                    "branch": "stable",
                    "directory": "apk",
                    "packages": [
                        {
                            "id": "mobile",
                            "label": "手机版",
                            "platform": "mobile",
                            "metadata": "mobile.json",
                            "downloads": [
                                {
                                    "filename": "mobile.apk",
                                    "label": "64 位",
                                    "architecture": "arm64-v8a",
                                    "recommended": True,
                                }
                            ],
                        }
                    ],
                }
            ]
        }

    def getter(self, url):
        if "/contents/" in url:
            return [
                {
                    "name": "mobile.json",
                    "type": "file",
                    "download_url": "https://raw.githubusercontent.com/owner/repo/stable/apk/mobile.json",
                },
                {
                    "name": "mobile.apk",
                    "type": "file",
                    "size": 10485760,
                    "download_url": "https://raw.githubusercontent.com/owner/repo/stable/apk/mobile.apk",
                },
            ]
        if "/commits?" in url:
            return [
                {
                    "sha": "abc123",
                    "commit": {"committer": {"date": "2026-07-14T00:00:00Z"}},
                }
            ]
        return {"code": 123, "name": "1.2.3", "desc": "* First\n- Second"}

    def test_builds_catalog(self):
        result = update_apps.build_catalog(self.config, self.getter)
        release = result["apps"][0]["releases"][0]
        self.assertEqual(release["version"], "1.2.3")
        self.assertEqual(release["notes"], ["First", "Second"])
        self.assertTrue(release["downloads"][0]["recommended"])
        self.assertEqual(
            release["downloads"][0]["mirrors"][0]["url"],
            "https://mirror.example/https://raw.githubusercontent.com/owner/repo/stable/apk/mobile.apk",
        )
        self.assertEqual(result["generated_at"], "2026-07-14T00:00:00Z")
        self.assertEqual(result["interfaces"][0]["url"], "https://example.org/config.json")

    def test_rejects_untrusted_download_host(self):
        with self.assertRaises(update_apps.CatalogError):
            update_apps.validate_download_url("https://example.com/app.apk")

    def test_rejects_insecure_interface_url(self):
        self.config["interfaces"][0]["url"] = "http://example.org/config.json"
        with self.assertRaises(update_apps.CatalogError):
            update_apps.build_catalog(self.config, self.getter)

    def test_rejects_insecure_mirror_url(self):
        self.config["download_mirrors"][0]["url_template"] = "http://mirror.example/{url}"
        with self.assertRaises(update_apps.CatalogError):
            update_apps.build_catalog(self.config, self.getter)

    def test_write_if_changed_is_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "apps.json"
            payload = {"schema_version": 1, "apps": []}
            self.assertTrue(update_apps.write_if_changed(path, payload))
            self.assertFalse(update_apps.write_if_changed(path, payload))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), payload)


if __name__ == "__main__":
    unittest.main()
