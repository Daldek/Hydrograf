#!/usr/bin/env python3
"""Version the addresses of the front end's own JS and CSS files.

Every relative reference `src="js/x.js"` / `href="css/y.css"` of a page (no CDN) gets
`?v=<the first 10 characters of the SHA-256 of the file>`, and so does every relative
import of an own ES module in `js/` (`from '../nogat/nogat-handoff.js'` of `js/nogat.js`,
which imports Nogat's kit: ADR-082). A module is versioned before the pages, so its
version covers those of the modules it imports. A changed file changes its address, so
the browsers and the Cloudflare cache fetch the new version at once, without clearing a
cache. nginx sends the HTML pages with `Cache-Control: no-cache`, so the new addresses
arrive with the first reload (docs/ARCHITECTURE.md §5.2, "Front-end asset cache"). The
copies of the kit in `nogat/` import nothing and are never rewritten.

Usage (from the root of the repository):
    python3 scripts/bump_asset_versions.py           # rewrite the versions
    python3 scripts/bump_asset_versions.py --check   # exit 1 when they are stale
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
PAGES = ("index.html", "admin/index.html", "instrukcja/index.html")
SCRIPTS = FRONTEND / "js"

# A relative path to a .js/.css file with an optional earlier version.
ASSET_REF = re.compile(
    r'(?P<attr>\b(?:src|href)=")'
    r'(?P<path>(?![a-z]+:|/)[^"?#]+\.(?:js|css))'
    r'(?:\?v=[0-9a-f]*)?"'
)

# The relative specifier of a static or dynamic import, with an optional earlier version.
IMPORT_REF = re.compile(
    r"""(?P<head>\b(?:from|import)\s*\(?\s*)(?P<quote>['"])"""
    r"""(?P<path>\.\.?/[^'"?#]+\.js)(?:\?v=[0-9a-f]*)?(?P=quote)"""
)


def content_version(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:10]


def script_text(path: Path, texts: dict[Path, str | None]) -> str:
    """The text of an own script with its imports versioned, each import before it."""
    if path in texts:
        text = texts[path]
        if text is None:
            raise SystemExit(f"{path}: the imports form a cycle")
        return text
    texts[path] = None

    def replace(match: re.Match[str]) -> str:
        target = (path.parent / match["path"]).resolve()
        if not target.is_file():
            raise SystemExit(f"{path}: no file {match['path']}")
        version = content_version(served(target, texts))
        quote = match["quote"]
        return f"{match['head']}{quote}{match['path']}?v={version}{quote}"

    text = IMPORT_REF.sub(replace, path.read_bytes().decode("utf-8"))
    texts[path] = text
    return text


def served(path: Path, texts: dict[Path, str | None]) -> bytes:
    """The content of a file as the pages get it: an own script with its imports versioned."""
    if path.suffix == ".js" and path.is_relative_to(SCRIPTS):
        return script_text(path, texts).encode("utf-8")
    return path.read_bytes()


def versioned(page: Path, texts: dict[Path, str | None]) -> str:
    def replace(match: re.Match[str]) -> str:
        asset = (page.parent / match["path"]).resolve()
        if not asset.is_file():
            raise SystemExit(f"{page}: no file {match['path']}")
        version = content_version(served(asset, texts))
        return f'{match["attr"]}{match["path"]}?v={version}"'

    return ASSET_REF.sub(replace, page.read_text(encoding="utf-8"))


def main() -> int:
    check = "--check" in sys.argv[1:]
    texts: dict[Path, str | None] = {}
    stale = []
    for script in sorted(SCRIPTS.rglob("*.js")):
        text = script_text(script, texts).encode("utf-8")
        if text != script.read_bytes():
            stale.append(script.relative_to(FRONTEND).as_posix())
            if not check:
                script.write_bytes(text)
    for name in PAGES:
        page = FRONTEND / name
        updated = versioned(page, texts)
        if updated != page.read_text(encoding="utf-8"):
            stale.append(name)
            if not check:
                page.write_text(updated, encoding="utf-8")
    if not stale:
        return 0
    verb = "stale asset versions" if check else "updated"
    print(f"{verb}: {', '.join(stale)}", file=sys.stderr)
    return 1 if check else 0


if __name__ == "__main__":
    sys.exit(main())
