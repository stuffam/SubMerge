"""
SubMerge unit tests.

Runs outside Sublime Text:

    python3 -m unittest discover -s test -v
    python3 test/test_submerge.py

submerge_core, submerge_docs, submerge_metadata and submerge_table import
nothing from Sublime and are tested directly.  submerge_session and
submerge_folder do, so a minimal stand-in is installed below - enough to reach
the pure logic in them (folder scanning, gap markup, color validation) without
pulling in the editor.
"""

import os
import sys
import types
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "test", "SubMerge-Test-Data")
sys.path.insert(0, REPO)


# ---------------------------------------------------------------------------
# Sublime stand-in
# ---------------------------------------------------------------------------

def _install_sublime_stub():
    if "sublime" in sys.modules:
        return sys.modules["sublime"]
    stub = types.ModuleType("sublime")
    stub.DRAW_NO_OUTLINE = stub.DRAW_NO_FILL = stub.HIDDEN = 1
    stub.DRAW_SOLID_UNDERLINE = stub.DRAW_SQUIGGLY_UNDERLINE = 2
    stub.LAYOUT_INLINE = stub.LAYOUT_BLOCK = 0
    stub.OP_EQUAL, stub.OP_NOT_EQUAL = 0, 1
    stub.settings_store = {}

    class _Settings(object):
        def get(self, key, default=None):
            return stub.settings_store.get(key, default)

        def set(self, key, value):
            stub.settings_store[key] = value

        def add_on_change(self, *a):
            pass

        def clear_on_change(self, *a):
            pass

    stub.load_settings = lambda name: _Settings()
    stub.status_message = lambda *a: None
    stub.message_dialog = lambda *a: None
    stub.error_message = lambda *a: None
    stub.set_timeout = lambda fn, delay=0: fn()
    stub.set_timeout_async = lambda fn, delay=0: fn()
    stub.packages_path = lambda: "/tmp"
    stub.windows = lambda: []

    class Region(object):
        def __init__(self, a, b=None):
            self.a, self.b = a, (a if b is None else b)

    class PhantomSet(object):
        def __init__(self, *a):
            pass

        def update(self, *a):
            pass

    stub.Region = Region
    stub.PhantomSet = PhantomSet
    sys.modules["sublime"] = stub
    return stub


sublime_stub = _install_sublime_stub()

from modules import submerge_core as core          # noqa: E402
from modules import submerge_docs as docs          # noqa: E402
from modules import submerge_folder as folders     # noqa: E402
from modules import submerge_metadata as meta      # noqa: E402
from modules import submerge_session as sessions   # noqa: E402
from modules import submerge_table as table        # noqa: E402


def data(*parts):
    return os.path.join(DATA, *parts)


def read(*parts):
    """Fixture text with its line endings intact.

    newline="" matters: the default universal-newline translation turns CRLF
    into LF on the way in, which would silently make the line-ending fixtures
    identical before the diff engine ever sees them.
    """
    with open(data(*parts), "r", encoding="utf-8",
              errors="replace", newline="") as handle:
        return handle.read()


def compare(a, b, **options):
    return core.compare_texts([a, b], core.CompareOptions(**options))


# ---------------------------------------------------------------------------
# diff engine
# ---------------------------------------------------------------------------

class TestAlignment(unittest.TestCase):

    def test_identical_files_produce_no_hunks(self):
        alignment = compare(read("01-basic-file-diff", "identical", "file-a.txt"),
                            read("01-basic-file-diff", "identical", "file-b.txt"))
        self.assertEqual(alignment.hunks, [])
        self.assertTrue(alignment.identical)
        self.assertTrue(alignment.stats()["identical"])

    def test_differing_files_produce_hunks(self):
        alignment = compare(read("01-basic-file-diff", "two-way", "original.txt"),
                            read("01-basic-file-diff", "two-way", "modified.txt"))
        self.assertTrue(alignment.hunks)
        self.assertFalse(alignment.identical)

    def test_crlf_and_lf_match_when_line_endings_ignored(self):
        unix = read("02-line-endings", "unix.txt")
        windows = read("02-line-endings", "windows.txt")
        self.assertTrue(compare(unix, windows, ignore_line_endings=True).identical)
        self.assertFalse(compare(unix, windows, ignore_line_endings=False).identical)

    def test_case_and_whitespace_options(self):
        self.assertFalse(compare("Hello", "hello").identical)
        self.assertTrue(compare("Hello", "hello", ignore_case=True).identical)
        self.assertFalse(compare("a  b", "a b").identical)
        self.assertTrue(compare("a  b", "a b", ignore_whitespace=True).identical)
        self.assertTrue(compare("a b", "ab", ignore_all_whitespace=True).identical)

    def test_three_way_alignment_covers_every_line(self):
        texts = [read("01-basic-file-diff", "three-way", "version-%s.txt" % v)
                 for v in "ABC"]
        alignment = core.compare_texts(texts, core.CompareOptions())
        self.assertEqual(alignment.pane_count, 3)
        for pane, lines in enumerate(alignment.pane_lines):
            # Every line of every pane must appear in exactly one row.
            seen = [row[pane] for row in alignment.rows if row[pane] is not None]
            self.assertEqual(sorted(seen), list(range(len(lines))))

    def test_rows_never_lose_or_duplicate_a_line(self):
        alignment = compare(read("04-moved-lines", "moved-a.txt"),
                            read("04-moved-lines", "moved-b.txt"))
        for pane, lines in enumerate(alignment.pane_lines):
            seen = [row[pane] for row in alignment.rows if row[pane] is not None]
            self.assertEqual(sorted(seen), list(range(len(lines))))

    def test_moved_line_pairs_are_symmetric(self):
        alignment = compare("alpha\nbeta\ngamma\ndelta",
                            "gamma\ndelta\nalpha\nbeta",
                            detect_moved=True, moved_min_length=3)
        for pane, mapping in enumerate(alignment.moved):
            for line, (other_pane, other_line) in mapping.items():
                self.assertEqual(alignment.moved[other_pane][other_line],
                                 (pane, line))

    def test_gaps_account_for_every_missing_row(self):
        alignment = compare("a\nb\nc\nd", "a\nd")
        for pane in range(alignment.pane_count):
            missing = sum(1 for row in alignment.rows if row[pane] is None)
            self.assertEqual(sum(alignment.gaps[pane].values()), missing)

    def test_empty_and_single_line_files(self):
        self.assertTrue(compare("", "").identical)
        self.assertFalse(compare("", "x").identical)
        self.assertTrue(compare("only", "only").identical)

    def test_blank_line_option(self):
        self.assertFalse(compare("a\n\nb", "a\nb").identical)
        self.assertTrue(compare("a\n\nb", "a\nb", ignore_blank_lines=True).identical)

    def test_intraline_ranges_stay_inside_the_text(self):
        a, b = "the quick brown fox", "the slow brown cat"
        a_ranges, b_ranges = core.intraline_ranges(a, b)
        self.assertTrue(a_ranges and b_ranges)
        for start, end in a_ranges:
            self.assertTrue(0 <= start <= end <= len(a))
        for start, end in b_ranges:
            self.assertTrue(0 <= start <= end <= len(b))

    def test_merge_ranges(self):
        self.assertEqual(core.merge_ranges([]), [])
        self.assertEqual(core.merge_ranges([(0, 3), (2, 5)]), [(0, 5)])
        self.assertEqual(core.merge_ranges([(5, 7), (0, 2)]), [(0, 2), (5, 7)])
        self.assertEqual(core.merge_ranges([(0, 2), (2, 4)]), [(0, 4)])

    def test_pane_letters_and_max_panes_agree(self):
        self.assertEqual(core.MAX_PANES, len(core.PANE_LETTERS))


# ---------------------------------------------------------------------------
# CSV / TSV table rendering
# ---------------------------------------------------------------------------

class TestTable(unittest.TestCase):

    OPTIONS = {"delimiter": "auto", "max_column_width": 40,
               "min_column_width": 3, "wrap_columns": True,
               "row_numbers": True, "header_rule": True}

    def render(self, names, **overrides):
        options = dict(self.OPTIONS, **overrides)
        paths = [data("07-csv-tsv-tables", n) for n in names]
        texts = [read("07-csv-tsv-tables", n) for n in names]
        return table.render_all(texts, paths, options)

    def test_simple_csv_renders(self):
        rendered, delimiter = self.render(["simple.csv", "simple-modified.csv"])
        self.assertEqual(delimiter, ",")
        self.assertEqual(len(rendered), 2)
        self.assertTrue(all(r.strip() for r in rendered))

    def test_tsv_uses_tab(self):
        _rendered, delimiter = self.render(["data.tsv", "data-modified.tsv"])
        self.assertEqual(delimiter, "\t")

    def test_ragged_rows_do_not_raise(self):
        rendered, _ = self.render(["ragged-rows-a.csv", "ragged-rows-b.csv"])
        self.assertEqual(len(rendered), 2)

    def test_quoted_commas_and_embedded_newlines(self):
        rendered, _ = self.render(["quoted-commas-a.csv", "quoted-commas-b.csv"])
        self.assertEqual(len(rendered), 2)
        rendered, _ = self.render(["embedded-newlines-a.csv",
                                   "embedded-newlines-b.csv"])
        self.assertEqual(len(rendered), 2)

    def test_column_widths_are_shared_across_panes(self):
        tables = [table.parse(read("07-csv-tsv-tables", n), ",")
                  for n in ("simple.csv", "simple-modified.csv")]
        widths = table.compute_widths(tables)
        for one in tables:
            self.assertEqual(len(table.compute_widths([one])), len(widths))

    # -- regressions --------------------------------------------------------

    def test_multi_character_delimiter_falls_back(self):
        # csv.reader raises TypeError (not csv.Error) for these, which used to
        # escape parse() and abort the whole comparison.
        for bad in ("||", "", "<>"):
            delimiter = table.sniff_delimiter("a,b\n1,2", "x.csv", bad)
            self.assertEqual(len(delimiter), 1)
            self.assertEqual(table.parse("a,b", bad), [["a", "b"]])

    def test_escaped_tab_delimiter_is_accepted(self):
        self.assertEqual(table.sniff_delimiter("a\tb", None, "\\t"), "\t")

    def test_non_positive_widths_do_not_raise(self):
        for min_width, max_width in ((0, 40), (-1, 40), (3, 0), (-5, -5)):
            rendered, _ = self.render(["simple.csv"],
                                      min_column_width=min_width,
                                      max_column_width=max_width)
            self.assertEqual(len(rendered), 1)

    def test_wrap_handles_zero_width(self):
        self.assertEqual(table._wrap("", 0), [""])
        self.assertTrue(table._wrap("hello world", 0))

    def test_is_table_file(self):
        self.assertTrue(table.is_table_file("x.csv"))
        self.assertTrue(table.is_table_file("x.TSV"))
        self.assertFalse(table.is_table_file("x.txt"))
        self.assertTrue(table.is_table_file("x.txt", [".txt"]))
        self.assertFalse(table.is_table_file(None))


# ---------------------------------------------------------------------------
# Markdown -> HTML
# ---------------------------------------------------------------------------

class TestDocs(unittest.TestCase):

    def test_headings_lists_tables_and_code(self):
        html = docs.markdown_to_html(
            "# Title\n\nSome *text* and **bold**.\n\n"
            "- one\n- two\n\n1. first\n2. second\n\n"
            "| a | b |\n|---|---|\n| 1 | 2 |\n\n"
            "```\ncode & more\n```\n\n> quoted\n\n---\n")
        for fragment in ("<h1", "<em>text</em>", "<strong>bold</strong>",
                         "<ul>", "<ol>", "<table>", "<pre><code>",
                         "<blockquote>", "<hr>"):
            self.assertIn(fragment, html)
        self.assertIn("code &amp; more", html)

    def test_relative_and_absolute_links_are_kept(self):
        for target in ("https://example.com/a?b=1&c=2", "#anchor",
                       "README.md", "mailto:someone@example.com"):
            html = docs._inline("[label](%s)" % target)
            self.assertIn("<a href=", html)
            self.assertIn("label</a>", html)

    # -- regressions --------------------------------------------------------

    def test_quotes_cannot_break_out_of_the_href_attribute(self):
        html = docs._inline('[click](" onmouseover="alert(1))')
        self.assertNotIn('onmouseover="alert', html)
        self.assertNotIn('href=""', html)

    def test_dangerous_schemes_are_dropped_but_text_survives(self):
        for target in ("javascript:alert(1)", "data:text/html,<b>x</b>",
                       "vbscript:msgbox", "JaVaScRiPt:alert(1)"):
            html = docs._inline("[label](%s)" % target)
            self.assertNotIn("<a href=", html)
            self.assertIn("label", html)

    def test_ampersands_are_not_double_escaped(self):
        html = docs._inline("[x](https://e.com/?a=1&b=2)")
        self.assertIn("a=1&amp;b=2", html)
        self.assertNotIn("&amp;amp;", html)

    def test_inline_code_is_not_reinterpreted(self):
        html = docs._inline("use `**not bold**` here")
        self.assertIn("<code>**not bold**</code>", html)
        self.assertNotIn("<strong>", html)

    def test_build_page_is_self_contained(self):
        page = docs.build_page("# Guide\n\nHello.\n", version="1.0.0")
        self.assertTrue(page.startswith("<!DOCTYPE html>"))
        self.assertIn("<style>", page)
        self.assertIn("1.0.0", page)

    def test_packaged_readme_renders(self):
        with open(os.path.join(REPO, "README.md"), encoding="utf-8") as handle:
            page = docs.build_page(handle.read(), version="1.0.0")
        self.assertIn("<h1", page)
        self.assertNotIn("javascript:", page)


# ---------------------------------------------------------------------------
# metadata
# ---------------------------------------------------------------------------

class TestMetadata(unittest.TestCase):

    def write(self, name, payload):
        import tempfile
        directory = getattr(self, "_dir", None)
        if directory is None:
            directory = self._dir = tempfile.mkdtemp()
        path = os.path.join(directory, name)
        with open(path, "wb") as handle:
            handle.write(payload)
        return path

    def test_line_ending_detection(self):
        self.assertEqual(meta.detect_line_endings(b"a\nb\n"), "LF")
        self.assertEqual(meta.detect_line_endings(b"a\r\nb\r\n"), "CRLF")
        self.assertEqual(meta.detect_line_endings(b"a\rb\r"), "CR")
        self.assertEqual(meta.detect_line_endings(b""), "none")
        self.assertTrue(meta.detect_line_endings(b"a\r\nb\n").startswith("mixed"))

    def test_bom_and_encoding_detection(self):
        self.assertEqual(meta.detect_bom(b"\xef\xbb\xbfx"), "UTF-8")
        self.assertEqual(meta.detect_bom(b"\xff\xfex"), "UTF-16 LE")
        self.assertEqual(meta.detect_bom(b"plain"), "none")
        self.assertEqual(meta.detect_encoding(b"plain ascii"), "ASCII")
        self.assertEqual(meta.detect_encoding("café".encode("utf-8")), "UTF-8")
        self.assertEqual(meta.detect_encoding(b"\xef\xbb\xbfx"), "UTF-8 with BOM")
        self.assertEqual(meta.detect_encoding(b"\x81\x82\x83"), "binary / 8-bit")

    def test_streaming_scan_matches_a_whole_file_hash(self):
        import hashlib
        payloads = {
            "empty": b"",
            "no-newline": b"abc",
            "crlf": b"a\r\nb\r\n",
            "trailing-cr": b"abc\r",
            "lone-cr": b"\r",
            "mixed": b"a\r\nb\nc\rd",
            "high-bit": "café\n".encode("utf-8"),
        }
        for name, payload in payloads.items():
            path = self.write(name, payload)
            fields = meta.scan_file(path).fields()
            self.assertEqual(fields["sha1"], hashlib.sha1(payload).hexdigest(),
                             name)
            self.assertEqual(
                fields["sha1_normalized"],
                hashlib.sha1(meta.normalize_eol(payload)).hexdigest(), name)

    def test_scan_is_independent_of_chunk_size(self):
        # A CRLF landing exactly on a read boundary must still count as one
        # CRLF rather than a stray CR followed by a stray LF.
        payload = b"x" * 100 + b"\r\n" + b"y" * 100 + b"\r" + b"z"
        path = self.write("boundary", payload)
        reference = meta.scan_file(path, chunk=1 << 16).fields()
        for chunk in (1, 2, 3, 7, 101, 102, 103):
            self.assertEqual(meta.scan_file(path, chunk=chunk).fields(),
                             reference, "chunk=%d" % chunk)

    def test_line_counts(self):
        for payload, expected in ((b"", 0), (b"a", 1), (b"a\n", 1),
                                  (b"a\nb", 2), (b"a\r\nb\r\n", 2),
                                  (b"a\rb\r", 2)):
            path = self.write("lines", payload)
            self.assertEqual(meta.scan_file(path).lines, expected, repr(payload))

    def test_collect_reports_a_missing_file_rather_than_raising(self):
        info = meta.collect(os.path.join(DATA, "does-not-exist"))
        self.assertIn("error", info)
        self.assertNotIn("sha1", info)

    def test_unreadable_file_is_not_reported_as_matching(self):
        good = meta.collect(data("01-basic-file-diff", "identical", "file-a.txt"))
        broken = {"name": "x", "path": "x", "error": "boom"}
        self.assertTrue(meta.differing_fields([good, broken]))

    def test_error_is_shown_in_the_report(self):
        broken = {"name": "x", "path": "/tmp/x", "error": "permission denied"}
        good = meta.collect(data("01-basic-file-diff", "identical", "file-a.txt"))
        report = meta.render_report(["/tmp/x", good["path"]], [broken, good],
                                    content_identical=False)
        self.assertIn("permission denied", report)

    def test_comparable_fields_drops_eol_sensitive_ones(self):
        with_eol = meta.comparable_fields(None, ignore_line_endings=False)
        without = meta.comparable_fields(None, ignore_line_endings=True)
        for field in ("line_endings", "sha1", "size"):
            self.assertIn(field, with_eol)
            self.assertNotIn(field, without)

    def test_identical_fixtures_have_identical_metadata_digests(self):
        a = meta.collect(data("01-basic-file-diff", "identical", "file-a.txt"))
        b = meta.collect(data("01-basic-file-diff", "identical", "file-b.txt"))
        self.assertEqual(a["sha1"], b["sha1"])

    def test_eol_variants_share_a_normalized_digest(self):
        a = meta.collect(data("02-line-endings", "unix.txt"))
        b = meta.collect(data("02-line-endings", "windows.txt"))
        self.assertNotEqual(a["sha1"], b["sha1"])
        self.assertEqual(a["sha1_normalized"], b["sha1_normalized"])


# ---------------------------------------------------------------------------
# folder comparison
# ---------------------------------------------------------------------------

class TestFolders(unittest.TestCase):

    OPTIONS = {"exclude": [], "max_depth": 0, "compare_mode": "content",
               "show_identical": True, "follow_symlinks": False,
               "compare_metadata": False, "metadata_fields": None,
               "ignore_line_endings": True}

    def scan(self, roots, **overrides):
        options = dict(self.OPTIONS, **overrides)
        root, summary = folders.scan(roots, options)
        return root, summary, options

    def test_identical_trees_report_no_differences(self):
        roots = [data("10-folder-comparison", "FolderD-Identical-%d" % n)
                 for n in (1, 2)]
        _root, summary, _ = self.scan(roots)
        self.assertEqual(summary["different"], 0)
        self.assertEqual(summary["unique"], 0)
        self.assertTrue(summary["files"])

    def test_differing_trees_report_differences(self):
        roots = [data("10-folder-comparison", "Folder%s" % n) for n in "AB"]
        _root, summary, _ = self.scan(roots)
        self.assertTrue(summary["different"] or summary["unique"])

    def test_exclude_patterns_are_honored(self):
        roots = [data("10-folder-comparison", "Folder%s" % n) for n in "AB"]
        _root, with_cache, _ = self.scan(roots)
        _root, without, _ = self.scan(roots, exclude=["__pycache__", "*.pyc"])
        self.assertLess(without["files"], with_cache["files"])

    def test_hiding_identical_files_still_renders(self):
        roots = [data("10-folder-comparison", "Folder%s" % n) for n in "AB"]
        root, summary, options = self.scan(roots, show_identical=False)
        text, rows = folders.render(root, roots, options, summary)
        self.assertIn("Folder Comparison", text)
        self.assertNotIn(folders.MARK[folders.STATUS_IDENTICAL] + " AB",
                         "\n".join(row for row in text.splitlines()
                                   if not row.startswith("  [")))

    def test_keep_flags_match_a_naive_recursive_check(self):
        roots = [data("10-folder-comparison", "Folder%s" % n) for n in "AB"]
        root, summary, options = self.scan(roots, show_identical=False)
        folders._mark_keep(root, False)

        def naive(node):
            return (node.status != folders.STATUS_IDENTICAL
                    or any(naive(child) for child in node.children))

        def walk(node):
            self.assertEqual(node.keep, naive(node), node.name)
            for child in node.children:
                walk(child)

        for child in root.children:
            walk(child)

    def test_max_depth_bounds_the_tree(self):
        """max_depth=N stops after N nested listings below the root, so the
        deepest entry sits at level N + 1 (root children are level 1)."""
        import shutil
        import tempfile
        base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        roots = []
        for name in ("A", "B"):
            deep = os.path.join(base, name, "l1", "l2", "l3", "l4")
            os.makedirs(deep)
            with open(os.path.join(deep, "leaf.txt"), "w") as handle:
                handle.write("leaf\n")
            roots.append(os.path.join(base, name))

        def deepest(node, level=0):
            return max([deepest(c, level + 1) for c in node.children],
                       default=level)

        for max_depth in (1, 2, 3):
            root, _summary, _ = self.scan(roots, max_depth=max_depth)
            self.assertEqual(deepest(root), max_depth + 1,
                             "max_depth=%d" % max_depth)
        root, _summary, _ = self.scan(roots, max_depth=0)     # unlimited
        self.assertEqual(deepest(root), 5)

    def test_depth_limited_folders_say_so(self):
        roots = [data("10-folder-comparison", "Folder%s" % n) for n in "AB"]
        root, summary, options = self.scan(roots, max_depth=1)
        text, _rows = folders.render(root, roots, options, summary)
        self.assertIn("depth limit", text)

    def test_size_shortcut_agrees_with_hashing(self):
        pair = [data("10-folder-comparison", "HashVsQuick", "Folder%s" % n,
                     "same-size-diff-content.txt") for n in "EF"]
        options = dict(self.OPTIONS, ignore_line_endings=False)
        self.assertFalse(folders._same_content(pair, "content", False))
        self.assertFalse(folders._compare_files(pair, options)[0])

    def test_metadata_digests_are_reused_for_content_comparison(self):
        pair = [data("01-basic-file-diff", "identical", "file-%s.txt" % n)
                for n in "ab"]
        metas = [meta.collect(p) for p in pair]
        self.assertTrue(folders._same_content(pair, "content", True, metas))
        self.assertTrue(folders._same_content(pair, "content", True, None))

    def test_too_large_digest_placeholder_falls_back_to_hashing(self):
        pair = [data("01-basic-file-diff", "identical", "file-%s.txt" % n)
                for n in "ab"]
        placeholders = [{"sha1_normalized": "(file too large)"},
                        {"sha1_normalized": "(file too large)"}]
        # Equal placeholders must not be mistaken for equal content.
        self.assertTrue(folders._same_content(pair, "content", True,
                                              placeholders))

    # -- regressions --------------------------------------------------------

    def _dir_symlink(self, path, target):
        """Create a directory symlink, or skip the test if we cannot.

        target_is_directory is not optional on Windows: without it os.symlink
        makes a *file* symlink, which os.path.isdir() then reports as False,
        so no loop forms and the test would silently assert against a
        different scenario than the one it is named for.  Creating one also
        needs Developer Mode or elevation, hence the skip.
        """
        try:
            os.symlink(target, path, target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest("directory symlinks unavailable on this platform")
        if not os.path.isdir(path):
            self.skipTest("directory symlinks not resolvable on this platform")

    def _looping_roots(self, target, filename=None):
        import shutil
        import tempfile
        base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        roots = []
        for name in ("A", "B"):
            root = os.path.join(base, name)
            os.makedirs(os.path.join(root, "sub"))
            if filename:
                with open(os.path.join(root, "sub", filename), "w") as handle:
                    handle.write("hi\n")
            self._dir_symlink(os.path.join(root, "sub", "loop"), target)
            roots.append(root)
        return roots

    def test_symlink_loop_terminates(self):
        roots = self._looping_roots("../..", filename="f.txt")
        # Before the loop guard this recursed until the interpreter's stack
        # limit and the scan never returned.
        root, summary, options = self.scan(roots)
        self.assertEqual(summary["different"], 0)
        text, _rows = folders.render(root, roots, options, summary)
        self.assertIn("symlink, not followed", text)

    def test_symlink_loop_terminates_even_when_following(self):
        roots = self._looping_roots("..")
        _root, summary, _ = self.scan(roots, follow_symlinks=True)
        # The guard, not the "don't follow" default, is what stops this.
        self.assertIsInstance(summary["dirs"], int)

    def test_rescan_settings_exclude_cosmetic_options(self):
        for option in ("compare_metadata", "folder_max_depth",
                       "ignore_line_endings"):
            self.assertIn(option, folders.RESCAN_ON)
        for option in ("color_preset", "highlight_style", "intraline_mode",
                       "gutter_icon", "graduated_inline_highlight"):
            self.assertNotIn(option, folders.RESCAN_ON)


# ---------------------------------------------------------------------------
# session-layer helpers
# ---------------------------------------------------------------------------

class TestSessionHelpers(unittest.TestCase):

    def tearDown(self):
        sublime_stub.settings_store.clear()

    def test_gap_markup_is_capped(self):
        small = sessions._gap_html(3, "#ff0000")
        self.assertEqual(small.count('class="l"'), 3)
        self.assertNotIn("more line(s)", small)

        # Uncapped this produced one <div> per missing line - megabytes of
        # markup in a single phantom when comparing an empty file to a big one.
        huge = sessions._gap_html(50000, "#ff0000")
        self.assertEqual(huge.count('class="l"'), sessions.GAP_MAX_ROWS)
        self.assertIn("more line(s)", huge)
        self.assertLess(len(huge), 4000)

    def test_gap_markup_has_balanced_style_block(self):
        html = sessions._gap_html(2, "rgba(1,2,3,0.5)")
        self.assertEqual(html.count("<style>"), 1)
        self.assertEqual(html.count("</style>"), 1)
        self.assertIn("rgba(1,2,3,0.5)", html)

    def test_valid_colors_are_accepted(self):
        for value in ("#fff", "#ff0000", "#ff000080", "rgba(1,2,3,0.4)",
                      "rgb(1, 2, 3)", "red", "cornflowerblue"):
            self.assertEqual(sessions._safe_color(value, "#000"), value)

    def test_markup_cannot_be_injected_through_a_color(self):
        for value in ("red } </style><img src=x>", "#fff;}", "", None,
                      "expression(alert(1))", "url(http://x)"):
            self.assertEqual(sessions._safe_color(value, "#000"), "#000")

    def test_columns_layout(self):
        for count in (1, 2, 3):
            layout = sessions.columns_layout(count)
            self.assertEqual(len(layout["cells"]), max(1, count))
            self.assertEqual(layout["cols"][0], 0.0)
            self.assertEqual(layout["cols"][-1], 1.0)

    def test_titles_use_the_shared_separator(self):
        self.assertEqual(sessions.join_names(["a", "b"]), "a ↔ b")
        self.assertTrue(sessions.title_for("", ["a", "b"]).startswith("SubMerge: "))

    def test_options_from_settings_reads_the_store(self):
        sublime_stub.settings_store.update(
            {"ignore_case": True, "intraline_mode": "char",
             "detect_moved_lines": False})
        options = sessions.options_from_settings()
        self.assertTrue(options.ignore_case)
        self.assertEqual(options.intraline_mode, "char")
        self.assertFalse(options.detect_moved)

    def test_highlight_style_falls_back_to_a_known_value(self):
        sublime_stub.settings_store["highlight_style"] = "nonsense"
        self.assertEqual(sessions._highlight_style(), "background")
        sublime_stub.settings_store["highlight_style"] = "squiggly"
        self.assertEqual(sessions._highlight_style(), "squiggly")


# ---------------------------------------------------------------------------
# release packaging
# ---------------------------------------------------------------------------

sys.path.insert(0, os.path.join(REPO, "tools"))
import build_package                                # noqa: E402


class TestBuildPackage(unittest.TestCase):

    def test_plugin_version_is_readable_without_importing(self):
        # SubMerge.py imports sublime, so this has to be parsed, not imported.
        version = build_package.plugin_version()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")

    def test_base_version_strips_v_and_suffixes(self):
        for tag, expected in (("v1.0.0", "1.0.0"),
                              ("1.0.0", "1.0.0"),
                              ("V2.3.4", "2.3.4"),
                              # A release candidate *of* 1.1.0: the suffix
                              # describes the release, not the plugin.
                              ("v1.1.0-rc1", "1.1.0"),
                              ("v1.1.0-beta.2", "1.1.0"),
                              ("v1.1.0+build7", "1.1.0")):
            self.assertEqual(build_package.base_version(tag), expected, tag)

    def test_matching_version_passes(self):
        build_package.check_version("v" + build_package.plugin_version())

    def test_prerelease_tag_is_accepted(self):
        # The release job publishes hyphenated tags as prereleases, so the
        # version gate has to let them through or that path is unreachable.
        build_package.check_version("v%s-rc1" % build_package.plugin_version())

    def test_mismatched_tag_is_rejected(self):
        with self.assertRaises(SystemExit) as caught:
            build_package.check_version("v99.98.97")
        self.assertIn("PLUGIN_VERSION", str(caught.exception))

    def test_manifest_covers_everything_loaded_at_runtime(self):
        names = [archive for _path, archive in build_package.collect()]
        for required in build_package.REQUIRED_IN_ARCHIVE:
            self.assertIn(required, names)
        # README.md is loaded via sublime.load_resource() by the user guide.
        self.assertIn("README.md", names)

    # Files at the repo root that deliberately do not ship.  Anything at the
    # root must be in this set or in INCLUDE_FILES; a file in neither fails
    # the test below.  That is the check that should have caught
    # .python-version going missing, and did not exist when it did.
    NOT_SHIPPED = {
        ".gitignore", ".gitattributes", ".DS_Store", "TODO.txt",
        "CONTRIBUTING.md", "setup.cfg",
        "SubMerge.sublime-project", "SubMerge.sublime-workspace",
    }

    def test_every_root_file_is_shipped_or_explicitly_excluded(self):
        root = {name for name in os.listdir(REPO)
                if os.path.isfile(os.path.join(REPO, name))}
        undecided = root - set(build_package.INCLUDE_FILES) - self.NOT_SHIPPED
        self.assertEqual(
            undecided, set(),
            "root file(s) in neither the package manifest nor the "
            "not-shipped list - decide which, do not leave it implicit")

    def test_plugin_host_is_declared_and_shipped(self):
        # A package without .python-version loads on Sublime's legacy 3.3
        # host, where this plugin cannot import - and a plugin that fails to
        # import registers no commands, so every menu entry silently vanishes.
        build_package.check_plugin_host()
        names = [archive for _path, archive in build_package.collect()]
        self.assertIn(".python-version", names)
        with open(os.path.join(REPO, ".python-version")) as handle:
            self.assertEqual(handle.read().strip(),
                             build_package.EXPECTED_PYTHON)

    def test_plugin_imports_nothing_missing_from_the_declared_host(self):
        # Modules added after Python 3.3. Importing one of these at module
        # level is only safe because .python-version selects the 3.8 host, so
        # if that file is ever dropped again this documents the blast radius.
        import ast
        too_new = {"pathlib": "3.4", "typing": "3.5", "secrets": "3.6",
                   "dataclasses": "3.7", "importlib.resources": "3.7",
                   "zoneinfo": "3.9", "graphlib": "3.9"}
        sources = [os.path.join(REPO, "SubMerge.py")]
        sources += [os.path.join(REPO, "modules", n)
                    for n in os.listdir(os.path.join(REPO, "modules"))
                    if n.endswith(".py")]
        for path in sources:
            with open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), path)
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    self.assertNotIn(
                        name, too_new,
                        "%s imports %s (needs Python %s); safe only while "
                        ".python-version selects 3.8"
                        % (os.path.basename(path), name,
                           too_new.get(name, "?")))

    def test_manifest_ships_nothing_it_should_not(self):
        names = [archive for _path, archive in build_package.collect()]
        for name in names:
            self.assertFalse(name.endswith(build_package.FORBIDDEN_SUFFIXES),
                             name)
            self.assertFalse(name.startswith(("test/", "tools/", ".git")), name)

    def test_build_is_deterministic(self):
        import hashlib
        import shutil
        import tempfile
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, ignore_errors=True)

        def digest():
            path = build_package.build(out)
            with open(path, "rb") as handle:
                return hashlib.sha256(handle.read()).hexdigest()

        self.assertEqual(digest(), digest())


if __name__ == "__main__":
    unittest.main(verbosity=2)
