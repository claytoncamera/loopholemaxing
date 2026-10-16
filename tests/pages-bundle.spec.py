#!/usr/bin/env python3
"""Release boundary tests: retain public evidence, omit operator/source files."""
from html.parser import HTMLParser
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from urllib.parse import unquote, urljoin, urlparse

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("stage_pages", ROOT / "scripts/stage-pages.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attributes):
        for key, value in attributes:
            if key in {"href", "src"} and value:
                self.urls.append(value)


class PagesBundleTests(unittest.TestCase):
    def fixture(self, root, name, content="fixture"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def test_allowlist_excludes_operator_data_and_unknown_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            allowed = ["index.html", "CNAME", ".nojekyll", "googleabc123.html",
                       "studio/index.html", "studio/vendor/ffmpeg-core.js",
                       "window/pnp-tracker/data.js", "agora/excerpts/example.txt",
                       "btc-brain/research/topic.md", "btc-brain/BTC-INTELLIGENCE-BRAIN.pplx.md",
                       "btc-brain/data/public/briefings/day.json",
                       "btc-brain/models/public/registry.json",
                       "btc-brain/ledger/data/forecasts.jsonl",
                       "btc-brain/ledger/data/resolutions.jsonl"]
            excluded = [".claude/launch.json", ".env", "README.md", "SECURITY.md",
                        "btc-brain-engine/engine.py", "btc-brain-engine/config.json",
                        "btc-brain-printer/README_SETUP.md", "logs/history.json",
                        "tests/example.html", "new-unreviewed-app/index.html",
                        "btc-brain/ledger/snapshots/private.json",
                        "btc-brain/data/history/candles.jsonl",
                        "btc-brain/data/public/tests/test.json",
                        "studio/node_modules/package/file.js", "studio/server.py",
                        "studio/__pycache__/source.pyc", "studio/.cache/data.json",
                        "studio/README.md", "studio/setup.test.js", "studio/lock.spec.js"]
            for name in allowed + excluded:
                self.fixture(root, name)
            selected = {p.as_posix() for p in module.stage(root)}
            self.assertEqual(selected, set(allowed))
            for name in excluded:
                self.assertFalse((root / "_site" / name).exists(), name)

    def test_rerun_is_deterministic_and_removes_stale_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["index.html", "CNAME", "studio/index.html"]:
                self.fixture(root, name)
            module.stage(root)
            def snapshot():
                return {str(p.relative_to(root / "_site")): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in (root / "_site").rglob("*") if p.is_file()}
            first = snapshot()
            self.fixture(root, "_site/stale.html")
            module.stage(root)
            self.assertEqual(first, snapshot())
            self.assertEqual((root / "_site/index.html").stat().st_mtime, 0)

    def test_symlink_cannot_publish_outside_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["index.html", "CNAME", "outside.json"]:
                self.fixture(root, name)
            (root / "studio").mkdir()
            (root / "studio/data.json").symlink_to(root / "outside.json")
            with self.assertRaisesRegex(ValueError, "Symlink"):
                module.stage(root)

    def test_real_site_preserves_existing_browser_links_and_evidence(self):
        selected = {p.as_posix() for p in module.stage(ROOT)}
        for name in selected:
            if not name.endswith(".html"):
                continue
            parser = References()
            parser.feed((ROOT / name).read_text())
            base = "https://loopholemaxing.com/" + name
            for raw in parser.urls:
                resolved = urlparse(urljoin(base, raw))
                if resolved.scheme not in {"http", "https"} or resolved.netloc != "loopholemaxing.com":
                    continue
                target = Path(unquote(resolved.path).lstrip("/"))
                source = ROOT / target
                if source.is_dir():
                    target /= "index.html"
                    source = ROOT / target
                # Existing broken source links are not caused by packaging.
                if source.is_file():
                    self.assertIn(target.as_posix(), selected, name + " -> " + str(target))
        for scope in ["btc-brain/data/public", "btc-brain/models/public", "btc-brain/ledger/public",
                      "btc-brain/research", "agora/data", "agora/excerpts", "agora/ledger"]:
            for path in (ROOT / scope).rglob("*"):
                relative = path.relative_to(ROOT)
                if path.is_file() and path.suffix in {".md", ".json", ".jsonl", ".txt", ".html"}:
                    self.assertIn(relative.as_posix(), selected, str(relative))
        self.assertIn("btc-brain/ledger/data/forecasts.jsonl", selected)
        self.assertIn("btc-brain/ledger/data/resolutions.jsonl", selected)
        self.assertFalse(any(p.startswith((".claude/", "logs/", "btc-brain-engine/", "btc-brain-printer/"))
                             for p in selected))
        self.assertFalse(any(Path(p).suffix in {".py", ".pyc", ".sh", ".plist"} for p in selected))

    def test_workflow_uploads_only_staged_bundle(self):
        workflow = (ROOT / ".github/workflows/pages.yml").read_text()
        self.assertIn("run: python3 scripts/stage-pages.py", workflow)
        self.assertIn("path: '_site'", workflow)
        self.assertNotIn("path: '.'", workflow)

    def test_formix_is_a_concept_not_a_pretend_store(self):
        html = (ROOT / "formix/index.html").read_text()
        self.assertIn("Concept study · Not for sale", html)
        self.assertIn('href="https://loopholemaxing.com/formix/"', html)
        self.assertIn("https://claytoncamera.com/#person", html)
        for retired in ["<form", "Add to Cart", "Pre-Order", "testimonials", "Verified Reviews",
                        "8,400+", "1,240+", "cGMP Certified", "Science-Backed"]:
            self.assertNotIn(retired, html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
