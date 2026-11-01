#!/usr/bin/env python3
"""Wersjonuje adresy własnych plików JS/CSS w stronach HTML frontendu.

Każde odwołanie `src="js/x.js"` / `href="css/y.css"` (ścieżka względna,
bez CDN) dostaje sufiks `?v=<10 znaków SHA-256 zawartości pliku>`. Zmiana
pliku zmienia jego adres, więc przeglądarki i cache Cloudflare pobierają
nową wersję od razu, bez czyszczenia cache. Strony HTML nginx wysyła
z `Cache-Control: no-cache`, więc nowe adresy docierają przy pierwszym
przeładowaniu (zob. docs/ARCHITECTURE.md, „Cache zasobów frontendu”).

Użycie (z katalogu głównego repozytorium):
    python3 scripts/bump_asset_versions.py           # przepisz wersje
    python3 scripts/bump_asset_versions.py --check   # kod 1, gdy nieaktualne
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
PAGES = ("index.html", "admin.html", "instrukcja/index.html")

# Względna ścieżka do .js/.css z opcjonalną dotychczasową wersją.
ASSET_REF = re.compile(
    r'(?P<attr>\b(?:src|href)=")'
    r'(?P<path>(?![a-z]+:|/)[^"?#]+\.(?:js|css))'
    r'(?:\?v=[0-9a-f]*)?"'
)


def content_version(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:10]


def versioned(page: Path) -> str:
    def replace(match: re.Match[str]) -> str:
        asset = (page.parent / match["path"]).resolve()
        if not asset.is_file():
            raise SystemExit(f"{page}: brak pliku {match['path']}")
        return f'{match["attr"]}{match["path"]}?v={content_version(asset)}"'

    return ASSET_REF.sub(replace, page.read_text(encoding="utf-8"))


def main() -> int:
    check = "--check" in sys.argv[1:]
    stale = []
    for name in PAGES:
        page = FRONTEND / name
        updated = versioned(page)
        if updated != page.read_text(encoding="utf-8"):
            stale.append(name)
            if not check:
                page.write_text(updated, encoding="utf-8")
    if not stale:
        return 0
    verb = "nieaktualne wersje zasobów" if check else "zaktualizowano"
    print(f"{verb}: {', '.join(stale)}", file=sys.stderr)
    return 1 if check else 0


if __name__ == "__main__":
    sys.exit(main())
