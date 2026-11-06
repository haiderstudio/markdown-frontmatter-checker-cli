#!/usr/bin/env python3
"""Tests for frontmatter_checker. Standard library unittest only."""

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from frontmatter_checker import (  # noqa: E402
    FrontmatterError,
    check_file,
    collect_files,
    load_config,
    parse_frontmatter,
    run,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
EXAMPLES = ROOT / "examples"


def run_cli(argv):
    """Run the CLI in-process and capture stdout/stderr. Returns (code, out, err)."""
    out = io.StringIO()
    err = io.StringIO()
    code = run(argv, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def write_file(folder, name, text):
    path = Path(folder) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


GOOD_DOC = """---
title: "How to prune a rose bush"
date: 2026-11-02
tags: [gardening, roses]
draft: false
---

# How to prune a rose bush
"""


class TestParseFrontmatter(unittest.TestCase):
    def test_plain_scalars(self):
        data, error = parse_frontmatter(GOOD_DOC)
        self.assertIsNone(error)
        self.assertEqual(data["title"], "How to prune a rose bush")
        self.assertEqual(data["date"], "2026-11-02")
        self.assertEqual(data["tags"], ["gardening", "roses"])
        self.assertIs(data["draft"], False)

    def test_no_frontmatter(self):
        data, error = parse_frontmatter("# Just a heading\n\nText.\n")
        self.assertIsNone(data)
        self.assertIsNone(error)

    def test_empty_document(self):
        data, error = parse_frontmatter("")
        self.assertIsNone(data)
        self.assertIsNone(error)

    def test_unclosed_block(self):
        _data, error = parse_frontmatter("---\ntitle: x\n")
        self.assertIsInstance(error, FrontmatterError)
        self.assertEqual(error.line, 1)

    def test_quoted_strings(self):
        data, _error = parse_frontmatter(
            '---\ntitle: "a: b"\nsingle: \'it\'\'s\'\n---\n'
        )
        self.assertEqual(data["title"], "a: b")
        self.assertEqual(data["single"], "it's")

    def test_block_list(self):
        data, _error = parse_frontmatter(
            "---\ntitle: x\ntags:\n  - one\n  - two\n---\n"
        )
        self.assertEqual(data["tags"], ["one", "two"])

    def test_empty_flow_list(self):
        data, _error = parse_frontmatter("---\ntitle: x\ntags: []\n---\n")
        self.assertEqual(data["tags"], [])

    def test_nested_mapping(self):
        data, _error = parse_frontmatter(
            "---\ntitle: x\nauthor:\n  name: Ana\n  email: a@example.com\n---\n"
        )
        self.assertEqual(data["author"], {"name": "Ana", "email": "a@example.com"})

    def test_numbers_and_booleans(self):
        data, _error = parse_frontmatter(
            "---\ncount: 12\nratio: 1.5\nflag: yes\nnothing: null\n---\n"
        )
        self.assertEqual(data["count"], 12)
        self.assertEqual(data["ratio"], 1.5)
        self.assertIs(data["flag"], True)
        self.assertIsNone(data["nothing"])

    def test_comments_ignored(self):
        data, _error = parse_frontmatter(
            "---\n# a full-line comment\ntitle: x # trailing note\n---\n"
        )
        self.assertEqual(data, {"title": "x"})

    def test_duplicate_key_fails(self):
        _data, error = parse_frontmatter("---\ntitle: a\ntitle: b\n---\n")
        self.assertIsInstance(error, FrontmatterError)
        self.assertIn("duplicate", error.message)

    def test_line_without_key_fails(self):
        _data, error = parse_frontmatter("---\njust some words\n---\n")
        self.assertIsInstance(error, FrontmatterError)

    def test_anchor_refused(self):
        _data, error = parse_frontmatter("---\ntitle: &x hello\n---\n")
        self.assertIsInstance(error, FrontmatterError)
        self.assertIn("outside the supported subset", error.message)

    def test_bare_key_is_empty(self):
        data, _error = parse_frontmatter("---\ntitle:\ndate: 2026-01-01\n---\n")
        self.assertIsNone(data["title"])

    def test_leading_blank_line_means_no_frontmatter(self):
        data, error = parse_frontmatter("\n---\ntitle: x\n---\n")
        self.assertIsNone(data)
        self.assertIsNone(error)

    def test_closing_marker_with_spaces(self):
        data, error = parse_frontmatter("---\ntitle: x\n---  \n\nBody.\n")
        self.assertIsNone(error)
        self.assertEqual(data, {"title": "x"})


class TestCheckFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, text, **kwargs):
        path = write_file(self.folder, "post.md", text)
        return check_file(path, **kwargs)

    def test_good_file_passes(self):
        problems = self.check(
            GOOD_DOC, required=["title", "date"], types={"tags": "list"},
            allowed=[], strict=False,
        )
        self.assertEqual(problems, [])

    def test_missing_key(self):
        problems = self.check(
            "---\ntitle: x\n---\n", required=["title", "date"],
            types={}, allowed=[], strict=False,
        )
        self.assertEqual(problems, ["missing required key 'date'"])

    def test_empty_value(self):
        problems = self.check(
            "---\ntitle:\ndate: 2026-01-01\n---\n", required=["title"],
            types={}, allowed=[], strict=False,
        )
        self.assertEqual(problems, ["empty value for required key 'title'"])

    def test_empty_list_value(self):
        problems = self.check(
            "---\ntitle: x\ntags: []\n---\n", required=["tags"],
            types={}, allowed=[], strict=False,
        )
        self.assertEqual(problems, ["empty value for required key 'tags'"])

    def test_wrong_type(self):
        problems = self.check(
            "---\ntitle: x\ntags: gardening\n---\n", required=["title"],
            types={"tags": "list"}, allowed=[], strict=False,
        )
        self.assertEqual(
            problems, ["key 'tags' should be list, got str"]
        )

    def test_date_type(self):
        problems = self.check(
            "---\ntitle: x\ndate: 2 November 2026\n---\n", required=[],
            types={"date": "date"}, allowed=[], strict=False,
        )
        self.assertEqual(problems, ["key 'date' should be date, got str"])
        ok = self.check(
            "---\ntitle: x\ndate: 2026-11-02\n---\n", required=[],
            types={"date": "date"}, allowed=[], strict=False,
        )
        self.assertEqual(ok, [])

    def test_int_and_bool_types(self):
        problems = self.check(
            "---\norder: twelve\ndraft: maybe\n---\n", required=[],
            types={"order": "int", "draft": "bool"}, allowed=[],
            strict=False,
        )
        self.assertEqual(len(problems), 2)
        self.assertIn("key 'order' should be int, got str", problems)
        self.assertIn("key 'draft' should be bool, got str", problems)

    def test_no_frontmatter(self):
        problems = self.check(
            "# No block\n", required=["title"], types={},
            allowed=[], strict=False,
        )
        self.assertEqual(
            problems, ["no frontmatter block (file must start with ---)"]
        )

    def test_parse_error_reported(self):
        problems = self.check(
            "---\ntitle: a\ntitle: b\n---\n", required=[], types={},
            allowed=[], strict=False,
        )
        self.assertEqual(len(problems), 1)
        self.assertIn("frontmatter error at line 3", problems[0])

    def test_strict_unexpected_key(self):
        problems = self.check(
            GOOD_DOC, required=["title"], types={},
            allowed=["date"], strict=True,
        )
        self.assertEqual(len(problems), 2)
        self.assertIn("unexpected key 'tags' (strict mode)", problems)
        self.assertIn("unexpected key 'draft' (strict mode)", problems)

    def test_extra_keys_allowed_by_default(self):
        problems = self.check(
            GOOD_DOC, required=["title"], types={},
            allowed=[], strict=False,
        )
        self.assertEqual(problems, [])


class TestCollectFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_file_and_directory(self):
        write_file(self.folder, "a.md", GOOD_DOC)
        write_file(self.folder, "sub/b.md", GOOD_DOC)
        write_file(self.folder, "sub/c.txt", "not markdown")
        files, problems = collect_files([str(self.folder)])
        self.assertEqual(problems, [])
        self.assertEqual(
            [p.name for p in files], ["a.md", "b.md"]
        )

    def test_missing_path(self):
        _files, problems = collect_files([str(self.folder / "nope.md")])
        self.assertEqual(len(problems), 1)
        self.assertIn("no such file", problems[0])

    def test_no_recursive(self):
        write_file(self.folder, "a.md", GOOD_DOC)
        write_file(self.folder, "sub/b.md", GOOD_DOC)
        files, _problems = collect_files([str(self.folder)], recursive=False)
        self.assertEqual([p.name for p in files], ["a.md"])

    def test_markdown_extension(self):
        write_file(self.folder, "a.markdown", GOOD_DOC)
        files, _problems = collect_files([str(self.folder)])
        self.assertEqual([p.name for p in files], ["a.markdown"])


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_good_config(self):
        path = write_file(
            self.folder, "config.json",
            json.dumps({"required": ["title"], "types": {"tags": "list"}}),
        )
        config, error = load_config(str(path))
        self.assertIsNone(error)
        self.assertEqual(config["required"], ["title"])

    def test_bad_json(self):
        path = write_file(self.folder, "config.json", "{not json")
        _config, error = load_config(str(path))
        self.assertIn("not valid JSON", error)

    def test_bad_type_name(self):
        path = write_file(
            self.folder, "config.json",
            json.dumps({"types": {"tags": "weird"}}),
        )
        _config, error = load_config(str(path))
        self.assertIn("must be one of", error)

    def test_missing_config(self):
        _config, error = load_config(str(self.folder / "nope.json"))
        self.assertIn("cannot read config", error)


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_good_file_exit_zero(self):
        path = write_file(self.folder, "good.md", GOOD_DOC)
        code, out, _err = run_cli(
            ["--require", "title", "--require", "date", str(path)]
        )
        self.assertEqual(code, 0)
        self.assertIn("PASS %s" % path, out)
        self.assertIn("1 file(s) checked, 1 passed, 0 failed", out)

    def test_bad_file_exit_one(self):
        path = write_file(self.folder, "bad.md", "---\ntitle: x\n---\n")
        code, out, _err = run_cli(["--require", "date", str(path)])
        self.assertEqual(code, 1)
        self.assertIn("FAIL %s: missing required key 'date'" % path, out)
        self.assertIn("1 file(s) checked, 0 passed, 1 failed", out)

    def test_directory_scan(self):
        write_file(self.folder, "good.md", GOOD_DOC)
        write_file(self.folder, "bad.md", "# no frontmatter\n")
        code, out, _err = run_cli(["--require", "title", str(self.folder)])
        self.assertEqual(code, 1)
        self.assertIn("2 file(s) checked, 1 passed, 1 failed", out)

    def test_missing_path_exit_two(self):
        code, _out, err = run_cli([str(self.folder / "nope.md")])
        self.assertEqual(code, 2)
        self.assertIn("no such file", err)

    def test_no_files_exit_two(self):
        code, _out, err = run_cli([str(self.folder)])
        self.assertEqual(code, 2)
        self.assertIn("no Markdown files found", err)

    def test_bad_type_flag_exit_two(self):
        path = write_file(self.folder, "good.md", GOOD_DOC)
        code, _out, err = run_cli(["--type", "tags:weird", str(path)])
        self.assertEqual(code, 2)
        self.assertIn("type must be one of", err)

    def test_config_file(self):
        config = write_file(
            self.folder, "config.json",
            json.dumps({"required": ["title", "date"]}),
        )
        good = write_file(self.folder, "good.md", GOOD_DOC)
        bad = write_file(self.folder, "bad.md", "---\ntitle: x\n---\n")
        code, out, _err = run_cli(
            ["--config", str(config), str(good), str(bad)]
        )
        self.assertEqual(code, 1)
        self.assertIn("PASS %s" % good, out)
        self.assertIn("FAIL %s" % bad, out)

    def test_bad_config_exit_two(self):
        config = write_file(self.folder, "config.json", "{bad")
        path = write_file(self.folder, "good.md", GOOD_DOC)
        code, _out, err = run_cli(["--config", str(config), str(path)])
        self.assertEqual(code, 2)
        self.assertIn("not valid JSON", err)

    def test_strict_flag(self):
        path = write_file(self.folder, "good.md", GOOD_DOC)
        code, out, _err = run_cli(
            ["--require", "title", "--strict", str(path)]
        )
        self.assertEqual(code, 1)
        self.assertIn("unexpected key 'tags'", out)

    def test_version(self):
        code, out, _err = run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertIn("frontmatter_checker 1.0.0", out)

    def test_input_file_unchanged(self):
        path = write_file(self.folder, "bad.md", "---\ntitle: x\n---\n")
        before = path.read_text()
        run_cli(["--require", "date", str(path)])
        self.assertEqual(path.read_text(), before)


class TestExamples(unittest.TestCase):
    def test_sample_output_matches_fresh_run(self):
        code, out, _err = run_cli(
            [
                "--require", "title", "--require", "date",
                "--type", "tags:list",
                str(EXAMPLES / "good.md"),
                str(EXAMPLES / "missing-date.md"),
                str(EXAMPLES / "empty-title.md"),
                str(EXAMPLES / "bad-tags.md"),
                str(EXAMPLES / "no-frontmatter.md"),
            ]
        )
        self.assertEqual(code, 1)
        saved = (EXAMPLES / "sample-output.txt").read_text()
        # The fresh run used absolute example paths; the saved output
        # uses the relative paths from the repo root.
        normalised = out
        for name in (
            "good.md", "missing-date.md", "empty-title.md",
            "bad-tags.md", "no-frontmatter.md",
        ):
            normalised = normalised.replace(
                str(EXAMPLES / name), "examples/" + name
            )
        self.assertEqual(normalised, saved)

    def test_run_example_script(self):
        result = subprocess.run(
            ["sh", str(EXAMPLES / "run-example.sh")],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("PASS examples/good.md", result.stdout)
        self.assertIn("5 file(s) checked, 1 passed, 4 failed", result.stdout)

    def test_readme_quoted_outputs(self):
        readme = (ROOT / "README.md").read_text()
        saved = (EXAMPLES / "sample-output.txt").read_text()
        for line in saved.strip().splitlines():
            self.assertIn(line, readme)


class TestRepoHygiene(unittest.TestCase):
    def test_stdlib_only_imports(self):
        allowed = {
            "argparse", "contextlib", "json", "re", "sys", "pathlib",
            "io", "subprocess", "tempfile", "unittest",
        }
        for folder in ("src", "tests"):
            for path in (ROOT / folder).rglob("*.py"):
                for line in path.read_text().splitlines():
                    line = line.strip()
                    if line.startswith("import "):
                        for name in line[7:].split(","):
                            top = name.strip().split(".")[0].split(" ")[0]
                            self.assertIn(
                                top, allowed | {"frontmatter_checker"},
                                "%s in %s" % (top, path),
                            )
                    elif line.startswith("from "):
                        top = line.split()[1].split(".")[0]
                        self.assertIn(
                            top, allowed | {"frontmatter_checker"},
                            "%s in %s" % (top, path),
                        )

    def test_no_placeholders_or_secrets(self):
        banned = (
            "TODO", "FIXME", "lorem", "coming soon",
            "API_KEY", "api_key", "password =",
        )
        # The tests directory is excluded from this scan: the test file
        # itself names the banned words in its own check list, and it
        # uses temp paths. The shipped content is what must be clean.
        # .git is excluded too: GitHub's checkout ships sample hooks
        # under .git/hooks/ that contain "TODO" (Day 21 CI failure).
        shipped = [
            path
            for path in ROOT.rglob("*")
            if path.is_file()
            and "__pycache__" not in str(path)
            and ".git" not in path.parts
            and "tests" not in path.parts
        ]
        for path in shipped:
            text = path.read_text(errors="ignore")
            for word in banned:
                self.assertNotIn(word, text, "%s in %s" % (word, path))

    def test_no_absolute_paths(self):
        # Same exclusion as the placeholder scan: the test file itself
        # names temp paths in its own check list.
        shipped = [
            path
            for path in ROOT.rglob("*")
            if path.is_file()
            and "__pycache__" not in str(path)
            and ".git" not in path.parts
            and "tests" not in path.parts
        ]
        for path in shipped:
            text = path.read_text(errors="ignore")
            self.assertNotIn(
                "/home/hatch", text, "absolute path in %s" % path
            )
            self.assertNotIn("/tmp/", text, "absolute path in %s" % path)

    def test_gitignore_lists_env_first(self):
        lines = (ROOT / ".gitignore").read_text().splitlines()
        self.assertEqual(lines[0], ".env")

    def test_ci_runs_this_test_file(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn("python3 tests/test_frontmatter_checker.py", ci)


if __name__ == "__main__":
    unittest.main()
