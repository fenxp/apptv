import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_site.py"
SPEC = importlib.util.spec_from_file_location("build_site", SCRIPT)
build_site = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(build_site)


class BuildSiteTests(unittest.TestCase):
    def create_project(self, root):
        (root / "index.html").write_text("<h1>Site</h1>", encoding="utf-8")
        (root / ".nojekyll").write_text("", encoding="utf-8")
        (root / "assets").mkdir()
        (root / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
        (root / "data").mkdir()
        (root / "data" / "apps.json").write_text("{}", encoding="utf-8")
        (root / "scripts").mkdir()
        (root / "scripts" / "private.py").write_text("PRIVATE = True", encoding="utf-8")

    def test_build_contains_only_public_items(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_project(root)
            output = build_site.build_site(root, root / "dist")
            self.assertTrue((output / "index.html").exists())
            self.assertTrue((output / "assets" / "app.js").exists())
            self.assertTrue((output / "data" / "apps.json").exists())
            self.assertFalse((output / "scripts").exists())

    def test_build_removes_stale_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_project(root)
            output = root / "dist"
            output.mkdir()
            (output / "stale.txt").write_text("old", encoding="utf-8")
            build_site.build_site(root, output)
            self.assertFalse((output / "stale.txt").exists())

    def test_refuses_output_outside_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            root.mkdir()
            self.create_project(root)
            with self.assertRaises(ValueError):
                build_site.build_site(root, Path(directory) / "outside")


if __name__ == "__main__":
    unittest.main()
