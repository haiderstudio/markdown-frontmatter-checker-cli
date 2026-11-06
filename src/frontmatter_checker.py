#!/usr/bin/env python3
"""Check Markdown frontmatter has the required keys, fail CI on a missing key.

Run: python3 src/frontmatter_checker.py --require title --require date docs/
     python3 src/frontmatter_checker.py --require title --type tags:list post.md
     python3 src/frontmatter_checker.py --config frontmatter.json docs/

The tool reads Markdown files, parses the YAML frontmatter block at the
top of each file (the ``---`` block), and checks it against the keys you
name. A file fails when it has no frontmatter, when the frontmatter does
not parse, when a required key is missing or empty, or when a key has the
wrong type. Extra keys are allowed unless you pass --strict.

It is report-only: it never rewrites a file, and it runs fully offline.
It sends nothing anywhere and needs no API key.

Frontmatter is parsed by a small plain-text parser, standard library
only — no YAML package is needed. The parser handles the shapes that
show up in real blog and docs frontmatter: plain and quoted scalars,
flow lists (``[a, b]``), block lists (``- item``), one level of nested
mappings, and ``#`` comments. Anything outside that subset (anchors,
aliases, tags, multi-line quoted strings, multi-document files) is
reported as a parse error, not guessed at.

Exit codes: 0 when every file passes, 1 when any file fails,
2 for a usage or input problem (missing file, bad flag, bad config).
"""

import argparse
import contextlib
import json
import re
import sys
from pathlib import Path

VERSION = "1.0.0"

TYPES = ("str", "int", "bool", "list", "date")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INT_RE = re.compile(r"^-?\d+$")
BOOL_WORDS = {"true": True, "false": False, "yes": True, "no": False,
              "on": True, "off": False}


class FrontmatterError(Exception):
    """A frontmatter block that cannot be parsed, with its line number."""

    def __init__(self, line, message):
        super().__init__(message)
        self.line = line
        self.message = message


def _strip_comment(text):
    """Remove a trailing ``# comment`` from an unquoted scalar."""
    out = []
    in_single = False
    in_double = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if i == 0 or text[i - 1] in " \t":
                break
        out.append(ch)
        i += 1
    return "".join(out).rstrip()


def _parse_scalar(raw):
    """Parse one plain-text scalar into a Python value."""
    text = raw.strip()
    if not text:
        return None
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if len(text) >= 2 and text[0] == "'" and text[-1] == "'":
        return text[1:-1].replace("''", "'")
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part) for part in _split_flow(inner)]
    lowered = text.lower()
    if lowered in BOOL_WORDS:
        return BOOL_WORDS[lowered]
    if lowered in ("null", "~"):
        return None
    if INT_RE.match(text):
        try:
            return int(text)
        except ValueError:
            pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def _split_flow(inner):
    """Split a flow list ``a, b, 'c, d'`` on top-level commas."""
    parts = []
    current = []
    in_single = False
    in_double = False
    depth = 0
    for ch in inner:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch in "[{" and not in_single and not in_double:
            depth += 1
        elif ch in "]}" and not in_single and not in_double:
            depth -= 1
        if ch == "," and not in_single and not in_double and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return parts


def _indent_of(line):
    return len(line) - len(line.lstrip(" "))


def parse_frontmatter(text):
    """Parse the frontmatter block of one Markdown document.

    Returns (data, error). ``data`` is a dict of key -> value, or None
    when the file has no frontmatter block. ``error`` is a
    FrontmatterError, or None when parsing worked. A file with no
    frontmatter is not an error here — the caller reports it.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, None
    body = []
    for index, line in enumerate(lines[1:], start=2):
        if line.strip() == "---":
            try:
                return _parse_block(body, start_line=2), None
            except FrontmatterError as exc:
                return None, exc
        body.append(line)
    return None, FrontmatterError(1, "frontmatter block never closed")


def _parse_block(body, start_line):
    """Parse the lines between the two ``---`` markers."""
    data = {}
    i = 0
    while i < len(body):
        raw = body[i]
        line_no = start_line + i
        stripped = raw.strip()
        i += 1
        if not stripped or stripped.startswith("#"):
            continue
        if raw.startswith((" ", "\t")):
            raise FrontmatterError(
                line_no, "unexpected indented line %r" % stripped
            )
        if stripped.startswith(("---", "...")):
            raise FrontmatterError(line_no, "unexpected marker %r" % stripped)
        if ":" not in stripped:
            raise FrontmatterError(
                line_no, "line %r has no key" % stripped
            )
        key, _, rest = stripped.partition(":")
        key = key.strip()
        if not key:
            raise FrontmatterError(line_no, "empty key")
        if key in data:
            raise FrontmatterError(line_no, "duplicate key %r" % key)
        if key.startswith(("&", "*", "!", "{", "[")):
            raise FrontmatterError(
                line_no, "unsupported key %r (anchors, aliases and tags "
                "are outside the supported subset)" % key
            )
        rest = _strip_comment(rest).strip()
        if rest.startswith(("&", "*", "!")):
            raise FrontmatterError(
                line_no, "unsupported value for key %r (anchors, aliases "
                "and tags are outside the supported subset)" % key
            )
        if rest:
            data[key] = _parse_scalar(rest)
            continue
        # Bare key: a block list, a nested mapping, or an empty value.
        nested = []
        while i < len(body):
            nxt = body[i]
            if not nxt.strip() or nxt.strip().startswith("#"):
                i += 1
                continue
            if _indent_of(nxt) == 0:
                break
            nested.append(nxt)
            i += 1
        if not nested:
            data[key] = None
            continue
        first = nested[0].strip()
        if first.startswith("- ") or first == "-":
            items = []
            for item_line in nested:
                item = item_line.strip()
                if not item.startswith("-"):
                    raise FrontmatterError(
                        line_no, "mixed content under key %r" % key
                    )
                items.append(_parse_scalar(_strip_comment(item[1:]).strip()))
            data[key] = items
        elif ":" in first:
            mapping = {}
            for item_line in nested:
                item = item_line.strip()
                if ":" not in item:
                    raise FrontmatterError(
                        line_no, "bad line under key %r: %r" % (key, item)
                    )
                sub_key, _, sub_rest = item.partition(":")
                sub_key = sub_key.strip()
                if sub_key in mapping:
                    raise FrontmatterError(
                        line_no, "duplicate key %r" % sub_key
                    )
                mapping[sub_key] = _parse_scalar(
                    _strip_comment(sub_rest).strip()
                )
            data[key] = mapping
        else:
            raise FrontmatterError(
                line_no, "unsupported value under key %r" % key
            )
    return data


def _type_name(value):
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "mapping"
    return "empty"


def _type_ok(value, wanted):
    if wanted == "str":
        return isinstance(value, str)
    if wanted == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if wanted == "bool":
        return isinstance(value, bool)
    if wanted == "list":
        return isinstance(value, list)
    if wanted == "date":
        return isinstance(value, str) and DATE_RE.match(value) is not None
    return False


def check_file(path, required, types, allowed, strict):
    """Check one file. Returns a list of problem strings (empty = pass)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ["cannot read file: %s" % exc]
    except UnicodeDecodeError:
        return ["file is not valid UTF-8 text"]
    data, error = parse_frontmatter(text)
    if error is not None:
        return ["frontmatter error at line %d: %s" % (error.line, error.message)]
    if data is None:
        return ["no frontmatter block (file must start with ---)"]
    problems = []
    for key in required:
        if key not in data:
            problems.append("missing required key %r" % key)
            continue
        value = data[key]
        if value is None or value == "" or value == []:
            problems.append("empty value for required key %r" % key)
            continue
        wanted = types.get(key)
        if wanted and not _type_ok(value, wanted):
            problems.append(
                "key %r should be %s, got %s" % (key, wanted, _type_name(value))
            )
    for key, wanted in types.items():
        if key in data and key not in required:
            value = data[key]
            if value is not None and not _type_ok(value, wanted):
                problems.append(
                    "key %r should be %s, got %s"
                    % (key, wanted, _type_name(value))
                )
    if strict:
        known = set(required) | set(types) | set(allowed)
        for key in data:
            if key not in known:
                problems.append("unexpected key %r (strict mode)" % key)
    return problems


def collect_files(paths, recursive=True):
    """Expand paths into a sorted list of Markdown files.

    A path may be a file or a directory. Directories are scanned for
    ``.md`` and ``.markdown`` files, recursively when ``recursive`` is
    true. Returns (files, problems) where problems are usage errors.
    """
    files = []
    problems = []
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            problems.append("no such file or directory: %s" % raw)
            continue
        if path.is_file():
            files.append(path)
            continue
        if recursive:
            found = sorted(path.rglob("*.md")) + sorted(
                path.rglob("*.markdown")
            )
        else:
            found = sorted(path.glob("*.md")) + sorted(path.glob("*.markdown"))
        files.extend(sorted(set(found)))
    return files, problems


def load_config(path):
    """Load a JSON config file. Returns (config, error-string-or-None)."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return None, "cannot read config file: %s" % exc
    try:
        config = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, "config file is not valid JSON: %s" % exc
    if not isinstance(config, dict):
        return None, "config file must hold one JSON object"
    for field in ("required", "allow"):
        if field in config and not isinstance(config[field], list):
            return None, "config field %r must be a list" % field
        if field in config and not all(
            isinstance(item, str) for item in config[field]
        ):
            return None, "config field %r must hold strings" % field
    if "types" in config and not isinstance(config["types"], dict):
        return None, "config field 'types' must be an object"
    if "types" in config:
        for key, wanted in config["types"].items():
            if wanted not in TYPES:
                return None, (
                    "config type for key %r must be one of %s, got %r"
                    % (key, ", ".join(TYPES), wanted)
                )
    return config, None


def parse_type_arg(text):
    """Parse one --type KEY:TYPE argument. Returns (key, type)."""
    if ":" not in text:
        raise argparse.ArgumentTypeError(
            "--type needs KEY:TYPE, got %r" % text
        )
    key, _, wanted = text.partition(":")
    key = key.strip()
    wanted = wanted.strip()
    if not key:
        raise argparse.ArgumentTypeError("--type needs a key, got %r" % text)
    if wanted not in TYPES:
        raise argparse.ArgumentTypeError(
            "type must be one of %s, got %r" % (", ".join(TYPES), wanted)
        )
    return key, wanted


def build_parser():
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="frontmatter_checker",
        description=(
            "Check Markdown frontmatter has the required keys. "
            "Prints PASS or FAIL per file and exits 1 when any file "
            "fails, so it can fail a CI run."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="+",
        metavar="PATH",
        help="Markdown file or directory to check. Directories are "
        "scanned for .md and .markdown files.",
    )
    parser.add_argument(
        "--require",
        action="append",
        default=[],
        metavar="KEY",
        help="A key every file must have, with a non-empty value. "
        "Repeat for more keys.",
    )
    parser.add_argument(
        "--type",
        action="append",
        default=[],
        metavar="KEY:TYPE",
        dest="types",
        type=parse_type_arg,
        help="A key that must have a type: str, int, bool, list, or "
        "date (YYYY-MM-DD). Repeat for more keys.",
    )
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        metavar="KEY",
        help="A key that is allowed in --strict mode, besides the "
        "required and typed keys. Repeat for more keys.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on any key that is not required, typed, or allowed.",
    )
    parser.add_argument(
        "--config",
        metavar="FILE",
        help="A JSON file with required, types, and allow lists. "
        "Command-line flags add to it.",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Do not look inside subdirectories of a named directory.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="frontmatter_checker " + VERSION,
    )
    return parser


def run(argv=None, stdout=None, stderr=None):
    """Run the checker. Returns the exit code (0, 1, or 2)."""
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    parser = build_parser()
    try:
        # argparse writes --version output and usage errors to the real
        # sys.stdout/sys.stderr, so point those at the caller's streams.
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    required = list(args.require)
    types = dict(args.types)
    allowed = list(args.allow)
    strict = args.strict
    if args.config:
        config, problem = load_config(args.config)
        if problem:
            print("error: %s" % problem, file=err)
            return 2
        required = list(config.get("required", [])) + required
        for key, wanted in config.get("types", {}).items():
            types.setdefault(key, wanted)
        allowed = list(config.get("allow", [])) + allowed
        if config.get("strict"):
            strict = True
    files, problems = collect_files(args.paths, recursive=not args.no_recursive)
    if problems:
        for problem in problems:
            print("error: %s" % problem, file=err)
        return 2
    if not files:
        print("error: no Markdown files found", file=err)
        return 2
    passed = 0
    failed = 0
    for path in files:
        found = check_file(path, required, types, allowed, strict)
        if found:
            failed += 1
            print("FAIL %s: %s" % (path, "; ".join(found)), file=out)
        else:
            passed += 1
            print("PASS %s" % path, file=out)
    print(
        "%d file(s) checked, %d passed, %d failed"
        % (passed + failed, passed, failed),
        file=out,
    )
    return 1 if failed else 0


def main():
    """Entry point for the command line."""
    sys.exit(run())


if __name__ == "__main__":
    main()
