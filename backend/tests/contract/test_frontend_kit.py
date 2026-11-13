"""
Nogat's GUI kit in the front end (ADR-082) and the view's strip of provider lines.

The kit in `frontend/nogat/` is copied byte for byte from Nogat `design/kit/`
(DEV-15.6): every file has the SHA-256 its manifest `nogat-kit.json` names. The map is
one view, so it has one `<nogat-sources>` (DEV-20.5): the provider lines of all its data
go into that one strip, never into a block of their own beside a chart, card, legend or
drawer.
"""

import hashlib
import json
import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"
KIT = FRONTEND / "nogat"


def test_every_kit_file_is_the_copy_its_manifest_names():
    manifest = json.loads((KIT / "nogat-kit.json").read_text(encoding="utf-8"))

    hashes = {
        name: hashlib.sha256((KIT / name).read_bytes()).hexdigest()
        for name in manifest["files"]
    }

    assert hashes == manifest["files"]


def test_the_map_view_has_one_strip_of_provider_lines():
    page = (FRONTEND / "index.html").read_text(encoding="utf-8")

    assert len(re.findall(r"<nogat-sources[\s>]", page)) == 1
    assert "provider-lines" not in page
