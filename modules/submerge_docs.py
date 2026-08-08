"""
SubMerge - user guide rendering.

Turns the packaged README.md into a styled, self-contained HTML page so the
guide can be read in a browser instead of as raw Markdown in a tab.

This deliberately implements only the small subset of Markdown the README
actually uses (headings, paragraphs, tables, fenced code, ordered/unordered
lists, blockquotes, bold, inline code, links and horizontal rules). Keeping
the renderer here rather than shipping a second, hand-written HTML copy of
the guide means README.md stays the single source of truth - there is no
second document to forget to update.

No Sublime imports, so it can be tested from a plain Python interpreter.
"""

import html
import re

# See submerge_session.VERSION for why this exists.
VERSION = 2

# Link targets we are willing to emit an <a href> for: absolute http(s), mail,
# same-page anchors, and relative paths (anything with no scheme at all).
# Everything else - "javascript:", "data:", "vbscript:" - is rendered as plain
# text instead. The guide is packaged with the plugin and therefore trusted,
# but this renderer is a general Markdown-to-HTML function whose output is
# opened in the user's real browser, so it does not rely on its input being
# trustworthy.
_SAFE_SCHEME = re.compile(r"^(?:https?:|mailto:|#|[^:]*$)", re.IGNORECASE)

CSS = """
:root {
  --bg: #ffffff; --fg: #24292f; --muted: #57606a; --border: #d0d7de;
  --accent: #0969da; --code-bg: #f6f8fa; --head-bg: #f6f8fa;
  --quote-border: #d0d7de; --quote-bg: #f6f8fa;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0d1117; --fg: #e6edf3; --muted: #9198a1; --border: #30363d;
    --accent: #4493f8; --code-bg: #161b22; --head-bg: #161b22;
    --quote-border: #30363d; --quote-bg: #161b22;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0 auto; padding: 2.5rem 1.5rem 6rem; max-width: 52rem;
  background: var(--bg); color: var(--fg); line-height: 1.6;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
               "Helvetica Neue", Arial, sans-serif;
  font-size: 16px;
}
h1, h2, h3 { line-height: 1.25; margin: 2rem 0 1rem; font-weight: 600; }
h1 {
  font-size: 2rem; padding-bottom: .3rem; margin-top: 0;
  border-bottom: 1px solid var(--border);
}
h2 { font-size: 1.5rem; padding-bottom: .3rem; border-bottom: 1px solid var(--border); }
h3 { font-size: 1.2rem; }
p, ul, ol, table, pre, blockquote { margin: 0 0 1rem; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
code {
  background: var(--code-bg); padding: .15em .4em; border-radius: 6px;
  font-size: .875em;
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas,
               "Liberation Mono", monospace;
}
pre {
  background: var(--code-bg); padding: 1rem; border-radius: 6px;
  overflow-x: auto; border: 1px solid var(--border);
}
pre code { background: none; padding: 0; font-size: .85em; line-height: 1.45; }
table { border-collapse: collapse; width: 100%; display: block; overflow-x: auto; }
th, td {
  border: 1px solid var(--border); padding: .5rem .75rem;
  text-align: left; vertical-align: top;
}
th { background: var(--head-bg); font-weight: 600; }
tr:nth-child(2n) td { background: var(--head-bg); }
blockquote {
  padding: .5rem 1rem; border-left: .25rem solid var(--quote-border);
  background: var(--quote-bg); color: var(--muted); border-radius: 0 6px 6px 0;
}
blockquote > :last-child { margin-bottom: 0; }
hr { border: 0; border-top: 1px solid var(--border); margin: 2rem 0; }
ul, ol { padding-left: 1.75rem; }
li { margin: .25rem 0; }
kbd {
  background: var(--code-bg); border: 1px solid var(--border);
  border-bottom-width: 2px; border-radius: 6px; padding: .1em .45em;
  font-size: .85em; font-family: ui-monospace, Menlo, Consolas, monospace;
}
.footer { margin-top: 4rem; padding-top: 1rem; border-top: 1px solid var(--border);
          color: var(--muted); font-size: .875rem; }
"""


def _anchor(text):
    slug = re.sub(r"[^\w\s-]", "", text.strip().lower())
    return re.sub(r"[\s]+", "-", slug)


def _link(match):
    """[label](href) -> <a>, but only for a scheme we trust.

    `href` arrives already HTML-escaped by the caller (quotes included), so it
    is safe to drop straight into the attribute - escaping it a second time
    here would double-encode ampersands in query strings.
    """
    label, href = match.group(1), match.group(2).strip()
    if not _SAFE_SCHEME.match(href):
        return label
    return '<a href="%s">%s</a>' % (href, label)


def _inline(text):
    """Escape HTML, then re-apply the inline Markdown we support."""
    # quote=True matters: the results below are interpolated into an href
    # attribute, and an unescaped double quote there would end the attribute
    # and let the rest of the link target become markup.
    out = html.escape(text, quote=True)
    # Inline code first, so its contents are not further transformed.
    placeholders = []

    def stash_code(match):
        placeholders.append(match.group(1))
        return "\x00%d\x00" % (len(placeholders) - 1)

    out = re.sub(r"`([^`]+)`", stash_code, out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![*\w])\*([^*\n]+)\*(?!\w)", r"<em>\1</em>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link, out)
    out = re.sub(r"\x00(\d+)\x00",
                 lambda m: "<code>%s</code>" % placeholders[int(m.group(1))],
                 out)
    return out


def _table(rows):
    """rows: list of raw '| a | b |' lines, the second being the separator."""
    def cells(line):
        line = line.strip()
        if line.startswith("|"):
            line = line[1:]
        if line.endswith("|"):
            line = line[:-1]
        return [c.strip() for c in line.split("|")]

    head = cells(rows[0])
    body = [cells(r) for r in rows[2:]]
    out = ["<table>", "<thead><tr>"]
    out += ["<th>%s</th>" % _inline(c) for c in head]
    out.append("</tr></thead><tbody>")
    for row in body:
        out.append("<tr>" + "".join("<td>%s</td>" % _inline(c) for c in row)
                   + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def markdown_to_html(md):
    lines = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # fenced code
        if stripped.startswith("```"):
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>%s</code></pre>"
                       % html.escape("\n".join(buf), quote=False))
            continue

        # headings
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            text = m.group(2)
            out.append('<h%d id="%s">%s</h%d>'
                       % (level, _anchor(text), _inline(text), level))
            i += 1
            continue

        # horizontal rule
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            out.append("<hr>")
            i += 1
            continue

        # table (header row followed by a |---|---| separator)
        if stripped.startswith("|") and i + 1 < n and \
                re.match(r"^\|[\s:|-]+\|?$", lines[i + 1].strip()):
            block = []
            while i < n and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            out.append(_table(block))
            continue

        # blockquote
        if stripped.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append("<blockquote>%s</blockquote>"
                       % markdown_to_html("\n".join(buf)))
            continue

        # ordered list
        if re.match(r"^\d+\.\s+", stripped):
            buf = []
            while i < n and re.match(r"^\d+\.\s+", lines[i].strip()):
                item = re.sub(r"^\s*\d+\.\s+", "", lines[i])
                i += 1
                # continuation lines (indented, not a new item)
                while i < n and lines[i].strip() and \
                        not re.match(r"^\d+\.\s+", lines[i].strip()) and \
                        lines[i].startswith((" ", "\t")):
                    item += " " + lines[i].strip()
                    i += 1
                buf.append("<li>%s</li>" % _inline(item))
            out.append("<ol>%s</ol>" % "".join(buf))
            continue

        # unordered list
        if re.match(r"^[-*]\s+", stripped):
            buf = []
            while i < n and re.match(r"^[-*]\s+", lines[i].strip()):
                item = re.sub(r"^\s*[-*]\s+", "", lines[i])
                i += 1
                while i < n and lines[i].strip() and \
                        not re.match(r"^[-*]\s+", lines[i].strip()) and \
                        lines[i].startswith((" ", "\t")):
                    item += " " + lines[i].strip()
                    i += 1
                buf.append("<li>%s</li>" % _inline(item))
            out.append("<ul>%s</ul>" % "".join(buf))
            continue

        # blank
        if not stripped:
            i += 1
            continue

        # paragraph
        buf = []
        while i < n and lines[i].strip() and \
                not lines[i].strip().startswith(("#", ">", "|", "```")) and \
                not re.match(r"^([-*]\s+|\d+\.\s+)", lines[i].strip()) and \
                not re.match(r"^(-{3,}|\*{3,}|_{3,})$", lines[i].strip()):
            buf.append(lines[i].strip())
            i += 1
        if buf:
            out.append("<p>%s</p>" % _inline(" ".join(buf)))
        else:
            i += 1

    return "\n".join(out)


def build_page(md, title="SubMerge User Guide", version=None):
    body = markdown_to_html(md)
    footer = ""
    if version:
        footer = ('<div class="footer">SubMerge %s &mdash; this page was '
                  'generated from the guide included with the plugin.</div>'
                  % html.escape(version))
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>%s</title>\n<style>%s</style>\n</head>\n<body>\n%s\n%s\n"
        "</body></html>\n" % (html.escape(title), CSS, body, footer)
    )
