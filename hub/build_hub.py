#!/usr/bin/env python3
"""Generate the Get a Job hub (index.html) from hub/shell.html + hub/tiles/*.html.

Why this exists
---------------
The hub is a portal whose tiles each belong to a different tool lane (the TBC
guide, the guild-name vote, "more soon"). When more than one lane hand-edits a
single index.html, their changes collide. So the hub is split:

  hub/shell.html        the page chrome — head, branding copy, footer.
                        Owned by the PRESENTATION lane.
  hub/tiles/NN-name.html one card per tool, rendered in filename sort order
                        (the NN prefix controls position). Each fragment is
                        owned by THAT tool's lane.
  index.html            the build artifact, assembled by this script and served
                        as-is by Caddy. Nobody hand-edits it.

A tool lane flips its own tile (Soon -> Live, copy tweaks) by editing ONLY its
fragment file — never index.html, never another lane's tile.

Usage
-----
  python3 hub/build_hub.py          regenerate index.html
  python3 hub/build_hub.py --check  verify index.html is in sync (exit 1 if not)
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../hub
ROOT = HERE.parent                               # repo root
SHELL = HERE / "shell.html"
TILES_DIR = HERE / "tiles"
OUT = ROOT / "index.html"
MARKER = "  <!-- @@TILES@@ -->"


def render() -> str:
    shell = SHELL.read_text(encoding="utf-8")
    if MARKER not in shell:
        sys.exit(f"error: marker {MARKER!r} not found in {SHELL}")
    frags = sorted(TILES_DIR.glob("*.html"))
    if not frags:
        sys.exit(f"error: no tile fragments in {TILES_DIR}")
    block = "\n\n".join(f.read_text(encoding="utf-8").strip("\n") for f in frags)
    return shell.replace(MARKER, block)


def main() -> None:
    html = render()
    if "--check" in sys.argv[1:]:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != html:
            sys.exit(
                f"error: {OUT.name} is out of sync with hub/ sources.\n"
                f"       run: python3 hub/build_hub.py"
            )
        print(f"{OUT.name} is in sync with hub/ sources")
        return
    OUT.write_text(html, encoding="utf-8")
    n = len(sorted(TILES_DIR.glob("*.html")))
    print(f"wrote {OUT.relative_to(ROOT)} ({len(html)} bytes, {n} tiles)")


if __name__ == "__main__":
    main()
