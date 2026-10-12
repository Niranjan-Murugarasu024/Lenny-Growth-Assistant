"""
Safe Markdown to HTML preview renderer with strict sanitization policy.
Uses markdown with tables/fenced_code extensions and nh3 (Rust-based) for strict sanitization.
"""
from __future__ import annotations

import re
import markdown
import nh3

# Explicitly permitted HTML tags for essay representation
ALLOWED_TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "b", "strong", "i", "em", "u", "s", "del",
    "blockquote", "pre", "code",
    "ul", "ol", "li",
    "table", "thead", "tbody", "tr", "th", "td",
    "a", "hr", "br", "span", "div",
}

# Permitted attributes per tag
ALLOWED_ATTRIBUTES = {
    "a": {"href", "title", "target"},
    "th": {"align"},
    "td": {"align"},
    "*": {"class", "id"},
}

# Allowed URL schemes (strictly disallows javascript:, data:, vbscript:, file:)
ALLOWED_URL_SCHEMES = {"http", "https", "mailto"}

SCOPED_STYLES = """
<style>
.lenny-essay-preview {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  color: #1a1a1a;
  line-height: 1.7;
  max-width: 780px;
  margin: 0 auto;
  padding: 2rem 1.5rem;
}
.lenny-essay-preview h1 {
  font-size: 2.2rem;
  font-weight: 800;
  line-height: 1.25;
  margin-bottom: 1.5rem;
  color: #111827;
  border-bottom: 2px solid #f3f4f6;
  padding-bottom: 0.5rem;
}
.lenny-essay-preview h2 {
  font-size: 1.5rem;
  font-weight: 700;
  margin-top: 2rem;
  margin-bottom: 0.75rem;
  color: #1f2937;
}
.lenny-essay-preview h3 {
  font-size: 1.2rem;
  font-weight: 600;
  margin-top: 1.5rem;
  margin-bottom: 0.5rem;
  color: #374151;
}
.lenny-essay-preview p {
  margin-bottom: 1.25rem;
  font-size: 1.05rem;
}
.lenny-essay-preview blockquote {
  border-left: 4px solid #6366f1;
  padding: 0.5rem 1rem;
  margin: 1.5rem 0;
  color: #4b5563;
  background: #f9fafb;
  border-radius: 0 4px 4px 0;
}
.lenny-essay-preview ul, .lenny-essay-preview ol {
  margin-bottom: 1.25rem;
  padding-left: 1.5rem;
}
.lenny-essay-preview li {
  margin-bottom: 0.5rem;
}
.lenny-essay-preview a {
  color: #4f46e5;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.lenny-essay-preview table {
  width: 100%;
  border-collapse: collapse;
  margin: 1.5rem 0;
}
.lenny-essay-preview th, .lenny-essay-preview td {
  border: 1px solid #e5e7eb;
  padding: 0.75rem 1rem;
  text-align: left;
}
.lenny-essay-preview th {
  background: #f9fafb;
  font-weight: 600;
}
.lenny-essay-preview hr {
  border: 0;
  border-top: 1px solid #e5e7eb;
  margin: 2rem 0;
}
.lenny-essay-preview code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  background: #f3f4f6;
  padding: 0.2rem 0.4rem;
  border-radius: 3px;
  font-size: 0.9em;
}
</style>
""".strip()


def render_markdown_to_safe_html(
    markdown_text: str,
    include_styles: bool = True,
) -> str:
    """
    Convert canonical Markdown into strictly sanitized, script-free HTML.

    1. Parses Markdown using python-markdown with tables and fenced_code.
    2. Sanitizes output via nh3: disallows raw script tags, inline javascript:,
       unapproved external embeds, event handlers, and untrusted url schemes.
    3. Adds rel='noopener noreferrer' to hyperlinks.
    4. Wraps in scoped CSS container suitable for sandboxed iframes.
    """
    if not markdown_text or not markdown_text.strip():
        return '<div class="lenny-essay-preview"><p></p></div>'

    # 1. Convert markdown to raw HTML
    raw_html = markdown.markdown(
        markdown_text.strip(),
        extensions=["extra", "sane_lists", "nl2br"],
        output_format="html5",
    )

    # 2. Strict sanitization via nh3
    clean_html = nh3.clean(
        raw_html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_URL_SCHEMES,
        link_rel="noopener noreferrer",
    )

    # 3. Wrap in container
    if include_styles:
        return f"{SCOPED_STYLES}\n<div class=\"lenny-essay-preview\">\n{clean_html}\n</div>"
    return f"<div class=\"lenny-essay-preview\">\n{clean_html}\n</div>"


def sanitize_html(
    raw_html: str,
    include_styles: bool = True,
) -> str:
    """
    Directly sanitize untrusted raw HTML input using the strict nh3 policy.

    Strips scripts, event handlers (onclick, onerror), dangerous schemes (javascript:, data:),
    and iframes while preserving safe semantic tags, tables, links, and styling.
    Adds rel='noopener noreferrer' to all anchor tags.
    """
    if not raw_html or not raw_html.strip():
        return '<div class="lenny-essay-preview"><p></p></div>'

    clean_html = nh3.clean(
        raw_html.strip(),
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_URL_SCHEMES,
        link_rel="noopener noreferrer",
    )

    if include_styles:
        return f"{SCOPED_STYLES}\n<div class=\"lenny-essay-preview\">\n{clean_html}\n</div>"
    return f"<div class=\"lenny-essay-preview\">\n{clean_html}\n</div>"

