#!/usr/bin/env python3
"""Build the reviewed browser bundle; repository contents are not a web root.

Run from any directory: python3 scripts/stage-pages.py
Only _site/ is replaced. Existing operational browser pages stay available;
their device locks are convenience features, not server authentication.
"""
from pathlib import Path
import os
import shutil
import tempfile


ROOT_FILES = {
    "index.html", "404.html", "CNAME", ".nojekyll", "robots.txt", "sitemap.xml",
    "styles.css", "capture.js", "portfolio-ledger.js", "favicon.ico", "favicon.svg",
}
BROWSER_DIRS = {
    "agora", "analytics-hub", "army-link", "clayton-camera", "formix", "mms-hub",
    "nba-brain", "studio", "uae", "ultron", "vault", "window", "work-with-clayton",
}
BTC_DIRS = {
    "btc-brain/charts", "btc-brain/research", "btc-brain/data/public",
    "btc-brain/ledger/public", "btc-brain/models/public",
}
BTC_FILES = {
    "btc-brain/index.html", "btc-brain/BTC-INTELLIGENCE-BRAIN.pplx.md",
    "btc-brain/ledger/data/forecasts.jsonl",
    "btc-brain/ledger/data/resolutions.jsonl",
}
ASSET_SUFFIXES = {
    ".html", ".css", ".js", ".json", ".jsonl", ".svg", ".png", ".jpg",
    ".jpeg", ".webp", ".gif", ".ico", ".webmanifest", ".wasm", ".txt",
    ".woff", ".woff2", ".ttf", ".otf", ".mp4", ".webm", ".mp3", ".ogg", ".md",
}
EXCLUDED_PARTS = {"tests", "test", "logs", "__pycache__", "node_modules", "scripts"}


def publishable(relative):
    """An allowlisted location AND a browser asset are both required."""
    name = relative.as_posix()
    if name in ROOT_FILES or name in BTC_FILES:
        return True
    if len(relative.parts) == 1:
        # Search-console verification files: Google's googleXXXX.html, and an IndexNow key
        # (32 lowercase hex chars + .txt, whose content is the key) so Bing accepts URL pings.
        return ((relative.name.startswith("google") and relative.suffix == ".html"
                 and relative.stem[6:].isalnum())
                or (relative.suffix == ".txt" and len(relative.stem) == 32
                    and all(c in "0123456789abcdef" for c in relative.stem)))
    if any(part.startswith(".") or part in EXCLUDED_PARTS for part in relative.parts):
        return False
    if (relative.name.lower().startswith(("readme", "test_", "test-"))
            or ".test." in relative.name or ".spec." in relative.name):
        return False
    if relative.suffix.lower() not in ASSET_SUFFIXES:
        return False
    return (relative.parts[0] in BROWSER_DIRS
            or any(name.startswith(scope + "/") for scope in BTC_DIRS))


def stage(root):
    root = Path(root).resolve()
    destination = root / "_site"
    if destination.is_symlink():
        raise ValueError("Refusing a symlinked _site output")
    # Never traverse symlinks: upload-pages-artifact dereferences them.
    selected = []
    for folder, directories, filenames in os.walk(root, followlinks=False):
        directories[:] = sorted(d for d in directories if d != "_site"
                                and not d.startswith((".git", ".pages-stage-")))
        for name in sorted(filenames):
            source = Path(folder) / name
            relative = source.relative_to(root)
            if publishable(relative):
                if source.is_symlink() or any(parent.is_symlink() for parent in source.parents):
                    raise ValueError("Symlink in a publishable path: " + relative.as_posix())
                selected.append(relative)
        for name in directories:
            source = Path(folder) / name
            if source.is_symlink() and publishable(source.relative_to(root) / "index.html"):
                raise ValueError("Symlinked public directory: " + source.relative_to(root).as_posix())
    if Path("index.html") not in selected or Path("CNAME") not in selected:
        raise ValueError("Required homepage or CNAME is missing")
    temporary = Path(tempfile.mkdtemp(prefix=".pages-stage-", dir=root))
    try:
        for relative in sorted(selected):
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((root / relative).read_bytes())
            target.chmod(0o644)
            os.utime(target, (0, 0))
        for folder, _, _ in os.walk(temporary, topdown=False):
            os.chmod(folder, 0o755)
            os.utime(folder, (0, 0))
        if destination.exists():
            shutil.rmtree(destination)
        temporary.rename(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return selected


if __name__ == "__main__":
    files = stage(Path(__file__).resolve().parents[1])
    print(f"Pages bundle: {len(files)} browser files staged in _site/")
