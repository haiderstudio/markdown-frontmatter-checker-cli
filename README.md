# markdown-frontmatter-checker-cli

Check Markdown frontmatter has the required keys, fail CI on a missing key.

[![CI](https://github.com/haiderstudio/markdown-frontmatter-checker-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/haiderstudio/markdown-frontmatter-checker-cli/actions/workflows/ci.yml) [![Licence: MIT](https://img.shields.io/badge/Licence-MIT-yellow.svg)](LICENSE)

## What it does

`frontmatter_checker` reads Markdown files, parses the YAML frontmatter
block at the top of each file (the `---` block), and checks it against
the keys you name. A file fails when it has no frontmatter, when the
frontmatter does not parse, when a required key is missing or empty, or
when a key has the wrong type. Extra keys are allowed unless you pass
`--strict`.

- `--require KEY` names a key every file must have, with a non-empty
  value. Repeat it for more keys.
- `--type KEY:TYPE` names a key that must have a type: `str`, `int`,
  `bool`, `list`, or `date` (a `YYYY-MM-DD` string). Repeat it for more
  keys.
- `--config FILE` reads the same lists from a JSON file, so a team can
  share one rule set: `{"required": ["title", "date"], "types":
  {"tags": "list"}, "allow": ["draft"], "strict": false}`.
- `--strict` fails on any key that is not required, typed, or allowed.
- It checks one file, several files, or a whole directory (directories
  are scanned for `.md` and `.markdown` files, including
  subdirectories, unless you pass `--no-recursive`).
- It prints `PASS` or `FAIL` per file, with the exact reason, and a
  summary line. It exits 1 when any file fails, so it can fail a CI
  run.
- It is report-only and runs fully offline: it never rewrites a file,
  sends nothing anywhere, and needs no API key.

## What it does NOT do

- It does not check frontmatter against a JSON Schema, and it does not
  check types beyond `str`, `int`, `bool`, `list`, and `date`. If you
  need full schema validation, that is a different tool's job.
- It does not fix frontmatter. A missing key is reported, not added.
- It does not read TOML (`+++`) or JSON (`{...}`) frontmatter. Only the
  YAML `---` block is supported.
- It does not parse full YAML. The parser handles the shapes that show
  up in real blog and docs frontmatter: plain and quoted scalars, flow
  lists (`[a, b]`), block lists (`- item`), one level of nested
  mappings, and `#` comments. Anchors, aliases, tags, multi-line
  quoted strings, and multi-document files are outside the supported
  subset and are reported as parse errors, not guessed at.
- It does not check the body of the Markdown file. Headings, links,
  and spelling are other tools' jobs.

## Who it is for

Anyone who keeps Markdown files that need frontmatter to be right
before a build: a blogger whose posts need a title, date, and tags, a
docs site where every page needs a title and a category, or a team
adding a CI step that fails the build when a page ships without its
required fields. If the files are right, you get a quiet pass; if one
is wrong, the report says exactly which file and which key.

## How this differs from similar tools

Frontmatter validation already exists, but it lives inside bigger
tools or other languages. The top GitHub hit for the exact job,
`remark-lint-frontmatter-schema` (81 stars), is a TypeScript remark
plugin that validates frontmatter against a JSON Schema — it needs
Node and a schema file. `schematter` (19 stars) is a Rust tool with
the same JSON-Schema approach and a `cargo install`. The closest
small rival, `vinicioslc/frontmatter-validator` (4 stars), is a
JavaScript tool for Gatsby sites that also tries to fix missing
fields. Obsidian plugins and vault checkers validate frontmatter
inside Obsidian, not from the command line. The `markdown-page-checker`
npm package checks required frontmatter properties, but as part of a
bigger page check (including writing-style rules) and it needs Node.

This tool does a narrower job: a Python standard-library-only CLI
that checks one thing — the required keys, with optional simple types
— on one file or a whole folder, reports the exact failure per file,
and exits 1 for CI. No install beyond Python, no schema file, no
Node, no Rust, no fixing.

## Install

Python standard library only — no packages to download. Clone the
repo and run it in place:

```sh
git clone https://github.com/haiderstudio/markdown-frontmatter-checker-cli.git
cd markdown-frontmatter-checker-cli
```

Python 3.10 or newer.

## Usage

Check several files at once:

```sh
python3 src/frontmatter_checker.py --require title --require date --type tags:list examples/good.md examples/missing-date.md examples/empty-title.md examples/bad-tags.md examples/no-frontmatter.md
```

Real output:

```text
PASS examples/good.md
FAIL examples/missing-date.md: missing required key 'date'
FAIL examples/empty-title.md: empty value for required key 'title'
FAIL examples/bad-tags.md: key 'tags' should be list, got str
FAIL examples/no-frontmatter.md: no frontmatter block (file must start with ---)
5 file(s) checked, 1 passed, 4 failed
```

The command exits 1, because four files fail. The same output is
saved in `examples/sample-output.txt`.

Check the good file alone:

```sh
python3 src/frontmatter_checker.py --require title --require date --type tags:list examples/good.md
```

Real output:

```text
PASS examples/good.md
1 file(s) checked, 1 passed, 0 failed
```

The command exits 0.

Check a whole folder, with the rules in a config file:

```sh
python3 src/frontmatter_checker.py --config frontmatter.json docs/
```

`frontmatter.json` holds the same lists the flags take:

```json
{"required": ["title", "date"], "types": {"tags": "list"}, "allow": ["draft"]}
```

Command-line flags add to the config file: a `--require` flag adds a
key, a `--type` flag adds a type, and `--strict` on the command line
turns strict mode on even if the config does not set it.

## Examples

### 1. Fail CI on a post with no date

`examples/missing-date.md` has a title and tags, but no date:

```sh
python3 src/frontmatter_checker.py --require title --require date examples/missing-date.md
```

```text
FAIL examples/missing-date.md: missing required key 'date'
1 file(s) checked, 0 passed, 1 failed
```

The exit code is 1. Put the same command in CI and the build fails
until the file is fixed. With a valid file the same command prints
`PASS examples/missing-date.md` and exits 0.

### 2. A tag that is not a list

`examples/bad-tags.md` has `tags: composting` — one bare word, not a
list:

```sh
python3 src/frontmatter_checker.py --type tags:list examples/bad-tags.md
```

```text
FAIL examples/bad-tags.md: key 'tags' should be list, got str
1 file(s) checked, 0 passed, 1 failed
```

The report names the key, the type it should be, and the type it
actually is.

### 3. Strict mode catches a stray key

```sh
python3 src/frontmatter_checker.py --require title --strict examples/good.md
```

```text
FAIL examples/good.md: unexpected key 'date' (strict mode); unexpected key 'tags' (strict mode); unexpected key 'draft' (strict mode)
1 file(s) checked, 0 passed, 1 failed
```

Add the keys to `--allow` (or to the config file's `allow` list) and
the same file passes.

## How it is tested

```sh
python3 tests/test_frontmatter_checker.py
```

54 tests, standard library `unittest` only — no third-party
packages. They cover: frontmatter parsing (plain and quoted scalars,
flow and block lists, nested mappings, numbers and booleans,
comments, duplicate keys, unclosed blocks, anchors refused), the
checks (missing key, empty value, wrong type for `str`, `int`,
`bool`, `list`, and `date`, no frontmatter, strict mode), file
collection (directories, subdirectories, `.markdown` files, missing
paths), the config file (good, bad JSON, bad type name, missing
file), the CLI (exit 0, 1, and 2, summary lines, config and strict
flags, `--version`, input files left unchanged), the bundled
examples (the committed `examples/sample-output.txt` is compared
against a fresh run, and the README's quoted outputs are checked
against it), the example script, and a check that the code and the
tests import standard library only.

The bundled example is a real run, not made-up output:

```sh
sh examples/run-example.sh
```

It checks all five example files and then the good file alone. The
committed `examples/sample-output.txt` is the output of the check run.

## Contributing

Small, focused improvements are welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE).

## Original work

Built from scratch for this repo. The frontmatter parser is a small
plain-text parser written for this tool; no YAML package is used and
no code was copied from any existing frontmatter checker.
