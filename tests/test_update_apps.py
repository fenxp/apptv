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

    def test_builds_catalog_from_latest_github_release(self):
        self.config["sources"] = [
            {
                "id": "release-demo",
                "type": "github-release",
                "name": "Release Demo",
                "repository": "owner/releases",
                "packages": [
                    {
                        "id": "tv",
                        "label": "电视版",
                        "platform": "tv",
                        "downloads": [
                            {
                                "asset_suffix": "-arm64.apk",
                                "label": "64 位",
                                "architecture": "arm64-v8a",
                                "recommended": True,
                            }
                        ],
                    }
                ],
            }
        ]

        def release_getter(url):
            release = {
                "tag_name": "v20260817-1745",
                "target_commitish": "abc123",
                "published_at": "2026-08-18T01:26:18Z",
                "body": "Credit: Example\nChangelog:\n```\n* First change\n- Second change\n```",
                "assets": [
                    {
                        "name": "release-arm64.apk",
                        "size": 1234,
                        "browser_download_url": "https://github.com/owner/releases/download/v1/release-arm64.apk",
                    }
                ],
            }
            self.assertTrue(url.endswith("/repos/owner/releases/releases?per_page=100&page=1"))
            return [release]

        result = update_apps.build_catalog(self.config, release_getter)
        app = result["apps"][0]
        release = app["releases"][0]
        self.assertEqual(app["source_revision"], "abc123")
        self.assertEqual(release["version"], "20260817-1745")
        self.assertEqual(release["tag_name"], "v20260817-1745")
        self.assertEqual(release["notes"], ["First change", "Second change"])
        self.assertEqual(release["downloads"][0]["filename"], "release-arm64.apk")
        self.assertTrue(release["downloads"][0]["recommended"])

    def test_incremental_release_update_preserves_history(self):
        self.config["sources"] = [
            {
                "id": "release-demo",
                "type": "github-release",
                "name": "Release Demo",
                "repository": "owner/releases",
                "packages": [
                    {
                        "id": "tv",
                        "label": "电视版",
                        "platform": "tv",
                        "downloads": [
                            {
                                "asset_suffix": "-arm64.apk",
                                "label": "64 位",
                                "architecture": "arm64-v8a",
                                "recommended": True,
                            }
                        ],
                    }
                ],
            }
        ]
        existing = {
            "schema_version": 1,
            "apps": [
                {
                    "id": "release-demo",
                    "history_complete": True,
                    "history_signature": update_apps.release_history_signature(self.config["sources"][0]),
                    "releases": [
                        {
                            "id": "tv",
                            "tag_name": "v1.0.0",
                            "version": "1.0.0",
                            "updated_at": "2026-08-01T00:00:00Z",
                            "downloads": [],
                        }
                    ],
                }
            ],
        }
        calls = []

        def latest_getter(url):
            calls.append(url)
            return {
                "tag_name": "v1.1.0",
                "target_commitish": "def456",
                "published_at": "2026-08-20T00:00:00Z",
                "body": "* New release",
                "assets": [
                    {
                        "name": "release-arm64.apk",
                        "size": 4567,
                        "browser_download_url": "https://github.com/owner/releases/download/v1.1.0/release-arm64.apk",
                    }
                ],
            }

        result = update_apps.build_catalog(self.config, latest_getter, existing)
        releases = result["apps"][0]["releases"]
        self.assertEqual(calls, ["https://api.github.com/repos/owner/releases/releases/latest"])
        self.assertEqual([release["version"] for release in releases], ["1.1.0", "1.0.0"])

    def test_known_latest_release_does_not_refetch_assets(self):
        self.config["sources"] = [
            {
                "id": "release-demo",
                "type": "github-release",
                "name": "Release Demo",
                "repository": "owner/releases",
                "packages": [
                    {
                        "id": "tv",
                        "label": "电视版",
                        "platform": "tv",
                        "downloads": [{"asset_suffix": "-arm64.apk", "architecture": "arm64-v8a"}],
                    }
                ],
            }
        ]
        existing_release = {
            "id": "tv",
            "tag_name": "v1.0.0",
            "version": "1.0.0",
            "updated_at": "2026-08-01T00:00:00Z",
            "downloads": [],
        }
        existing = {
            "schema_version": 1,
            "apps": [
                {
                    "id": "release-demo",
                    "history_complete": True,
                    "history_signature": update_apps.release_history_signature(self.config["sources"][0]),
                    "releases": [existing_release],
                }
            ],
        }

        def latest_getter(url):
            self.assertTrue(url.endswith("/repos/owner/releases/releases/latest"))
            return {"tag_name": "v1.0.0", "published_at": "2026-08-02T00:00:00Z"}

        result = update_apps.build_catalog(self.config, latest_getter, existing)
        self.assertEqual(result["apps"][0]["releases"], [existing_release])

    def test_release_tag_patterns_select_matching_package_group(self):
        source = {
            "id": "variants",
            "name": "Variants",
            "repository": "owner/variants",
            "packages": [
                {
                    "id": "standard",
                    "label": "普通版",
                    "platform": "mobile",
                    "exclude_tag_pattern": "-pro$",
                    "downloads": [{"asset_suffix": "-arm64.apk", "architecture": "arm64-v8a"}],
                },
                {
                    "id": "pro",
                    "label": "Pro",
                    "platform": "mobile",
                    "tag_pattern": "-pro$",
                    "downloads": [
                        {"asset_suffix": "-pro.apk", "architecture": "universal"},
                        {"asset_suffix": "-optional.apk", "architecture": "universal", "optional": True},
                    ],
                },
            ],
        }
        release = {
            "tag_name": "2.0.0-pro",
            "published_at": "2026-08-20T00:00:00Z",
            "assets": [
                {
                    "name": "app-pro.apk",
                    "size": 10,
                    "browser_download_url": "https://github.com/owner/variants/releases/download/2.0.0-pro/app-pro.apk",
                }
            ],
        }
        entries = update_apps.build_release_entries(source, release, [])
        self.assertEqual([entry["id"] for entry in entries], ["pro"])
        self.assertEqual(len(entries[0]["downloads"]), 1)

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
