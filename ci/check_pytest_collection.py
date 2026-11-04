#!/usr/bin/env python3
"""Refuse a pytest configuration that removes tests from every run in this repo.

WHY THIS IS A SCRIPT AND NOT A TEST
-----------------------------------
``ci/tests/test_swiss_ephemeris_job.py`` guards the accuracy job's *run line* and
its *environment*, and it does so as a pytest test. That works for every vector
that lives in the workflow file. It cannot work for this one, and the reason is
worth stating precisely rather than discovering again later:

**a pytest test cannot police a pytest setting that stops pytest running tests.**

``addopts`` in ``pyproject.toml`` applies to EVERY pytest invocation in this
repository — the fast ``test`` job, the ``swiss-ephemeris`` accuracy job, and the
``ci/tests/`` guard suite alike. Measured on this branch, appending three lines to
``pyproject.toml`` and running ``pytest ci/tests/ -q``:

  ``addopts = "-k not_corpus"``      -> exit 5, 88 deselected   (pytest itself fails)
  ``addopts = "-k 'not corpus'"``    -> exit 1                  (the pytest guard reds)
  ``addopts = "-m 'not nothing'"``   -> exit 1                  (the pytest guard reds)
  ``addopts = "-k 'not narrow'"``    -> **exit 0**, 87 passed, 1 deselected
  ``addopts = "--collect-only"``     -> **exit 0**, 88 collected, 0 executed

The last two are fail-open. ``--collect-only`` is the worst of them: it deselects
nothing, so every module is still collected and every reachability check still
answers "yes, the job reaches it" — while not one test body executes and the whole
workflow reports green. The pytest-resident guard cannot catch either case, because
under both it is the thing that did not run.

So this check runs as a plain ``python`` step. Nothing in pytest's configuration can
deselect, skip, or no-op it.

WHAT IT REFUSES
---------------
1. A narrowing ``addopts`` in ``pyproject.toml``: anything that deselects tests
   (``-k``, ``-m``, ``--ignore``, ``--ignore-glob``, ``--deselect``) or that collects
   without running them (``--collect-only``, ``--co``). A non-narrowing ``addopts``
   (``-q``, ``--strict-markers``, ...) is perfectly legitimate and is not flagged —
   this is about what removes assertions from a run, not about whether addopts is used.
2. The presence of any OTHER file pytest reads ini options from, ANYWHERE IN THE
   TREE. pytest honours ``pytest.ini``, ``.pytest.ini``, ``tox.ini`` and
   ``setup.cfg`` as well as ``pyproject.toml``. Only the repo-root
   ``pyproject.toml`` exists here and only it is parsed, so any of the other four
   is **refused on sight** — not parsed, not judged for narrowing-ness, refused.
   Extending this checker to parse one is the deliberate act that clears the
   refusal, and that act lands the day one is legitimately added.

   THE ROOT IS NOT THE ONLY PLACE THEY COUNT, and assuming it was is a defect this
   check shipped with. pytest resolves its inifile by walking UP from the common
   ancestor of its arguments, so a config file sitting in a directory the suite is
   invoked against WINS over the root ``pyproject.toml``. Measured on this repo
   with one file added::

       tests/pytest.ini  ==  [pytest]\\naddopts = --collect-only
       python ci/check_pytest_collection.py
           -> "OK: pytest configuration does not narrow collection.", exit 0
       REQUIRE_SWISS_EPHEMERIS=1 python -m pytest tests/ -q
           -> "937 tests collected", 0 executed, exit 0

   The root-only scan reported clean while every assertion in the suite had been
   removed — the same fail-open the ``--collect-only`` case above describes, in a
   directory nothing looked at. ``tests/pyproject.toml`` carrying
   ``[tool.pytest.ini_options] addopts = "--collect-only"`` did the same. The scan
   now covers the whole working tree, scoped by ``git ls-files --cached --others
   --exclude-standard`` so the exclusions come from ``.gitignore`` rather than from
   a hand-kept list here (``.venv/Lib/site-packages`` alone carries dozens of
   third-party ``setup.cfg``/``tox.ini`` files, every one a false refusal under a
   naive walk). A NESTED ``pyproject.toml`` is judged on content rather than on
   sight, because a subpackage manifest is a legitimate thing to add and the other
   four are not.

3. A narrowing ``PYTEST_ADDOPTS`` in **this process's own environment**. A
   workflow- or job-level ``env:`` block lands here too, so an injection that
   silences every pytest run in the job also kills this step — loudly, and before
   the suite it would have silenced. ``--self-test`` refuses first for the same
   reason: it must not certify a detector from inside an already-narrowed
   environment.

4. ``PYTEST_ADDOPTS`` **anywhere in the workflow files** — every job, all three
   ``env:`` levels, and **any mention at all inside a ``run:`` body**. This is the
   placement (3) cannot see: a step-level ``env:``, or a ``$GITHUB_ENV`` write, on
   a *sibling* step never enters this process.

   (3) is narrowing-only; (4) is presence-only. Deliberate: a contributor's shell
   may legitimately carry ``PYTEST_ADDOPTS=-q``, and redding on that would teach
   people to distrust this check — but a workflow file has no legitimate reason to
   name the variable at all, and judging an arbitrary value's narrowing-ness means
   reimplementing pytest's argument parser.

   THE RUN-BODY RULE IS PRESENCE BECAUSE MODELLING FAILED. An earlier version
   analysed argv position — a leading ``VAR=value`` prefix, or an argument to
   ``export``. Both of those are shell-LOCAL: every ``run:`` is a fresh shell, so
   neither escapes its own body. The form that actually reaches a later step is
   GitHub Actions' own cross-step mechanism, ``echo "VAR=value" >> "$GITHUB_ENV"``,
   where the assignment is an argument to ``echo`` and the position check said no.
   Measured with one such line appended to the swiss job's install step: this
   checker exited 0 "OK", all 149 guard tests passed, and the accuracy step would
   then have run under ``--collect-only``. See ``run_body_names_addopts``.

KNOWN BOUND, stated rather than left implicit: this scans the workflow files in
``.github/workflows``. A composite or reusable action pulled in with ``uses:`` can
write ``$GITHUB_ENV`` from a file outside this repository, and nothing here reads
that. Closing it would mean resolving and fetching third-party action source — a
different kind of check. Recorded as a bound of this control, not a claim of
completeness.

PARSED, NEVER GREPPED. ``# addopts = "-k not_corpus"`` is a comment and must stay
invisible; a grep would red on it and a reader would then learn to distrust this
check. The TOML is parsed and the value is shell-split the way pytest splits it.

Usage
-----
    python ci/check_pytest_collection.py            # 0 clean, 1 refused
    python ci/check_pytest_collection.py --self-test

Exit codes: 0 = no narrowing configuration; 1 = refused (with the reason printed).
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import shlex
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - declared in the dev extras
    yaml = None

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"

_WORKFLOW_SCOPE_PATH = Path(__file__).resolve().parent / "workflow_scope.py"


def _load_workflow_scope():
    """Load ``ci/workflow_scope.py`` -- the shared workflow enumeration.

    By path, not ``from ci import ...``: ``ci/`` has no ``__init__.py`` by
    design, and this runs both as ``python ci/check_pytest_collection.py``
    (where ``ci/`` is on ``sys.path``) and loaded by path from
    ``ci/tests/test_pytest_collection_check.py`` (where it is not). The by-path
    form is the one that works in both, and it is the form
    ``ci/check_pr_text.py`` already uses to reach the tree gate.
    """
    spec = importlib.util.spec_from_file_location(
        "_workflow_scope_for_pytest_collection", _WORKFLOW_SCOPE_PATH
    )
    assert spec is not None and spec.loader is not None, _WORKFLOW_SCOPE_PATH
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_workflow_scope = _load_workflow_scope()

# The environment variable pytest reads extra arguments from. Round 1 detected this
# at all three GitHub Actions `env:` levels — but from inside a pytest test, which
# the variable itself disables. See the PYTEST_ADDOPTS section below.
ADDOPTS_ENV = "PYTEST_ADDOPTS"

# Narrowing flags that DESELECT tests, and that consume a value. Kept separate
# because a value-taking flag's argument must never be mistaken for a positional
# target when a caller parses a command line (see ci/tests/test_swiss_ephemeris_job.py).
VALUE_TAKING_DESELECT_FLAGS = ("--ignore", "--ignore-glob", "--deselect", "-k", "-m")

# Narrowing flags that deselect NOTHING and run nothing. `pytest --collect-only`
# collects every module the accuracy gate needs and executes not one test body.
COLLECTION_ONLY_FLAGS = ("--collect-only", "--co")

# Everything that costs a run its assertions, by either mechanism. THIS IS THE ONE
# DEFINITION — ci/tests/test_swiss_ephemeris_job.py imports it rather than keeping a
# second copy, so a flag added here is covered by both readers at once.
NARROWING_FLAGS = VALUE_TAKING_DESELECT_FLAGS + COLLECTION_ONLY_FLAGS

# Files pytest reads ini options (and therefore `addopts`) from, other than
# pyproject.toml. None exists in this repo; any that appears is refused ON SIGHT,
# wherever in the tree it appears — see unparsed_config_files().
PYTEST_CONFIG_FILENAMES = ("pytest.ini", ".pytest.ini", "tox.ini", "setup.cfg")

# The one ini source this checker DOES parse — but only the repo-root copy of it.
# A second one deeper in the tree is a separate, unparsed source (see below).
PYPROJECT_FILENAME = "pyproject.toml"

# Directory names never scanned, used ONLY by the fallback walk below. Git's own
# ignore rules are the source of truth whenever git can answer; this list exists
# so the checker still works in a tree that is not a git checkout (every tmp-tree
# test in ci/tests/test_pytest_collection_check.py is one). Dot-directories are
# skipped wholesale, which covers .git/.venv/.pytest_cache/.mypy_cache.
_UNSCANNED_DIRECTORY_NAMES = frozenset({"venv", "node_modules", "__pycache__", "build", "dist"})


def addopts_tokens(document: dict) -> list[str]:
    """``[tool.pytest.ini_options].addopts`` from a PARSED pyproject document.

    pytest accepts either a string (which it shell-splits) or a list of arguments.
    Each list entry is shell-split too, so a single entry holding ``"-k not_corpus"``
    is read as the two arguments pytest would actually see rather than as one opaque
    token that no flag check would ever match.
    """
    ini_options = (
        ((document.get("tool") or {}).get("pytest") or {}).get("ini_options") or {}
    )
    addopts = ini_options.get("addopts")
    if addopts is None:
        return []
    entries = addopts if isinstance(addopts, list) else [addopts]
    tokens: list[str] = []
    for entry in entries:
        tokens.extend(shlex.split(str(entry), comments=True))
    return tokens


def narrowing_addopts(tokens: list[str]) -> list[str]:
    """The narrowing flags among a parsed ``addopts``, by flag NAME.

    Split on ``=`` first so ``--ignore=path`` and ``--ignore path`` are both caught,
    while ``--color=no`` and a positional path that merely contains a flag's spelling
    are not.
    """
    found: list[str] = []
    for token in tokens:
        if not token.startswith("-"):
            continue
        name = token.split("=", 1)[0]
        if name in NARROWING_FLAGS:
            found.append(name)
    return found


def is_unparsed_config_path(relative: str) -> bool:
    """True when a repo-relative path is a pytest ini source this checker does not parse.

    Pure, path-only, and self-tested — the classification a whole-tree scan turns
    on, kept separate from the scanning so ``--self-test`` can discriminate it
    without a filesystem.
    """
    parts = PurePosixPath(str(relative).replace("\\", "/")).parts
    if not parts:
        return False
    name = parts[-1]
    if name in PYTEST_CONFIG_FILENAMES:
        return True
    # Only the ROOT pyproject.toml is parsed (addopts_tokens reads it). A nested
    # one is a different file that pytest will honour as its inifile when it
    # declares [tool.pytest.ini_options], and nothing here parses it.
    return name == PYPROJECT_FILENAME and len(parts) > 1


def _declares_pytest_ini_options(path: Path) -> bool:
    """Whether a pyproject.toml actually declares ``[tool.pytest.ini_options]``.

    The four filenames above are refused on sight because none has a legitimate
    reason to exist in this repo. A SECOND pyproject.toml might — a subpackage
    manifest is an ordinary thing — so this one is judged on content instead. A
    check that reds on something legitimate is a check people learn to route
    around, which is the same argument the PYTEST_ADDOPTS section makes for
    tolerating `-q` in a contributor's shell.

    Unreadable or unparseable counts as declaring: a manifest nothing could open
    is exactly where a declaration would hide.
    """
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return True
    pytest_table = ((document.get("tool") or {}).get("pytest") or {})
    return isinstance(pytest_table, dict) and "ini_options" in pytest_table


def _git_working_tree_paths(root: Path) -> list[str] | None:
    """Every path git considers part of the working tree, or None if git cannot answer.

    SCOPE FROM THE SOURCE OF TRUTH, NOT A WALK. `--cached --others
    --exclude-standard` is tracked files plus untracked-but-not-ignored ones, so
    the exclusions come from .gitignore itself rather than from a list here that
    could be wrong. That matters concretely: `.venv/Lib/site-packages` carries
    dozens of third-party `setup.cfg` and `tox.ini` files, and every one of them
    would be a false refusal under a naive walk.

    `-z`, AND BYTES, AND NO SEPARATOR REWRITE — three halves of one fix, each
    load-bearing. Measured on the commit before it, against a fixture repo
    holding `caf<e-acute><s-caron>/pytest.ini` with `addopts = --collect-only`:
    this returned `['"caf/303/251/305/241/pytest.ini"', 'plain.txt']` and the
    scan reported CLEAN. `git ls-files` quotes a path carrying non-ASCII bytes
    (`core.quotePath` defaults on), wrapping it in literal double quotes and
    rendering each byte as a backslash-octal escape; the basename then read back
    as `pytest.ini"` and matched nothing. The old `.replace("\\", "/")` — there
    to normalise Windows separators — then rewrote those escapes into fabricated
    directory separators. `-z` disables quoting entirely and NUL-separates the
    records, so a path arrives verbatim whatever bytes it holds and whatever
    `core.quotePath` is set to; git emits `/` separators on every platform, so
    the rewrite has nothing left to do and is removed rather than left to
    corrupt a literal backslash in a POSIX filename. Records are not stripped
    either: with `-z` they are exact, and a leading or trailing space is a legal
    filename character.

    The decode happens HERE, on bytes, not inside subprocess. In text mode it
    happens on a reader thread, where — measured — a UnicodeDecodeError kills
    the thread and hands back `stdout=None` with `returncode=0`, so the next
    `.splitlines()` raised `AttributeError` out of a checker whose contract is
    to reach a verdict. A filename need not be valid UTF-8 on a POSIX
    filesystem, so that is a reachable input, not a hypothetical one. An
    undecodable listing is answered as `None` — "git cannot answer" — which is
    not a silent pass: the caller falls back to `_walked_paths` and the tree is
    still scanned.
    """
    try:
        completed = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    try:
        listing = completed.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return [record for record in listing.split("\0") if record]


def _walked_paths(root: Path) -> list[str]:
    """Fallback enumeration for a tree that is not a git checkout."""
    paths: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if not name.startswith(".")
            and name not in _UNSCANNED_DIRECTORY_NAMES
            and not name.endswith(".egg-info")
        ]
        for filename in filenames:
            paths.append((Path(dirpath) / filename).relative_to(root).as_posix())
    return paths


def unparsed_config_files(root: Path) -> list[str]:
    """Config files pytest would honour that this checker does not parse.

    THE WHOLE TREE, NOT JUST THE ROOT. pytest resolves its inifile by walking UP
    from the common ancestor of its arguments, so a config file in a directory
    the suite is invoked against wins over the root pyproject.toml. Measured on
    this repo before this scan existed, with one file added:

        tests/pytest.ini  ==  [pytest]\\naddopts = --collect-only
        python ci/check_pytest_collection.py
            -> "OK: pytest configuration does not narrow collection.", exit 0
        REQUIRE_SWISS_EPHEMERIS=1 python -m pytest tests/ -q
            -> "937 tests collected", 0 executed, exit 0

    and the same with `tests/pyproject.toml` carrying
    `[tool.pytest.ini_options] addopts = "--collect-only"`. Both are the exact
    fail-open this checker exists to close; the root-only scan reported clean
    about both, because `tests/` is not the root.
    """
    candidates = _git_working_tree_paths(root)
    if candidates is None:
        candidates = _walked_paths(root)

    found: list[str] = []
    for relative in candidates:
        if not is_unparsed_config_path(relative):
            continue
        if PurePosixPath(relative).name == PYPROJECT_FILENAME and not _declares_pytest_ini_options(
            root / relative
        ):
            continue
        found.append(relative)
    return sorted(set(found))


# ---------------------------------------------------------------------------
# Shell tokenising — the single definition, imported by
# ci/tests/test_swiss_ephemeris_job.py rather than copied.
# ---------------------------------------------------------------------------


def join_shell_continuations(run: str) -> list[str]:
    """Split a ``run:`` body into LOGICAL lines, joining backslash-continuations.

    ``shlex.split`` RAISES on a line ending in a lone backslash
    (``ValueError: No escaped character``); tokenising line-by-line therefore drops
    the first line of every continued command and reads the rest as commands of
    their own. Only an ODD number of trailing backslashes continues a line — a
    trailing ``\\\\`` is an escaped backslash, a real final token.
    """
    logical: list[str] = []
    pending = ""
    for physical in run.splitlines():
        line = physical.rstrip("\r")
        trailing_backslashes = len(line) - len(line.rstrip("\\"))
        if trailing_backslashes % 2 == 1:
            pending += line[:-1]
            continue
        logical.append(pending + line)
        pending = ""
    if pending:
        # A continuation with nothing after it. Keep what was accumulated rather
        # than dropping the command — dropping it is the failure this removes.
        logical.append(pending)
    return logical


def shell_commands(run: str) -> list[list[str]]:
    """Tokenise a ``run:`` body into individual shell commands (argv token lists).

    A substring search cannot answer "does this invoke pytest": ``echo "pytest
    tests/"`` contains the string and runs nothing. shlex puts the words in argv
    positions, so a quoted string collapses to ONE token.
    """
    commands: list[list[str]] = []
    for line in join_shell_continuations(run):
        try:
            tokens = shlex.split(line, comments=True)
        except ValueError:
            # Unbalanced quoting — treat the line as opaque rather than guessing.
            continue
        current: list[str] = []
        for token in tokens:
            if token in {"&&", "||", ";", "|", "&"}:
                if current:
                    commands.append(current)
                current = []
                continue
            current.append(token)
        if current:
            commands.append(current)
    return commands


def run_body_names_addopts(run: str) -> bool:
    """True when a ``run:`` body mentions ``PYTEST_ADDOPTS`` at all. PRESENCE, not
    semantics — and the plainest substring test, deliberately.

    TOKENISING WAS THE BUG (PR #66 round-2 review, blocking finding). The previous
    version of this check analysed argv POSITION: it accepted a leading
    ``VAR=value`` prefix or an argument to ``export`` as an assignment, and rejected
    anything else as "just an echo". Both forms it recognised are shell-LOCAL —
    every ``run:`` is a fresh shell, so neither escapes its own body. The form that
    actually reaches a later step is GitHub Actions' own cross-step mechanism::

        echo "PYTEST_ADDOPTS=--collect-only" >> "$GITHUB_ENV"

    ``shell_commands`` renders that as
    ``['echo', 'PYTEST_ADDOPTS=--collect-only', '>>', '$GITHUB_ENV']`` — the
    assignment is an ARGUMENT to echo, so the position check returned False. Measured
    with that one line appended to the swiss job's install step: the checker exited 0
    "OK", all 149 guard tests passed, and the accuracy step would then have run under
    ``--collect-only`` (912 collected, 0 executed, ``REQUIRE_SWISS_EPHEMERIS`` never
    evaluating). The checker caught the weak forms and missed the effective one.

    So this does not model shell semantics at all. Telling a harmless echo from a
    poisoning one requires modelling redirection, heredocs, ``printf``, ``tee``,
    variable indirection — an open surface, and modelling is precisely what failed.
    A ``run:`` body has no more legitimate reason to name this variable than an
    ``env:`` block does; if one ever genuinely needs to, that is an exception to
    record here deliberately, not a rule to relax.
    """
    return ADDOPTS_ENV in run


# ---------------------------------------------------------------------------
# PYTEST_ADDOPTS — TWO arms, because neither alone is enough
# ---------------------------------------------------------------------------
#
# THE ROUND-1 DEFECT, measured and reproduced (PR #66 review, blocking finding).
# Round 1 moved the pyproject arm out of pytest on the argument that "a pytest test
# cannot police a pytest setting that stops pytest running tests" — then left the
# PYTEST_ADDOPTS detector as a pytest test. The same measurement defeats it:
#
#   PYTEST_ADDOPTS='--collect-only' pytest ci/tests/ -q
#       -> exit 0, 119 collected, 0 executed. The guard for this exact vector
#          (test_swiss_job_does_not_inject_pytest_addopts) is among them.
#   PYTEST_ADDOPTS='--collect-only' pytest tests/ -q   with REQUIRE_SWISS_EPHEMERIS=1
#       -> exit 0, 912 collected, 0 executed. The fail-closed flag never evaluates:
#          fixtures do not run during collection, so the accuracy gate asserts
#          nothing and reports success.
#   PYTEST_ADDOPTS='--collect-only' python ci/check_pytest_collection.py
#       -> "OK", exit 0. The checker never read its own environment.
#
# One `env:` block in test.yml and the whole workflow is green having asserted
# nothing, anywhere.
#
#   ARM 1 — RUNTIME. Read what the engine applies: this script runs as a plain
#   python step in the same job, so a workflow- or job-level injection lands in
#   THIS process's environment. It cannot be deselected; it is not a test.
#   Narrowing-only, because a contributor's shell may legitimately carry `-q`.
#
#   ARM 2 — DECLARATION. A step-level `env:` on a SIBLING pytest step never
#   reaches this process, so arm 1 cannot see it. This one parses the workflow
#   files themselves. PRESENCE, not narrowing-ness: a workflow has no legitimate
#   reason to declare the variable at all, and judging an arbitrary value's
#   narrowing-ness means reimplementing pytest's argument parser.


def narrowing_env_addopts(environ: Mapping[str, str]) -> list[str]:
    """Narrowing flags in a ``PYTEST_ADDOPTS`` value from the live environment."""
    raw = environ.get(ADDOPTS_ENV)
    if not raw:
        return []
    try:
        tokens = shlex.split(raw, comments=True)
    except ValueError:
        # Unbalanced quoting. pytest would fail on it too, but refuse rather than
        # guess — an unreadable value is not an absent one.
        return [raw]
    return narrowing_addopts(tokens)


def workflow_paths_in_scope(root: Path) -> list[Path]:
    """Every workflow file, from the repository's ONE scope definition.

    This was ``sorted((root / ".github" / "workflows").iterdir())`` filtered on
    the two suffixes. It read BOTH suffixes — the half-enumeration defect that
    motivated ``ci/workflow_scope.py`` was never present here — but it asked the
    FILESYSTEM, which cannot know whether a file ships:

    * ``--exclude-standard`` — a git-ignored scratch workflow is never pushed,
      so GitHub Actions never runs it and it cannot narrow any pytest run.
      Measured before this migration: such a file was scanned and refused.
    * ``--others`` — an untracked workflow stays in scope, because the cheapest
      moment to catch a declaration is the commit that introduces it.
    * a tree git cannot describe now RAISES. Measured before this migration, a
      directory that is not a checkout answered ``[]`` for this whole arm —
      clean, about files nothing enumerated.

    A path listed from the INDEX may be gone from the working tree (a workflow
    deleted but not yet committed); a directory listing could not produce that,
    so it is dropped here rather than read and crashed on.
    """
    return [p for p in _workflow_scope.workflow_paths(root) if p.is_file()]


def workflow_addopts_declarations(root: Path) -> list[str]:
    """Every ``PYTEST_ADDOPTS`` declaration across the workflow files.

    All three GitHub Actions ``env:`` levels (workflow, job, step) plus inline
    shell assignments in ``run:`` bodies. Every job in every workflow file, not
    just the accuracy job: a declaration anywhere narrows the pytest run in that
    job, and this checker is the only thing outside pytest that can see it.

    A scope git cannot derive is reported as a PROBLEM, never raised and never
    returned as "nothing found": this function's contract is one message per
    problem, and a traceback out of a gate is a worse verdict than a legible
    refusal — but silence is worse than either.
    """
    if yaml is None:  # pragma: no cover - pyyaml is in the dev extras
        return [
            "PyYAML is not installed, so the workflow files could not be scanned for "
            f"{ADDOPTS_ENV} declarations. Refusing rather than reporting clean about "
            "files nothing opened."
        ]

    try:
        paths = workflow_paths_in_scope(root)
    except _workflow_scope.WorkflowScopeError as exc:
        return [
            f"the workflow scope could not be derived from git under {root}: {exc} "
            f"Refusing rather than reporting no {ADDOPTS_ENV} declarations about "
            "files nothing enumerated."
        ]

    if not paths:
        # The sibling's [EMPTY_SCAN], mirrored. Two guards that migrated to one
        # scope definition must not disagree about what an EMPTY scope means:
        # `check_workflow_token_scopes.scan_violations` already refuses this
        # state, and this arm answered `[]` -- clean -- which is "zero found and
        # zero violations are the same green" one state along from the one the
        # git migration closed.
        #
        # Reachable through the migration's own `is_file()` filter as well:
        # every workflow deleted from the worktree while still in the index
        # drops the enumeration to zero paths.
        return [
            f"no workflow files found under {root / '.github' / 'workflows'} "
            f"(scope derived from git), so this checker examined none. It "
            f"refuses rather than reporting no {ADDOPTS_ENV} declarations, "
            f"which would be vacuously true of a scan of nothing."
        ]

    found: list[str] = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            found.append(
                f"{relative} could not be parsed as YAML ({exc.__class__.__name__}), "
                f"so it could not be checked for {ADDOPTS_ENV}. A workflow this "
                "checker cannot read is exactly where a declaration would hide."
            )
            continue
        if not isinstance(document, dict):
            found.append(
                f"{relative} did not parse to a mapping, so it could not be checked "
                f"for {ADDOPTS_ENV}."
            )
            continue

        workflow_env = document.get("env")
        if isinstance(workflow_env, dict) and ADDOPTS_ENV in workflow_env:
            found.append(
                f"{relative} declares {ADDOPTS_ENV} at WORKFLOW level "
                f"({workflow_env[ADDOPTS_ENV]!r}) — it reaches every job in the file."
            )

        jobs = document.get("jobs")
        if not isinstance(jobs, dict):
            continue
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            job_env = job.get("env")
            if isinstance(job_env, dict) and ADDOPTS_ENV in job_env:
                found.append(
                    f"{relative} job {job_name!r} declares {ADDOPTS_ENV} at JOB level "
                    f"({job_env[ADDOPTS_ENV]!r})."
                )
            for step in job.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                label = step.get("name") or "<unnamed step>"
                step_env = step.get("env")
                if isinstance(step_env, dict) and ADDOPTS_ENV in step_env:
                    found.append(
                        f"{relative} job {job_name!r} step {label!r} declares "
                        f"{ADDOPTS_ENV} ({step_env[ADDOPTS_ENV]!r})."
                    )
                run = step.get("run")
                if run and run_body_names_addopts(str(run)):
                    found.append(
                        f"{relative} job {job_name!r} step {label!r} names "
                        f"{ADDOPTS_ENV} in its run body. Any mention is refused: "
                        f"`echo \"{ADDOPTS_ENV}=...\" >> \"$GITHUB_ENV\"` sets the "
                        "variable for every LATER step in the job, which is how a "
                        "single line in an install step silently disarms the "
                        "accuracy gate that follows it."
                    )
    return found


def problems(root: Path, environ: Mapping[str, str] | None = None) -> list[str]:
    """Every reason to refuse, as operator-readable lines. Empty means clean.

    ``environ`` defaults to ``os.environ`` deliberately — the CI step passes
    nothing, so a default of ``{}`` would silently drop the runtime arm while every
    test that passes ``environ=`` explicitly kept passing. Pinned by
    ``test_problems_reads_the_real_environment_when_none_is_passed``.
    """
    if environ is None:
        environ = os.environ

    found: list[str] = []

    narrowing_env = narrowing_env_addopts(environ)
    if narrowing_env:
        found.append(
            f"{ADDOPTS_ENV} is set in this process's environment to "
            f"{environ.get(ADDOPTS_ENV)!r}, carrying narrowing flag(s) "
            f"{narrowing_env}.\n"
            f"  pytest reads arguments from that variable, so every pytest run in "
            f"this job — including the accuracy gate — loses assertions without a "
            f"single visible change to its run line.\n"
            f"  Measured: with {ADDOPTS_ENV}='--collect-only', `pytest tests/ -q` "
            f"collects 912 tests, executes NONE, and exits 0 with "
            f"REQUIRE_SWISS_EPHEMERIS=1 still set — fixtures do not run during "
            f"collection, so the fail-closed flag never evaluates.\n"
            f"  If pytest arguments are genuinely needed, put them on the run line "
            f"of the job that needs them, where the diff shows them."
        )

    found.extend(workflow_addopts_declarations(root))

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        document = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        tokens = addopts_tokens(document)
        narrowing = narrowing_addopts(tokens)
        if narrowing:
            found.append(
                f"pyproject.toml [tool.pytest.ini_options] addopts carries narrowing "
                f"flag(s) {narrowing} (parsed as {tokens}).\n"
                f"  That applies to EVERY pytest invocation in this repo — including "
                f"the swiss-ephemeris accuracy job — so it removes assertions from the "
                f"suite without touching a single workflow file.\n"
                f"  If tests genuinely need to be excluded, exclude them on the run "
                f"line of the specific job that needs it, where the diff shows it and "
                f"ci/tests/test_swiss_ephemeris_job.py can see it."
            )

    for name in unparsed_config_files(root):
        found.append(
            f"{name} exists, and pytest reads `addopts` from it. Only the ROOT "
            f"pyproject.toml is parsed here, so this check would report clean "
            f"while a narrowing addopts sat in a file nothing opens.\n"
            f"  pytest resolves its inifile by walking UP from the common ancestor "
            f"of its arguments, so a config file inside a directory the suite is "
            f"invoked against (tests/, ci/tests/) WINS over the root pyproject.toml "
            f"— it does not merely coexist with it.\n"
            f"  Measured: `tests/pytest.ini` holding `addopts = --collect-only` left "
            f"this checker exiting 0 \"OK\" while `pytest tests/ -q` collected 937 "
            f"tests and executed none, also exiting 0.\n"
            f"  If {name} is genuinely needed, extend addopts_tokens() and "
            f"is_unparsed_config_path() to parse it — deliberately, in a change that "
            f"says so."
        )

    return found


def _self_test() -> int:
    """Prove the checker still discriminates before it certifies the real repo.

    Same ordering rule as ci/fetch_swiss_ephemeris.py --self-test: a verifier that
    has stopped verifying must never get as far as certifying the real thing.
    """
    narrowing_fixtures = (
        '[tool.pytest.ini_options]\naddopts = "-k not_corpus"\n',
        "[tool.pytest.ini_options]\naddopts = \"-k 'not corpus'\"\n",
        "[tool.pytest.ini_options]\naddopts = \"-m 'not accuracy'\"\n",
        '[tool.pytest.ini_options]\naddopts = "--collect-only"\n',
        '[tool.pytest.ini_options]\naddopts = "--co"\n',
        '[tool.pytest.ini_options]\naddopts = "--ignore=tests/test_swiss_ephemeris.py"\n',
        '[tool.pytest.ini_options]\naddopts = ["-q", "--deselect", "tests/x.py"]\n',
        '[tool.pytest.ini_options]\naddopts = ["-k not_corpus"]\n',
    )
    clean_fixtures = (
        "",
        "[tool.pytest.ini_options]\n",
        '[tool.pytest.ini_options]\naddopts = "-q --strict-markers"\n',
        '[tool.pytest.ini_options]\naddopts = ["-q", "--color=no"]\n',
        '[tool.pytest.ini_options]\n# addopts = "-k not_corpus"\n',
        '[tool.pytest.ini_options]\nmarkers = ["accuracy: needs swiss data"]\n',
    )

    # The runtime-environment arm. Neutering `narrowing_env_addopts` must red here,
    # or the CI step's `--self-test` proves nothing about the arm that catches an
    # injected workflow-level `env:` block.
    env_narrowing = ("--collect-only", "--co", "-k not_corpus", "-m 'not accuracy'",
                     "--ignore=tests/test_swiss_ephemeris.py")
    env_clean = ("", "-q", "--color=no", "-q --strict-markers")

    # The run-body arm. `$GITHUB_ENV` forms come FIRST because they are the ones
    # that persist across steps — and the ones the previous, tokenising version of
    # this check let through.
    inline_declaring = (
        'echo "PYTEST_ADDOPTS=--collect-only" >> "$GITHUB_ENV"',
        "echo PYTEST_ADDOPTS=--co >> $GITHUB_ENV",
        'printf "PYTEST_ADDOPTS=%s" --collect-only >> "$GITHUB_ENV"',
        'PYTEST_ADDOPTS="--collect-only" pytest tests/ -q',
        "export PYTEST_ADDOPTS=-k nothing",
        "REQUIRE_SWISS_EPHEMERIS=1 PYTEST_ADDOPTS=--co pytest tests/",
        # A bare mention, no assignment: still refused. Presence, not semantics.
        'echo "PYTEST_ADDOPTS"',
    )
    inline_clean = (
        "pytest tests/ -q",
        "python ci/check_pytest_collection.py",
        "uv sync --frozen --extra dev\nuv run --frozen pytest tests/ -q",
        'echo "REQUIRE_SWISS_EPHEMERIS=1" >> "$GITHUB_ENV"',
    )

    # The whole-tree config-file arm. Path classification only — the scan around
    # it needs a filesystem, but the decision it turns on does not, and neutering
    # this must red here rather than only in ci/tests/.
    config_paths_refused = (
        "pytest.ini",
        ".pytest.ini",
        "tox.ini",
        "setup.cfg",
        "tests/pytest.ini",
        "ci/tests/tox.ini",
        "a/b/c/setup.cfg",
        "tests/.pytest.ini",
        # A nested pyproject.toml is a candidate; content decides (see
        # _declares_pytest_ini_options), and the path arm must surface it.
        "tests/pyproject.toml",
    )
    config_paths_clean = (
        # The ROOT pyproject.toml is the one this checker parses.
        "pyproject.toml",
        "README.md",
        "tests/conftest.py",
        "ci/check_pytest_collection.py",
        "tests/goldens/swiss_ephemeris_goldens.json",
        # Names that merely CONTAIN a config filename are not config files.
        "docs/pytest.ini.md",
        "tests/setup.cfg.bak",
    )

    failures: list[str] = []
    for text in narrowing_fixtures:
        if not narrowing_addopts(addopts_tokens(tomllib.loads(text))):
            failures.append(f"NOT DETECTED as narrowing: {text!r}")
    for text in clean_fixtures:
        if narrowing_addopts(addopts_tokens(tomllib.loads(text))):
            failures.append(f"FALSELY flagged as narrowing: {text!r}")

    for value in env_narrowing:
        if not narrowing_env_addopts({ADDOPTS_ENV: value}):
            failures.append(f"NOT DETECTED as a narrowing {ADDOPTS_ENV}: {value!r}")
    for value in env_clean:
        if narrowing_env_addopts({ADDOPTS_ENV: value}):
            failures.append(f"FALSELY flagged as a narrowing {ADDOPTS_ENV}: {value!r}")

    for run in inline_declaring:
        if not run_body_names_addopts(run):
            failures.append(f"NOT DETECTED as a run body naming {ADDOPTS_ENV}: {run!r}")
    for run in inline_clean:
        if run_body_names_addopts(run):
            failures.append(f"FALSELY flagged as naming {ADDOPTS_ENV}: {run!r}")

    for relative in config_paths_refused:
        if not is_unparsed_config_path(relative):
            failures.append(f"NOT DETECTED as an unparsed pytest config path: {relative!r}")
    for relative in config_paths_clean:
        if is_unparsed_config_path(relative):
            failures.append(f"FALSELY flagged as an unparsed pytest config path: {relative!r}")

    if failures:
        print("self-test FAILED:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    total = (
        len(narrowing_fixtures) + len(clean_fixtures)
        + len(env_narrowing) + len(env_clean)
        + len(inline_declaring) + len(inline_clean)
        + len(config_paths_refused) + len(config_paths_clean)
    )
    print(
        f"self-test OK ({total} fixtures discriminated across four arms: "
        f"{len(narrowing_fixtures)}+{len(clean_fixtures)} pyproject addopts, "
        f"{len(env_narrowing)}+{len(env_clean)} runtime {ADDOPTS_ENV}, "
        f"{len(inline_declaring)}+{len(inline_clean)} run-body mention, "
        f"{len(config_paths_refused)}+{len(config_paths_clean)} unparsed config path)"
    )
    return 0


def main(argv: list[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refuse a narrowing pytest configuration.")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="prove the detector still discriminates; check nothing real",
    )
    arguments = parser.parse_args(argv)

    if environ is None:
        environ = os.environ

    if arguments.self_test:
        # The self-test runs BEFORE the real check in CI, so an injected
        # PYTEST_ADDOPTS must stop it here rather than let it certify a detector
        # and only then fail. Checked first for that reason.
        narrowing_env = narrowing_env_addopts(environ)
        if narrowing_env:
            print(
                f"self-test REFUSED: {ADDOPTS_ENV}={environ.get(ADDOPTS_ENV)!r} is set "
                f"in this environment and carries narrowing flag(s) {narrowing_env}. "
                "Refusing to certify anything from inside an already-narrowed "
                "environment.",
                file=sys.stderr,
            )
            return 1
        return _self_test()

    found = problems(REPO_ROOT, environ=environ)
    if found:
        print(
            "REFUSED: this repository's pytest configuration removes tests from every "
            "run.\n",
            file=sys.stderr,
        )
        for problem in found:
            print(f"  * {problem}\n", file=sys.stderr)
        return 1

    print("OK: pytest configuration does not narrow collection.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
