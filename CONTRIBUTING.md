# Working on SubMerge

Everything below runs on a plain Python 3 install. There is nothing to
`pip install` except the linter, and no need for Sublime Text.

## Tests

```bash
python3 -m unittest discover -s test -v
```

`submerge_core`, `submerge_docs`, `submerge_metadata` and `submerge_table`
import nothing from Sublime and are tested directly. `submerge_session` and
`submerge_folder` do, so `test/test_submerge.py` installs a small stand-in for
the `sublime` module before importing them — enough to reach the folder
scanning, gap markup and color validation without the editor.

`SubMerge.py` itself is command wiring and is not unit tested; CI byte-compiles
it on every supported Python version instead.

## Lint

```bash
python3 -m pip install pycodestyle
pycodestyle SubMerge.py modules tools test
```

Line length and exclusions come from `setup.cfg`, so a bare run checks exactly
what CI checks. The fixtures under `test/SubMerge-Test-Data/` are excluded on
purpose: their formatting is the input under test, so a linter must never be
the reason one of them changes. For the same reason `.gitattributes` stops Git
normalizing their line endings.

## Build

```bash
python3 tools/build_package.py
```

Writes `dist/SubMerge.sublime-package`, which is a plain zip whose *root* is
the package directory. The script picks contents from an explicit include list
rather than by excluding things — a missed exclusion ships somebody's
workspace file to every user, whereas a missed inclusion just fails the
manifest check. It also refuses to produce an archive that is missing anything
the plugin loads at runtime, `README.md` included: the user guide command reads
it back with `sublime.load_resource()`.

Builds are deterministic; rebuilding the same source gives a byte-identical
archive, and CI asserts that.

To test a build, drop the file into `Installed Packages/` (Preferences →
Browse Packages…, then up one level) and restart Sublime Text completely.

## Module versions

Each module in `modules/` carries a `VERSION` that `REQUIRED_VERSIONS` in
`SubMerge.py` checks at load time. Sublime does not always re-execute
sub-modules when the top-level plugin file reloads, so overwriting the package
in place can leave new code calling into old modules — which mostly fails
silently, since the function names rarely change. **Bump the module's `VERSION`
and the matching entry in `REQUIRED_VERSIONS` whenever you change a module's
public surface**, so that mismatch is reported instead of quietly misbehaving.

## CI

`.github/workflows/ci.yml` runs tests on Python 3.8 (what Sublime Text 4
bundles, and therefore the version that has to pass) plus 3.12, across Linux,
macOS and Windows — the last two because `file://` URL construction, symlink
handling and permission bits all differ there. Lint and build run on Linux
only, and the built package is uploaded as a workflow artifact.
