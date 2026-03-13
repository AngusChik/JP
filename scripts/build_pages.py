#!/usr/bin/env python3
"""Build a static site bundle for GitHub Pages from the Django homepage."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DJANGO_PROJECT_DIR = ROOT_DIR / "jp"
SITE_DIR = ROOT_DIR / "site"
APP_STATIC_DIR = DJANGO_PROJECT_DIR / "barber" / "static"


def clean_site_dir() -> None:
    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    SITE_DIR.mkdir(parents=True, exist_ok=True)


def build_index_html() -> None:
    sys.path.insert(0, str(DJANGO_PROJECT_DIR))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "jp.settings")

    import django  # pylint: disable=import-outside-toplevel
    from django.test import RequestFactory  # pylint: disable=import-outside-toplevel
    from barber.views import home  # pylint: disable=import-outside-toplevel

    django.setup()

    request = RequestFactory().get("/")
    response = home(request)
    html = response.content.decode("utf-8")
    # GitHub Pages project URLs are served under /<repo>/, so absolute
    # /static/... URLs would break. Rewrite to relative static/... paths.
    html = html.replace('"/static/', '"static/').replace("'/static/", "'static/")
    (SITE_DIR / "index.html").write_text(html, encoding="utf-8")


def copy_static_assets() -> None:
    if not APP_STATIC_DIR.exists():
        raise FileNotFoundError(f"Static directory not found: {APP_STATIC_DIR}")
    shutil.copytree(APP_STATIC_DIR, SITE_DIR / "static", dirs_exist_ok=True)


def write_pages_markers() -> None:
    # Prevent Jekyll processing so files are served exactly as built.
    (SITE_DIR / ".nojekyll").write_text("", encoding="utf-8")


def main() -> None:
    clean_site_dir()
    build_index_html()
    copy_static_assets()
    write_pages_markers()
    print(f"Built GitHub Pages bundle at: {SITE_DIR}")


if __name__ == "__main__":
    main()
