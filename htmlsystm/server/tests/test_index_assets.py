from pathlib import Path


HTMLSYSTM_ROOT = Path(__file__).resolve().parents[2]
INDEX_TEMPLATE = HTMLSYSTM_ROOT / "templates" / "index.html"
FONTAWESOME_ROOT = HTMLSYSTM_ROOT / "static" / "vendor" / "fontawesome-6.4.0"


def test_homepage_critical_assets_are_self_hosted():
    html = INDEX_TEMPLATE.read_text(encoding="utf-8")

    assert "cdnjs.cloudflare.com" not in html
    assert "fonts.googleapis.com" not in html
    assert "static/vendor/fontawesome-6.4.0/css/fontawesome.min.css" in html
    assert "static/vendor/fontawesome-6.4.0/css/solid.min.css" in html


def test_vendored_solid_icon_assets_are_complete():
    base_css = FONTAWESOME_ROOT / "css" / "fontawesome.min.css"
    solid_css = FONTAWESOME_ROOT / "css" / "solid.min.css"
    solid_font = FONTAWESOME_ROOT / "webfonts" / "fa-solid-900.woff2"

    assert base_css.is_file()
    assert solid_css.is_file()
    assert solid_font.is_file()
    assert "../webfonts/fa-solid-900.woff2" in solid_css.read_text(encoding="utf-8")
