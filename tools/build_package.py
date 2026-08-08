#!/usr/bin/env python3
"""
Build SubMerge.sublime-package.

A .sublime-package is a plain zip whose *root* is the package directory - so
"SubMerge.py" sits at the top of the archive, not "SubMerge/SubMerge.py".
Sublime reads files straight out of it, which is why the archive has to carry
everything the plugin loads at runtime, README.md included: the user guide
command reads it back with sublime.load_resource().

Contents are chosen by an explicit include list rather than by excluding
things.  A missed exclusion ships somebody's .sublime-workspace or a stray
credential file to every user; a missed inclusion just fails the manifest
check below.

    python3 tools/build_package.py [--output-dir dist]
"""

import argparse
import json
import os
import re
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE_NAME = "SubMerge.sublime-package"

# Everything the installed plugin needs, relative to the repo root.
INCLUDE_FILES = [
    "SubMerge.py",
    "SubMerge.sublime-settings",
    "SubMergeFolder.sublime-syntax",
    "SubMergeMetadata.sublime-syntax",
    "Main.sublime-menu",
    "Context.sublime-menu",
    "Side Bar.sublime-menu",
    "Tab Context.sublime-menu",
    "Default (Linux).sublime-keymap",
    "Default (OSX).sublime-keymap",
    "Default (Windows).sublime-keymap",
    "messages.json",
    # Loaded at runtime by SubmergeOpenUserGuideCommand / OpenReadmeCommand.
    "README.md",
]

INCLUDE_TREES = [
    ("modules", ".py"),
    ("messages", ".txt"),
]

# Without these the plugin does not work at all, so a build that somehow
# produced an archive missing one of them is a failed build, not a warning.
REQUIRED_IN_ARCHIVE = [
    "SubMerge.py",
    "modules/__init__.py",
    "modules/submerge_core.py",
    "modules/submerge_session.py",
    "modules/submerge_folder.py",
    "modules/submerge_metadata.py",
    "modules/submerge_table.py",
    "modules/submerge_docs.py",
    "SubMerge.sublime-settings",
    "README.md",
]

# Nothing matching these may ever end up in a distributed archive.
FORBIDDEN_SUFFIXES = (
    ".pyc", ".sublime-workspace", ".sublime-project", ".DS_Store",
)


def plugin_version():
    """PLUGIN_VERSION from SubMerge.py, read without importing it.

    Importing is not an option outside Sublime - SubMerge.py imports the
    `sublime` module at the top - so the value is parsed out of the source.
    """
    path = os.path.join(REPO, "SubMerge.py")
    with open(path, encoding="utf-8") as handle:
        match = re.search(r'^PLUGIN_VERSION\s*=\s*"([^"]+)"', handle.read(),
                          re.MULTILINE)
    if not match:
        raise SystemExit("build: no PLUGIN_VERSION found in SubMerge.py")
    return match.group(1)


def base_version(tag):
    """Strip a leading "v" and any prerelease or build suffix.

    v1.1.0-rc1 is a release candidate *of* 1.1.0: the suffix describes the
    release, not the plugin, so PLUGIN_VERSION still reads 1.1.0 and
    messages.json still keys on 1.1.0.  Comparing the whole tag would reject
    every prerelease the release job is built to publish.
    """
    return re.split(r"[-+]", tag.lstrip("vV"), maxsplit=1)[0]


def check_version(expected):
    """Fail unless the release tag, PLUGIN_VERSION and messages.json agree.

    These three drift silently: nothing in Sublime cross-checks them, so a
    tag cut without bumping PLUGIN_VERSION ships a package that reports the
    wrong version, and one without a messages.json entry shows the user no
    upgrade note at all.  A release is the last place that can still be
    caught cheaply.
    """
    expected = base_version(expected)
    found = plugin_version()
    if found != expected:
        raise SystemExit(
            "build: version mismatch - tag says %r, PLUGIN_VERSION in "
            "SubMerge.py says %r. Bump one of them." % (expected, found))

    with open(os.path.join(REPO, "messages.json"), encoding="utf-8") as handle:
        messages = json.load(handle)
    if expected not in messages:
        raise SystemExit(
            "build: messages.json has no entry for %r, so upgrading users "
            "would see no release note. Add \"%s\": \"messages/%s.txt\"."
            % (expected, expected, expected))
    note = os.path.join(REPO, messages[expected])
    if not os.path.isfile(note):
        raise SystemExit("build: messages.json points at %r, which is missing"
                         % messages[expected])
    print("version %s (SubMerge.py, messages.json and tag agree)" % expected)


def collect():
    """Return [(absolute source path, archive name)], sorted."""
    entries = []
    for name in INCLUDE_FILES:
        path = os.path.join(REPO, name)
        if not os.path.isfile(path):
            raise SystemExit("build: missing required file %r" % name)
        entries.append((path, name))

    for directory, suffix in INCLUDE_TREES:
        root = os.path.join(REPO, directory)
        if not os.path.isdir(root):
            raise SystemExit("build: missing required directory %r" % directory)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for filename in sorted(filenames):
                if not filename.endswith(suffix):
                    continue
                path = os.path.join(dirpath, filename)
                archive = os.path.relpath(path, REPO).replace(os.sep, "/")
                entries.append((path, archive))

    return sorted(set(entries), key=lambda pair: pair[1])


def build(output_dir):
    entries = collect()
    names = [archive for _path, archive in entries]

    for archive in names:
        if archive.endswith(FORBIDDEN_SUFFIXES):
            raise SystemExit("build: refusing to ship %r" % archive)

    missing = [name for name in REQUIRED_IN_ARCHIVE if name not in names]
    if missing:
        raise SystemExit("build: archive would be missing %s"
                         % ", ".join(missing))

    os.makedirs(output_dir, exist_ok=True)
    target = os.path.join(output_dir, PACKAGE_NAME)
    # Deterministic: fixed timestamp and ordered entries, so rebuilding the
    # same source produces a byte-identical archive.
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, name in entries:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(path, "rb") as handle:
                archive.writestr(info, handle.read())

    with zipfile.ZipFile(target) as archive:
        broken = archive.testzip()
        if broken is not None:
            raise SystemExit("build: corrupt entry %r" % broken)
        count = len(archive.namelist())

    size = os.path.getsize(target)
    print("%s  (%d files, %.1f KiB)" % (target, count, size / 1024.0))
    for name in names:
        print("  %s" % name)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=os.path.join(REPO, "dist"))
    parser.add_argument(
        "--expect-version", default="", metavar="VERSION",
        help="fail unless the tag, PLUGIN_VERSION and messages.json all "
             "agree on this version (a leading 'v' is stripped). Empty means "
             "no check, so CI can pass the tag name unconditionally.")
    args = parser.parse_args(argv)
    if args.expect_version:
        check_version(args.expect_version)
    build(args.output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
