"""Copy web/ to a staging dir with cache-busted asset URLs.

GitHub Pages serves everything with `Cache-Control: max-age=600` and offers no
way to change that. A visitor who loaded the page shortly before a deploy can
therefore revalidate the HTML while still holding the previous JS, which renders
a table whose rows no longer match its headers.

Appending a build version to every local asset URL makes each deploy's assets
distinct, so fresh HTML can never pair with stale JS. Run this instead of
uploading web/ directly:

    python -m pipeline.stage_site _site
"""
from __future__ import annotations

import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import config

# src="js/main.js" / href="css/app.css" in HTML
HTML_ASSET = re.compile(r'((?:src|href)=")((?:js|css)/[^"?]+)(\?v=[^"]*)?"')
# import ... from './common.js' or './js/common.js' inside modules and inline
# scripts -- module imports bypass the HTML tag, so they need stamping too.
JS_IMPORT = re.compile(r"(from\s+['\"])(\.{1,2}/[A-Za-z0-9_./-]+?\.js)(\?v=[^'\"]*)?(['\"])")


def stage(dest: Path, version: str | None = None) -> str:
    version = version or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(config.WEB_DIR, dest)

    patched = 0
    for path in list(dest.rglob("*.html")) + list(dest.rglob("*.js")):
        text = path.read_text(encoding="utf-8")
        original = text
        if path.suffix == ".html":
            text = HTML_ASSET.sub(rf'\1\2?v={version}"', text)
        text = JS_IMPORT.sub(rf"\1\2?v={version}\4", text)
        if text != original:
            path.write_text(text, encoding="utf-8")
            patched += 1

    print(f"staged {dest} at version {version} ({patched} files stamped)", flush=True)
    return version


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "_site")
    stage(target.resolve())
