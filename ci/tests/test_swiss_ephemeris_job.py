"""Regression guard: CI keeps actually running the suite against real Swiss data (CALC-1).

``tests/test_swiss_ephemeris.py`` SKIPS when no ephemeris data files are present —
deliberately, because the fast ``test`` job and the default local loop genuinely have
none. That skip is only safe because one CI job does supply the data and sets
``REQUIRE_SWISS_EPHEMERIS=1``, which converts the skip into a hard failure.

Delete that job, drop its fetch step, or lose that env var, and the accuracy tests
quietly become three permanent skips while the workflow still looks like it covers
them. That is the fail-open shape this file exists to prevent — the same class of
defect as the "docker-test-image only BUILDS the test image, it never runs the suite
against real data" gap that made CALC-1 look closed when it was not.

WHY A PARSER, NOT A LINE-SCAN
-----------------------------
``grep REQUIRE_SWISS_EPHEMERIS .github/workflows/test.yml`` matches the string in a
comment, in a commented-out step, in another job's ``run:`` body, or in this very
file's name — none of which means the job sets it. PyYAML resolves the workflow to a
data structure in which a comment cannot exist, so every assertion below is about
structure: a job exists, its steps include one whose ``run`` invokes the fetcher, and
its pytest step's ``env`` mapping carries the flag. ``test_parser_discriminates``
feeds that logic the fixtures a textual scanner gets wrong, and the real assertions
re-invoke it so an unproven parser can never certify the workflow green.

STRUCTURAL BACKSTOP (round 4). Three rounds of review each found a NEW way to
silently disable the job/workflow that the semantic checks above did not
model. Reimplementing GitHub Actions' full `if:`/trigger-filter semantics is
an unbounded surface, so this file also carries a snapshot assertion (see
the module-level comment above ``test_swiss_job_enablement_snapshot_matches_committed_shape``,
near the end of this file) over the raw enablement-relevant shape of the
workflow. The semantic checks are the diagnostics -- they give a precise
reason a specific `if:`/filter form is wrong; the snapshot is the backstop --
it catches any change to that shape, known or not, without evaluating
anything. Keep both; neither is redundant with the other.
"""
from __future__ import annotations

import fnmatch
import re
import subprocess
import tomllib
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_TEST_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "test.yml"


def _load_ci_module(name: str):
    """Import a ``ci/*.py`` script by path.

    ``ci/`` has no ``__init__.py`` by design, and CI runs the bare
    ``pytest ci/tests/ -q`` console script, which does not put the CWD on
    ``sys.path`` (see CLAUDE.md) — so ``from ci import ...`` is not available.
    Same importlib form as ci/tests/test_reference_corpus_fetcher.py.
    """
    import importlib.util

    path = _REPO_ROOT / "ci" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_workflow_scope = _load_ci_module("workflow_scope")

_JOB = "swiss-ephemeris"
_FLAG = "REQUIRE_SWISS_EPHEMERIS"
_FETCHER = "ci/fetch_swiss_ephemeris.py"
_WORKFLOW_RELATIVE_PATH = _TEST_WORKFLOW.relative_to(_REPO_ROOT).as_posix()
# This repo's default branch (confirmed live, not assumed) -- the branch a
# real push/PR targets. If it ever changes, update this alongside it.
_DEFAULT_BRANCH = "main"


# ---------------------------------------------------------------------------
# Structural helpers — take a PARSED document, never raw text
# ---------------------------------------------------------------------------


def _job(document: dict, name: str) -> dict | None:
    jobs = document.get("jobs") or {}
    job = jobs.get(name)
    return job if isinstance(job, dict) else None


def _workflow_triggers(document: dict) -> dict:
    """The workflow's ``on:`` mapping.

    PyYAML's default (YAML 1.1) resolver reads the unquoted key ``on`` as the
    boolean ``True``, not the string ``"on"`` -- a well-known gotcha specific to
    GitHub Actions workflow YAML. ``document.get("on")`` is silently ``None`` on
    every real workflow file for this reason. Check both spellings so this
    guard doesn't mistake that parser quirk for "no triggers declared".
    """
    triggers = document.get("on")
    if triggers is None:
        triggers = document.get(True)
    return triggers if isinstance(triggers, dict) else {}


class _UnverifiedFilterShape(ValueError):
    """Raised when a `paths`/`paths-ignore`/`branches`/`branches-ignore` value
    is present but is not a list (e.g. a bare scalar string).

    Whether GitHub Actions even accepts a scalar there -- and if so, whether
    it treats it as a single-element list or something else -- could not be
    verified without pushing to a real repository (round 4, non-blocking
    item 3). Rather than guess and silently treat it as "no filter" (which
    was the previous, permissive behaviour), this guard fails closed: an
    unverified shape can never certify enablement.
    """


def _glob_matches_any(patterns: object, value: str) -> bool:
    """True when ``value`` is matched under GitHub's own filter algorithm.

    Not a re-implementation of GitHub's full path/branch matcher (which has
    its own `**`/`?` semantics) -- ``fnmatch`` is close enough for the cases
    this guard cares about, PROVIDED negation is handled the way GHA actually
    handles it: patterns are evaluated in order and the LAST pattern that
    matches ``value`` decides the outcome, with a `!`-prefixed pattern
    excluding on match rather than including. ``fnmatch`` alone has no such
    concept and would treat each pattern in isolation -- exactly why
    `paths: ["**", "!**"]` or `branches: ["**", "!main"]` used to be
    completely invisible to this guard despite fully disabling the workflow
    (round 4, finding 3). A missing key (`patterns is None`) means "no
    filter" and matches nothing; a *present* non-list value is a shape this
    guard cannot verify GHA's handling of, so it fails closed rather than
    silently treating it as "no filter" (round 4, non-blocking item 3).
    """
    if patterns is None:
        return False
    if not isinstance(patterns, list):
        raise _UnverifiedFilterShape(
            f"filter value is not a list of glob patterns: {patterns!r}"
        )
    matched = False
    for pattern in patterns:
        pattern = str(pattern)
        negated = pattern.startswith("!")
        glob = pattern[1:] if negated else pattern
        if fnmatch.fnmatch(value, glob):
            matched = not negated
    return matched


def _paths_filter_excludes_own_workflow(trigger_body: object) -> bool:
    """True when this trigger's `paths`/`paths-ignore` filter would stop a push
    that touches ONLY the workflow file itself (``_WORKFLOW_RELATIVE_PATH``)
    from firing the trigger.

    `paths-ignore: ["**"]` is the fixture this exists to catch (round 3,
    finding 1b): it matches every path, so the job can never run on any push
    -- including one that edits this very file to re-enable it. A `paths:`
    allowlist that never matches the workflow's own path is symmetric: it
    means editing the workflow can never itself re-trigger the job either.
    """
    if not isinstance(trigger_body, dict):
        return False
    if _glob_matches_any(trigger_body.get("paths-ignore"), _WORKFLOW_RELATIVE_PATH):
        return True
    paths = trigger_body.get("paths")
    if paths is not None and not _glob_matches_any(paths, _WORKFLOW_RELATIVE_PATH):
        return True
    return False


def _branches_filter_excludes_default_branch(trigger_body: object) -> bool:
    """True when this trigger's `branches`/`branches-ignore` filter would stop
    a push to the repo's real default branch (``_DEFAULT_BRANCH``) from firing.

    `branches: ["no-such-branch-xyz"]` is the fixture this exists to catch
    (round 3, finding 1b): the key is present, so a presence-only check stays
    green, but no real push/PR against the default branch would ever satisfy it.
    """
    if not isinstance(trigger_body, dict):
        return False
    if _glob_matches_any(trigger_body.get("branches-ignore"), _DEFAULT_BRANCH):
        return True
    branches = trigger_body.get("branches")
    if branches is not None and not _glob_matches_any(branches, _DEFAULT_BRANCH):
        return True
    return False


def _steps(job: dict) -> list[dict]:
    return [step for step in (job.get("steps") or []) if isinstance(step, dict)]


def _runs(job: dict) -> list[str]:
    return [str(step["run"]) for step in _steps(job) if "run" in step]


# Tokenising lives in ci/check_pytest_collection.py — the plain-python checker that
# must analyse the same run bodies from OUTSIDE pytest. One definition, two readers:
# a second copy here would drift, and the copy that stopped handling a form would be
# the one nobody re-read. The behaviour these names carry is pinned by
# test_commands_joins_shell_line_continuations below, which exercises the imported
# implementation directly.
_COLLECTION_CHECKER = _load_ci_module("check_pytest_collection")
_join_shell_continuations = _COLLECTION_CHECKER.join_shell_continuations
_commands = _COLLECTION_CHECKER.shell_commands
_run_body_names_addopts = _COLLECTION_CHECKER.run_body_names_addopts


def _invokes(run: str, program: str, *required_tokens: str) -> bool:
    """True when some command in ``run`` has ``program`` and all required tokens as ARGV tokens."""
    for tokens in _commands(run):
        if program not in tokens:
            continue
        if all(any(required in token for token in tokens) for required in required_tokens):
            return True
    return False


def _has_token_sequence(run: str, *sequence: str) -> bool:
    """True when some command contains the given consecutive argv tokens (e.g. `uv sync --frozen`)."""
    width = len(sequence)
    for tokens in _commands(run):
        for index in range(len(tokens) - width + 1):
            if tuple(tokens[index : index + width]) == sequence:
                return True
    return False


def _job_invokes_fetcher(job: dict) -> bool:
    return any(_invokes(run, "python", _FETCHER) for run in _runs(job))


def _job_self_tests_fetcher(job: dict) -> bool:
    return any(_invokes(run, "python", _FETCHER, "--self-test") for run in _runs(job))


def _uses(job: dict) -> list[str]:
    return [str(step["uses"]) for step in _steps(job) if "uses" in step]


# ---------------------------------------------------------------------------
# Enablement — does the job actually RUN, or can its `if:` skip it entirely?
#
# Every check above inspects the job's CONTENTS (its steps, their env, the
# cache key, ...). None of them notice if the job itself never runs: add
# `if: false` to the job and every one of them keeps passing, because the
# steps they inspect are still correctly written — they simply never
# execute. That is the exact fail-open shape this whole file exists to
# prevent, one level up. The checks below parse and evaluate the job's `if:`
# condition instead of grepping for it, for the same reason the rest of this
# file parses rather than scans: `if: 'false'` inside a comment, or the
# string "false" inside an unrelated step, must not be mistaken for the
# job's real condition.
# ---------------------------------------------------------------------------


class _UnsupportedExpression(ValueError):
    """Raised when a job's or step's `if:` uses syntax this mini-evaluator does
    not model.

    The caller must treat this as "cannot prove the job/step is enabled" and
    fail the test — never silently assume it runs just because its condition
    could not be evaluated.
    """


_EXPR_TOKEN_RE = re.compile(
    r"""\s*(?:(?P<op>==|!=|&&|\|\||!|\(|\))|(?P<str>'[^']*'|"[^"]*")|(?P<ident>[A-Za-z_][A-Za-z0-9_.]*))"""
)


def _to_number(value: bool | str) -> float:
    """GitHub Actions' number-coercion table for a comparison between
    mismatched types: Boolean -> 1.0/0.0, String -> parsed as a JSON number,
    otherwise NaN (an empty string is 0). See
    https://docs.github.com/actions/reference/evaluate-expressions-in-workflows-and-actions
    """
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if value == "":
        return 0.0
    try:
        return float(value)
    except ValueError:
        return float("nan")


def _loose_equals(lhs: bool | str, rhs: bool | str) -> bool | None:
    """GitHub Actions' `==` semantics: same-type operands compare directly;
    differently-typed operands are both coerced to numbers first (see
    `_to_number`). Returns None when that coercion makes either side NaN --
    GHA documents a NaN operand as always `false` for the relational
    operators, and round 4 finding 2's reproduced cases show the same holds
    for `==` *and* `!=`: a NaN operand makes BOTH evaluate to `false`, not
    just `==`. The caller is responsible for turning that `None` into
    `False` regardless of which operator (`==`/`!=`) is being evaluated.
    """
    if type(lhs) is type(rhs):
        return lhs == rhs
    lhs_num, rhs_num = _to_number(lhs), _to_number(rhs)
    if lhs_num != lhs_num or rhs_num != rhs_num:  # NaN is never equal to itself
        return None
    return lhs_num == rhs_num


def _tokenize_expression(expr: str) -> list[str]:
    tokens: list[str] = []
    pos = 0
    while pos < len(expr):
        match = _EXPR_TOKEN_RE.match(expr, pos)
        if not match or match.end() == pos:
            if expr[pos:].strip() == "":
                break
            raise _UnsupportedExpression(f"cannot tokenize {expr[pos:]!r} in {expr!r}")
        pos = match.end()
        token = match.group("op") or match.group("str") or match.group("ident")
        tokens.append(token)
    return tokens


class _ExpressionParser:
    """Recursive-descent evaluator for a deliberately small subset of GitHub
    Actions `if:` expression syntax: `==`, `!=`, `&&`, `||`, `!`, parens, quoted
    string literals, bare `true`/`false`, and the single context reference
    `github.event_name` (substituted with the event name under test). Anything
    else — a function call, a different context, a matrix reference — raises
    _UnsupportedExpression rather than guessing a truth value.

    OPERATOR PRECEDENCE (round 3, finding 1a). GitHub Actions' documented order
    of evaluation, highest-binding first, is:

        1. ()                  grouping
        2. !                   logical NOT (unary)
        3. <  <=  >  >=        relational          (NOT supported here)
        4. ==  !=              equality
        5. &&                  logical AND
        6. ||                  logical OR

    So `!` binds to the single operand right after it, TIGHTER than `==`/`!=`:
    `!github.event_name == 'schedule'` is `(!github.event_name) == 'schedule'`,
    NOT `!(github.event_name == 'schedule')`. A round-1/round-2 version of this
    evaluator applied `!` above comparison (between `_and_expr` and comparison),
    which silently inverted every un-parenthesized `!x == y` condition — see
    the mutation fixtures in `test_enablement_parser_discriminates` for the
    concrete case this broke. The grammar below encodes the table above
    directly: `_or_expr` wraps `_and_expr` wraps `_comparison` wraps `_unary`
    wraps `_primary`, so `!` (in `_unary`) sits strictly BELOW `==`/`!=` (in
    `_comparison`) and can only ever bind to the primary right next to it.

    PAREN GROUPING MUST NOT CHANGE A VALUE'S TYPE (round 4, finding 2). GitHub
    Actions parens are pure grouping. A round-2/round-3 version of `_primary`'s
    paren branch returned `self._or_expr()`, which funnelled through
    `_comparison`'s bare-operand fallback -- and that fallback used to return
    `bool(lhs)` unconditionally, so `(github.event_name)` became the Python
    bool `True` instead of the string `'push'`. Any later comparison against
    that parenthesised value then compared against an already-mangled type
    and guessed wrong in both directions: `(github.event_name) == true`
    reported the job enabled (comparing `True == True`) when GHA's own
    type-coercion table (string -> NaN, boolean -> 1/0, NaN never equal to
    anything) makes it `false` for every event; `(github.event_name) ==
    'push'` reported disabled (comparing `True == 'push'`) when a real push
    event makes it `true`. `_comparison` below now returns its bare operand
    completely unchanged when no `==`/`!=` follows, so a parenthesised value
    keeps its real type all the way up; `bool()` is applied only where GHA
    itself requires a boolean -- combining two operands with `&&`/`||`, `!`'s
    negation, and the final result of `parse()`.
    """

    def __init__(self, tokens: list[str], event_name: str) -> None:
        self._tokens = tokens
        self._pos = 0
        self._event_name = event_name

    def parse(self) -> bool:
        value = self._or_expr()
        if self._pos != len(self._tokens):
            raise _UnsupportedExpression(f"unconsumed tokens: {self._tokens[self._pos:]}")
        return bool(value)

    def _peek(self) -> str | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _advance(self) -> str:
        token = self._peek()
        if token is None:
            raise _UnsupportedExpression("unexpected end of expression")
        self._pos += 1
        return token

    def _or_expr(self) -> bool | str:
        value = self._and_expr()
        while self._peek() == "||":
            self._advance()
            value = bool(self._and_expr()) or bool(value)
        return value

    def _and_expr(self) -> bool | str:
        value = self._comparison()
        while self._peek() == "&&":
            self._advance()
            value = bool(self._comparison()) and bool(value)
        return value

    def _comparison(self) -> bool | str:
        """`==`/`!=`, or the bare operand unchanged when neither follows.

        Round 4, finding 2: this used to `return bool(lhs)` on the no-operator
        path, which is what silently mangled every parenthesised value's type
        (see the class docstring). It must return `lhs` exactly as received --
        a genuine boolean is only produced here when an actual `==`/`!=`
        comparison was evaluated.
        """
        lhs = self._unary()
        if self._peek() in ("==", "!="):
            op = self._advance()
            rhs = self._unary()
            equal = _loose_equals(lhs, rhs)
            if equal is None:
                # A NaN-producing type coercion: GHA's documented rule for the
                # relational operators ("NaN is never equal, even to itself")
                # holds here too, for BOTH `==` and `!=` -- see `_loose_equals`.
                return False
            return equal if op == "==" else not equal
        return lhs

    def _unary(self):
        """`!`, unary — binds tighter than `==`/`!=` (see class docstring), so
        it wraps only the single primary/parenthesised operand right after it,
        never a whole comparison."""
        if self._peek() == "!":
            self._advance()
            return not self._unary()
        return self._primary()

    def _primary(self):
        if self._peek() == "(":
            self._advance()
            value = self._or_expr()
            if self._advance() != ")":
                raise _UnsupportedExpression("expected closing ')'")
            return value
        token = self._advance()
        if token.startswith("'") or token.startswith('"'):
            return token[1:-1]
        if token == "true":
            return True
        if token == "false":
            return False
        if token == "github.event_name":
            return self._event_name
        raise _UnsupportedExpression(f"unsupported identifier or context ref: {token!r}")


def _evaluate_gha_if(expr: str, event_name: str) -> bool:
    return _ExpressionParser(_tokenize_expression(expr), event_name).parse()


def _condition(mapping: dict) -> bool | str | None:
    """A job's or step's raw `if:` value: a bool if YAML parsed a bare
    literal, the unwrapped expression string otherwise, or None if there is
    no `if:` at all (which means it always runs).

    GitHub Actions' `if:` grammar is identical for jobs and steps, so this
    reads either mapping the same way (round 4, finding 1 -- the step-level
    guard reuses this rather than duplicating it)."""
    if "if" not in mapping:
        return None
    value = mapping["if"]
    if isinstance(value, bool):
        return value
    text = str(value).strip()
    if text.startswith("${{") and text.endswith("}}"):
        text = text[3:-2].strip()
    return text


def _runs_for_event(mapping: dict, event_name: str) -> bool:
    """Whether the job's or step's `if:` (if any) lets it run for the given
    event.

    Raises _UnsupportedExpression when the condition cannot be evaluated by this
    guard's supported subset — the caller must fail the test on that, not treat
    it as "probably fine".
    """
    condition = _condition(mapping)
    if condition is None:
        return True
    if isinstance(condition, bool):
        return condition
    return _evaluate_gha_if(condition, event_name)


def _step_env_flag_values(job: dict, flag: str) -> list[str]:
    """Every value the given env key takes across the job's steps and job-level env."""
    values: list[str] = []
    job_env = job.get("env")
    if isinstance(job_env, dict) and flag in job_env:
        values.append(str(job_env[flag]))
    for step in _steps(job):
        env = step.get("env")
        if isinstance(env, dict) and flag in env:
            values.append(str(env[flag]))
    return values


def _runs_the_test_suite(run: str) -> bool:
    """True when a command in ``run`` really invokes pytest over the tests/ tree."""
    for tokens in _commands(run):
        if "pytest" not in tokens:
            continue
        if any(token == "tests" or token.startswith("tests/") or token.startswith("tests\\") for token in tokens):
            return True
    return False


def _suite_step(job: dict) -> dict | None:
    """The step that invokes pytest over tests/ WITH the flag=1 in scope, if
    any -- a step must BOTH invoke pytest over tests/ AND carry the flag=1 in
    scope to count.

    Returning the step itself (not just a bool) is what round 4, finding 1's
    step-level enablement check needs: the job's `if:` being fine says
    nothing about whether GHA would actually reach the step that runs the
    suite (see test_swiss_job_suite_step_is_not_conditionally_skipped)."""
    job_env = job.get("env")
    job_level = isinstance(job_env, dict) and str(job_env.get(_FLAG)) == "1"
    for step in _steps(job):
        run = step.get("run")
        if not run or not _runs_the_test_suite(str(run)):
            continue
        env = step.get("env")
        step_level = isinstance(env, dict) and str(env.get(_FLAG)) == "1"
        # Also accept the inline `FLAG=1 pytest ...` shell form — as an argv token,
        # so the same string inside a quoted echo argument does not count.
        inline = any(f"{_FLAG}=1" in tokens for tokens in _commands(str(run)))
        if job_level or step_level or inline:
            return step
    return None


def _runs_the_suite_with_the_flag(job: dict) -> bool:
    """A step must BOTH invoke pytest over tests/ AND carry the flag=1 in scope."""
    return _suite_step(job) is not None


# ---------------------------------------------------------------------------
# Discrimination fixtures — inputs a grep over the raw YAML gets WRONG
# ---------------------------------------------------------------------------

_FIXTURE_GOOD = """
jobs:
  swiss-ephemeris:
    steps:
      - run: python ci/fetch_swiss_ephemeris.py
      - env:
          REQUIRE_SWISS_EPHEMERIS: "1"
        run: pytest tests/ -q
"""

_FIXTURE_GOOD_INLINE = """
jobs:
  swiss-ephemeris:
    steps:
      - run: python ci/fetch_swiss_ephemeris.py
      - run: REQUIRE_SWISS_EPHEMERIS=1 pytest tests/ -q
"""

_FIXTURE_GOOD_JOB_LEVEL_ENV = """
jobs:
  swiss-ephemeris:
    env:
      REQUIRE_SWISS_EPHEMERIS: "1"
    steps:
      - run: python ci/fetch_swiss_ephemeris.py
      - run: pytest tests/ -q
"""

_FIXTURE_FLAG_ONLY_IN_A_COMMENT = """
jobs:
  swiss-ephemeris:
    steps:
      - run: python ci/fetch_swiss_ephemeris.py
      # REQUIRE_SWISS_EPHEMERIS: "1"
      - run: pytest tests/ -q
"""

_FIXTURE_STEP_COMMENTED_OUT = """
jobs:
  swiss-ephemeris:
    steps:
      - run: python ci/fetch_swiss_ephemeris.py
      # - env:
      #     REQUIRE_SWISS_EPHEMERIS: "1"
      #   run: pytest tests/ -q
"""

_FIXTURE_FLAG_SET_BUT_SUITE_NOT_RUN = """
jobs:
  swiss-ephemeris:
    env:
      REQUIRE_SWISS_EPHEMERIS: "1"
    steps:
      - run: python ci/fetch_swiss_ephemeris.py
      - run: echo "pytest tests/ would go here"
"""

_FIXTURE_FLAG_ZERO = """
jobs:
  swiss-ephemeris:
    steps:
      - run: python ci/fetch_swiss_ephemeris.py
      - env:
          REQUIRE_SWISS_EPHEMERIS: "0"
        run: pytest tests/ -q
"""

_FIXTURE_SUITE_ONLY_ECHOED = """
jobs:
  swiss-ephemeris:
    env:
      REQUIRE_SWISS_EPHEMERIS: "1"
    steps:
      - run: python ci/fetch_swiss_ephemeris.py
      - run: echo "pytest tests/ -q"
"""

_FIXTURE_SUITE_IN_ANOTHER_JOB = """
jobs:
  swiss-ephemeris:
    steps:
      - run: python ci/fetch_swiss_ephemeris.py
  other:
    steps:
      - env:
          REQUIRE_SWISS_EPHEMERIS: "1"
        run: pytest tests/ -q
"""


def test_parser_discriminates() -> None:
    """Every fixture below is something a textual scan of the YAML gets wrong."""

    def check(text: str) -> bool:
        job = _job(yaml.safe_load(text), _JOB)
        assert job is not None, "fixture is missing the job itself"
        return _runs_the_suite_with_the_flag(job)

    # Accepted forms — all three are genuinely correct wiring.
    assert check(_FIXTURE_GOOD) is True
    assert check(_FIXTURE_GOOD_INLINE) is True
    assert check(_FIXTURE_GOOD_JOB_LEVEL_ENV) is True

    # Rejected forms — each contains the literal flag string, none of them runs the
    # suite with it in effect.
    assert check(_FIXTURE_FLAG_ONLY_IN_A_COMMENT) is False
    assert check(_FIXTURE_STEP_COMMENTED_OUT) is False
    assert check(_FIXTURE_FLAG_SET_BUT_SUITE_NOT_RUN) is False
    assert check(_FIXTURE_SUITE_ONLY_ECHOED) is False
    assert check(_FIXTURE_FLAG_ZERO) is False
    assert check(_FIXTURE_SUITE_IN_ANOTHER_JOB) is False

    # And the fetcher-step detection must be equally structural: neither a
    # commented-out step nor an echoed mention counts as running the fetcher.
    for decoy in (
        """
jobs:
  swiss-ephemeris:
    steps:
      # - run: python ci/fetch_swiss_ephemeris.py
      - run: pytest tests/ -q
""",
        """
jobs:
  swiss-ephemeris:
    steps:
      - run: echo "run python ci/fetch_swiss_ephemeris.py first"
      - run: pytest tests/ -q
""",
    ):
        job = _job(yaml.safe_load(decoy), _JOB)
        assert job is not None
        assert not _job_invokes_fetcher(job), "a decoy fetcher mention was accepted"
        assert not _job_self_tests_fetcher(job), "a decoy --self-test mention was accepted"

    # A real invocation in any of its plausible spellings must be accepted.
    for real in (
        """
jobs:
  swiss-ephemeris:
    steps:
      - run: python ci/fetch_swiss_ephemeris.py
      - run: python ci/fetch_swiss_ephemeris.py --self-test
"""
    ,
        """
jobs:
  swiss-ephemeris:
    steps:
      - run: |
          python ci/fetch_swiss_ephemeris.py --self-test
          python ci/fetch_swiss_ephemeris.py
""",
    ):
        job = _job(yaml.safe_load(real), _JOB)
        assert job is not None
        assert _job_invokes_fetcher(job), "a real fetcher invocation was rejected"
        assert _job_self_tests_fetcher(job), "a real --self-test invocation was rejected"

    # `uv sync --frozen` must be a consecutive argv sequence, not a substring.
    assert _has_token_sequence("uv sync --frozen --extra dev", "uv", "sync", "--frozen")
    assert not _has_token_sequence('echo "uv sync --frozen"', "uv", "sync", "--frozen")


def test_commands_joins_shell_line_continuations() -> None:
    """A backslash-continued command is ONE command, exactly as a shell reads it.

    Without this, `shlex.split` raises "No escaped character" on the line ending in
    a lone backslash, `_commands` treats that line as opaque and drops it, and the
    continuation lines that follow are parsed as commands in their own right. Every
    consumer of `_commands` is wrong at once: `_invokes` stops finding the fetcher,
    `_has_token_sequence` stops finding `uv sync --frozen`, and `_pytest_targets`
    returns [] so the reachability guard reds on a correctly-wired workflow.
    """
    continued = (
        "uv run --frozen python -m pytest tests/test_swiss_ephemeris.py \\\n"
        "  tests/test_independent_reference_corpus.py -q"
    )
    assert _commands(continued) == [
        [
            "uv", "run", "--frozen", "python", "-m", "pytest",
            "tests/test_swiss_ephemeris.py",
            "tests/test_independent_reference_corpus.py",
            "-q",
        ]
    ]
    assert _pytest_targets(continued) == [
        "tests/test_swiss_ephemeris.py",
        "tests/test_independent_reference_corpus.py",
    ]

    # The other consumers of `_commands`, on continued bodies of their own.
    assert _invokes("python ci/fetch_swiss_ephemeris.py \\\n  --self-test", "python",
                    _FETCHER, "--self-test")
    assert _has_token_sequence("uv sync \\\n  --frozen --extra dev", "uv", "sync", "--frozen")

    # A narrowing flag on the continuation line must still be found.
    assert _narrowing_flags(
        "pytest tests/ -q \\\n  --ignore=tests/test_independent_reference_corpus.py"
    ) == ["--ignore"]

    # An EVEN number of trailing backslashes is an escaped backslash, NOT a
    # continuation: the two lines stay two separate commands.
    not_continued = 'echo "a" \\\\\npytest tests/ -q'
    assert len(_commands(not_continued)) == 2, _commands(not_continued)
    assert _pytest_targets(not_continued) == ["tests/"]

    # A dangling continuation at the very end must not swallow the command.
    assert _commands("pytest tests/ -q \\\n") == [["pytest", "tests/", "-q"]]

    # And joining must not fuse two genuinely separate lines.
    assert len(_commands("pytest tests/ -q\npython ci/fetch_swiss_ephemeris.py")) == 2


# ---------------------------------------------------------------------------
# The real workflow
# ---------------------------------------------------------------------------


def _real_job() -> dict:
    document = yaml.safe_load(_TEST_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(document, dict), f"{_TEST_WORKFLOW} did not parse to a mapping"
    job = _job(document, _JOB)
    assert job is not None, (
        f"{_TEST_WORKFLOW} has no `{_JOB}` job. That job is the ONLY thing that runs "
        "this engine's suite against real Swiss ephemeris data; without it "
        "tests/test_swiss_ephemeris.py becomes three permanent skips and CI is back to "
        "validating the Moshier fallback only (CALC-1)."
    )
    return job


def test_swiss_job_fetches_the_data_files() -> None:
    test_parser_discriminates()
    job = _real_job()
    runs = _runs(job)
    assert _job_invokes_fetcher(job), (
        f"the `{_JOB}` job no longer invokes {_FETCHER}, so it has no ephemeris data "
        "and can only be running on the Moshier fallback. Steps found:\n  - "
        + "\n  - ".join(runs)
    )


def test_swiss_job_self_tests_the_verifier_before_trusting_it() -> None:
    test_parser_discriminates()
    job = _real_job()
    assert _job_self_tests_fetcher(job), (
        f"the `{_JOB}` job no longer runs `{_FETCHER} --self-test`. A checksum "
        "verifier that has stopped verifying must not be able to certify the real "
        "download. Steps found:\n  - " + "\n  - ".join(_runs(job))
    )


def test_swiss_job_runs_the_suite_with_the_fail_closed_flag() -> None:
    test_parser_discriminates()
    job = _real_job()
    assert _runs_the_suite_with_the_flag(job), (
        f"the `{_JOB}` job does not run `pytest tests/` with {_FLAG}=1 in effect. "
        f"Without that flag tests/test_swiss_ephemeris.py SKIPS when the ephemeris "
        "data is absent, so this job would report success while validating nothing. "
        f"env values seen for {_FLAG}: {_step_env_flag_values(job, _FLAG) or 'none'}; "
        "run steps:\n  - " + "\n  - ".join(_runs(job))
    )


def test_swiss_job_installs_the_frozen_dependency_set() -> None:
    """Golden values are only reproducible against the pinned resolve."""
    test_parser_discriminates()
    runs = _runs(_real_job())
    assert any(_has_token_sequence(run, "uv", "sync", "--frozen") for run in runs), (
        f"the `{_JOB}` job no longer installs with `uv sync --frozen`. The committed "
        "Swiss golden values are reproducible only against the pinned dependency set "
        "(the same one the image ships); a floating resolve turns a dependency's own "
        "numeric change into a mystery golden failure. Steps found:\n  - "
        + "\n  - ".join(runs)
    )


def test_swiss_job_caches_the_data_by_manifest_hash() -> None:
    """A cache keyed on anything but the manifest could satisfy a new pin with old bytes."""
    test_parser_discriminates()
    job = _real_job()
    assert any(step.startswith("actions/cache") for step in _uses(job)), (
        f"the `{_JOB}` job no longer caches data/ephe; every run would re-download "
        "~5 MB from the upstream host"
    )
    for step in _steps(job):
        if not str(step.get("uses", "")).startswith("actions/cache"):
            continue
        key = str((step.get("with") or {}).get("key", ""))
        assert "ci/swiss_ephemeris.json" in key, (
            "the ephemeris cache key no longer includes ci/swiss_ephemeris.json, so a "
            f"stale cache could survive a checksum change. key={key!r}"
        )


def test_enablement_parser_discriminates() -> None:
    """Fixtures for the `if:`-evaluator, mirroring ``test_parser_discriminates``:
    every case here is something a textual scan (or a check that only reads the
    job's contents) gets wrong."""
    # A blanket `if: false` — the exact mutation this guard exists to catch —
    # must be rejected for both real triggers, however it is spelled.
    disabled_literal = _job(
        yaml.safe_load("jobs:\n  swiss-ephemeris:\n    if: false\n    steps: []\n"),
        _JOB,
    )
    assert _runs_for_event(disabled_literal, "push") is False
    assert _runs_for_event(disabled_literal, "pull_request") is False

    disabled_expr = _job(
        yaml.safe_load("jobs:\n  swiss-ephemeris:\n    if: ${{ false }}\n    steps: []\n"),
        _JOB,
    )
    assert _runs_for_event(disabled_expr, "push") is False

    disabled_quoted_string = _job(
        yaml.safe_load("jobs:\n  swiss-ephemeris:\n    if: \"false\"\n    steps: []\n"),
        _JOB,
    )
    assert _runs_for_event(disabled_quoted_string, "push") is False

    # No `if:` at all means the job always runs.
    always_runs = _job(
        yaml.safe_load("jobs:\n  swiss-ephemeris:\n    steps: []\n"), _JOB
    )
    assert _runs_for_event(always_runs, "push") is True
    assert _runs_for_event(always_runs, "pull_request") is True

    # THE INVERSE: the repo's real, legitimate schedule-only skip must NOT be
    # rejected. It must run on push/PR and may legitimately skip on schedule.
    legitimate = _job(
        yaml.safe_load(
            "jobs:\n  swiss-ephemeris:\n"
            "    if: github.event_name != 'schedule'\n    steps: []\n"
        ),
        _JOB,
    )
    assert _runs_for_event(legitimate, "push") is True
    assert _runs_for_event(legitimate, "pull_request") is True
    assert _runs_for_event(legitimate, "schedule") is False

    # Equivalent spellings of the same legitimate condition must also be accepted.
    for text in (
        "${{ github.event_name != 'schedule' }}",
        "github.event_name != 'schedule' && true",
        "!(github.event_name == 'schedule')",
    ):
        job = _job(
            yaml.safe_load(f"jobs:\n  swiss-ephemeris:\n    if: \"{text}\"\n    steps: []\n"),
            _JOB,
        )
        assert _runs_for_event(job, "push") is True, f"rejected legitimate form: {text!r}"

    # PRECEDENCE (round 3, finding 1a): GitHub Actions binds `!` tighter than
    # `==`/`!=` (see the precedence table on _ExpressionParser). So
    # `!github.event_name == 'schedule'` parses as
    # `(!github.event_name) == 'schedule'` -- i.e. `false == 'schedule'`,
    # which is false for EVERY event, including push and pull_request. An
    # evaluator that instead applies `!` to the whole comparison (reading it
    # as `!(github.event_name == 'schedule')`) gets this exactly backwards:
    # it would report the job enabled when the real workflow disables it on
    # every push and PR. Every spelling below must evaluate to False, not
    # True -- the opposite of the "legitimate" list just above.
    for typo in (
        "!github.event_name == 'schedule'",
        "! github.event_name == 'schedule'",
        "${{ !github.event_name == 'schedule' }}",
    ):
        job = _job(
            yaml.safe_load(f"jobs:\n  swiss-ephemeris:\n    if: \"{typo}\"\n    steps: []\n"),
            _JOB,
        )
        assert _runs_for_event(job, "push") is False, (
            f"precedence bug: {typo!r} must evaluate to False (disabled) for push -- "
            "'!' binds tighter than '==' in GHA, so this is (!github.event_name) == "
            "'schedule', not !(github.event_name == 'schedule')"
        )

    # A condition using syntax outside the supported subset must fail closed —
    # "cannot prove enablement" — rather than being silently treated as enabled.
    unsupported = _job(
        yaml.safe_load(
            "jobs:\n  swiss-ephemeris:\n"
            "    if: contains(github.event.head_commit.message, 'skip-ci')\n"
            "    steps: []\n"
        ),
        _JOB,
    )
    try:
        _runs_for_event(unsupported, "push")
    except _UnsupportedExpression:
        pass
    else:
        raise AssertionError("an unsupported expression form was silently evaluated")


def test_paren_grouping_does_not_coerce_to_bool() -> None:
    """Round 4, finding 2: `_primary`'s paren branch used to funnel through
    `_comparison`'s bare-operand fallback, which returned `bool(lhs)`
    unconditionally -- so `(github.event_name)` became the Python bool
    `True` instead of the real string `'push'`/`'pull_request'` before any
    enclosing comparison ever saw it. GitHub Actions parens are pure
    grouping and must never change a value's type.

    Every form below is something the coercion bug got wrong -- either by
    reporting a job enabled that GHA would actually skip, or (over-strictly)
    reporting one disabled that GHA would actually run. None of these
    depend on which real event is under test except where noted, since they
    are comparisons against literal `true`/`false`.
    """
    # Under GHA's own number-coercion table (string -> NaN if non-numeric,
    # boolean -> 1/0, NaN never equal to anything -- see _to_number /
    # _loose_equals), comparing the real string event name against a
    # boolean literal is false for EVERY event. The coercion bug reported
    # all five of these as enabled on both push and pull_request instead.
    for expr in (
        "(github.event_name) == true",
        "((github.event_name)) == true",
        "true == (github.event_name)",
        "(github.event_name) != false",
    ):
        for event_name in ("push", "pull_request"):
            assert _evaluate_gha_if(expr, event_name) is False, (
                f"{expr!r} must evaluate False for {event_name!r} -- a string "
                "event name is never loosely equal to a boolean literal under "
                "GHA's own coercion rules, but the paren-coercion bug reported "
                "every one of these as enabled"
            )

    # Over-strict in the other direction: a paren-wrapped value compared
    # against its OWN real string value must still equal it. The coercion
    # bug reported this as False (disabled) for a real push event, which
    # would falsely red a legitimate condition shaped like this.
    assert _evaluate_gha_if("(github.event_name) == 'push'", "push") is True
    assert _evaluate_gha_if("(github.event_name) == 'push'", "pull_request") is False

    # A realistic parenthesised form equivalent to the real job's own
    # `github.event_name != 'schedule'` condition: two paren-wrapped
    # inequality checks ANDed together. Parens must not flip this to
    # "enabled" for push/pull_request or to "disabled" for schedule.
    combined = (
        "(github.event_name) != 'push' && (github.event_name) != 'pull_request'"
    )
    assert _evaluate_gha_if(combined, "push") is False
    assert _evaluate_gha_if(combined, "pull_request") is False
    assert _evaluate_gha_if(combined, "schedule") is True


# ---------------------------------------------------------------------------
# Trigger-BODY checks (round 3, finding 1b) — presence of `push`/`pull_request`
# as keys in `on:` proves nothing about whether the filters inside them let a
# real push/PR through. `paths-ignore: ["**"]` or `branches: ["no-such-branch"]`
# keep those keys present while silencing the workflow entirely.
# ---------------------------------------------------------------------------

_FIXTURE_TRIGGERS_GOOD = """
on:
  push:
    paths-ignore:
      - "**.md"
      - "LICENSE"
  pull_request:
    paths-ignore:
      - "**.md"
      - "LICENSE"
jobs:
  swiss-ephemeris:
    steps: []
"""

_FIXTURE_TRIGGERS_NO_FILTERS = """
on:
  push: {}
  pull_request: {}
jobs:
  swiss-ephemeris:
    steps: []
"""

_FIXTURE_TRIGGERS_BRANCHES_INCLUDE_MAIN = """
on:
  push:
    branches:
      - "main"
  pull_request: {}
jobs:
  swiss-ephemeris:
    steps: []
"""

_FIXTURE_TRIGGERS_PATHS_IGNORE_STAR = """
on:
  push:
    paths-ignore:
      - "**"
  pull_request:
    paths-ignore:
      - "**"
jobs:
  swiss-ephemeris:
    steps: []
"""

_FIXTURE_TRIGGERS_PATHS_IGNORE_STAR_SLASH_STAR = """
on:
  push:
    paths-ignore:
      - "**/*"
      - "**"
  pull_request:
    paths-ignore:
      - "**/*"
      - "**"
jobs:
  swiss-ephemeris:
    steps: []
"""

_FIXTURE_TRIGGERS_WRONG_BRANCH = """
on:
  push:
    branches:
      - "no-such-branch-xyz"
  pull_request:
    branches:
      - "no-such-branch-xyz"
jobs:
  swiss-ephemeris:
    steps: []
"""

# Round 4, finding 3: `fnmatch` has no notion of GHA's `!`-exclusion, and GHA
# filters are order-dependent -- the LAST matching pattern wins. Each fixture
# below fully disables the trigger (every path/branch that the first pattern
# would ever match is immediately excluded by a later `!`-prefixed one) while
# a match-any-pattern check (no negation awareness) stays green.

_FIXTURE_TRIGGERS_PATHS_STAR_THEN_NEGATE_ALL = """
on:
  push:
    paths:
      - "**"
      - "!**"
  pull_request:
    paths:
      - "**"
      - "!**"
jobs:
  swiss-ephemeris:
    steps: []
"""

_FIXTURE_TRIGGERS_PATHS_REALISTIC_NEGATED_ALLOWLIST = """
on:
  push:
    paths:
      - "**"
      - "!.github/**"
      - "!bphs_core/**"
      - "!tests/**"
      - "!ci/**"
  pull_request:
    paths:
      - "**"
      - "!.github/**"
      - "!bphs_core/**"
      - "!tests/**"
      - "!ci/**"
jobs:
  swiss-ephemeris:
    steps: []
"""

_FIXTURE_TRIGGERS_BRANCHES_DOUBLESTAR_NEGATE_MAIN = """
on:
  push:
    branches:
      - "**"
      - "!main"
  pull_request:
    branches:
      - "**"
      - "!main"
jobs:
  swiss-ephemeris:
    steps: []
"""

_FIXTURE_TRIGGERS_BRANCHES_STAR_NEGATE_MAIN = """
on:
  push:
    branches:
      - "*"
      - "!main"
  pull_request:
    branches:
      - "*"
      - "!main"
jobs:
  swiss-ephemeris:
    steps: []
"""


def test_trigger_body_parser_discriminates() -> None:
    """Fixtures for the trigger-body checks: `push`/`pull_request` being keys in
    `on:` is necessary but not sufficient -- each fixture below is something a
    presence-only check ("is the key there") gets wrong, because it never looks
    at the filters nested inside."""

    def triggers_of(text: str) -> dict:
        return _workflow_triggers(yaml.safe_load(text))

    # Legitimate forms — mirrors the real workflow's own paths-ignore, plus a
    # branches allowlist that DOES include the default branch, plus no filters
    # at all. None of these may be flagged.
    for fixture in (
        _FIXTURE_TRIGGERS_GOOD,
        _FIXTURE_TRIGGERS_NO_FILTERS,
        _FIXTURE_TRIGGERS_BRANCHES_INCLUDE_MAIN,
    ):
        triggers = triggers_of(fixture)
        for event in ("push", "pull_request"):
            body = triggers.get(event)
            assert not _paths_filter_excludes_own_workflow(body), (
                f"legitimate fixture {fixture!r} was flagged on {event} for its path filter"
            )
            assert not _branches_filter_excludes_default_branch(body), (
                f"legitimate fixture {fixture!r} was flagged on {event} for its branch filter"
            )

    # `paths-ignore: ["**"]` matches every path, including the workflow file's
    # own path -- a push that edits test.yml to re-enable the job would itself
    # never trigger it. Must be flagged on both triggers.
    star = triggers_of(_FIXTURE_TRIGGERS_PATHS_IGNORE_STAR)
    for event in ("push", "pull_request"):
        assert _paths_filter_excludes_own_workflow(star.get(event)), (
            f"paths-ignore: ['**'] on {event} was not flagged, but it excludes every "
            "path, including the workflow file itself"
        )

    # Same shape, two glob spellings for "everything".
    star_slash_star = triggers_of(_FIXTURE_TRIGGERS_PATHS_IGNORE_STAR_SLASH_STAR)
    for event in ("push", "pull_request"):
        assert _paths_filter_excludes_own_workflow(star_slash_star.get(event)), (
            f"paths-ignore: ['**/*', '**'] on {event} was not flagged"
        )

    # `branches: ["no-such-branch-xyz"]` excludes the repo's actual default
    # branch -- a real push/PR against it would never run this job.
    wrong_branch = triggers_of(_FIXTURE_TRIGGERS_WRONG_BRANCH)
    for event in ("push", "pull_request"):
        assert _branches_filter_excludes_default_branch(wrong_branch.get(event)), (
            f"branches: ['no-such-branch-xyz'] on {event} was not flagged, but it "
            f"excludes the default branch ({_DEFAULT_BRANCH!r})"
        )

    # Round 4, finding 3: `!`-negation with last-match-wins. A `paths:`/
    # `branches:` allowlist that matches everything and then immediately
    # negates it (or negates specifically the default branch / this
    # workflow's own path) must be flagged exactly like an outright
    # `paths-ignore: ["**"]` -- `fnmatch.fnmatch` alone cannot see this at
    # all, since it evaluates each pattern in isolation.
    for fixture in (
        _FIXTURE_TRIGGERS_PATHS_STAR_THEN_NEGATE_ALL,
        _FIXTURE_TRIGGERS_PATHS_REALISTIC_NEGATED_ALLOWLIST,
    ):
        triggers = triggers_of(fixture)
        for event in ("push", "pull_request"):
            assert _paths_filter_excludes_own_workflow(triggers.get(event)), (
                f"negated paths allowlist in {fixture!r} was not flagged on {event} "
                "-- GHA filters are order-dependent (last match wins) and this "
                "negates every path, including the workflow's own"
            )

    for fixture in (
        _FIXTURE_TRIGGERS_BRANCHES_DOUBLESTAR_NEGATE_MAIN,
        _FIXTURE_TRIGGERS_BRANCHES_STAR_NEGATE_MAIN,
    ):
        triggers = triggers_of(fixture)
        for event in ("push", "pull_request"):
            assert _branches_filter_excludes_default_branch(triggers.get(event)), (
                f"negated branches allowlist in {fixture!r} was not flagged on "
                f"{event} -- it matches everything and then excludes exactly "
                f"the default branch ({_DEFAULT_BRANCH!r})"
            )


def test_scalar_filter_value_fails_closed() -> None:
    """Round 4, non-blocking item 3, handled honestly rather than waved
    through: whether GHA even accepts a scalar (non-list) `paths` /
    `paths-ignore` / `branches` / `branches-ignore` value -- and if so, how
    -- could not be verified without pushing to a real repository. The
    previous behaviour silently treated a present scalar as "no filter"
    (permissive on an unverified assumption). This guard now fails closed
    instead: a present scalar value raises rather than being read as
    "no restriction"."""
    for trigger_body in ({"paths-ignore": "**.md"}, {"paths": "src/**"}):
        try:
            _paths_filter_excludes_own_workflow(trigger_body)
        except _UnverifiedFilterShape:
            pass
        else:
            raise AssertionError(
                f"a scalar filter value in {trigger_body!r} was silently treated "
                "as 'no filter' instead of failing closed"
            )
    for trigger_body in ({"branches-ignore": "main"}, {"branches": "main"}):
        try:
            _branches_filter_excludes_default_branch(trigger_body)
        except _UnverifiedFilterShape:
            pass
        else:
            raise AssertionError(
                f"a scalar filter value in {trigger_body!r} was silently treated "
                "as 'no filter' instead of failing closed"
            )


def test_swiss_job_is_actually_enabled_on_its_real_triggers() -> None:
    """A guard that only checks the job's CONTENTS can be defeated trivially: add
    `if: false` to the job and every other test in this file keeps passing,
    because the steps it inspects are still correctly written — they simply
    never run. This proves the job is reachable on the workflow's real
    push/pull_request triggers, not merely well-formed.

    A schedule-only skip (`github.event_name != 'schedule'`) is fine and is
    deliberately NOT what this assertion checks — see
    test_enablement_parser_discriminates for the proof that such a condition is
    not falsely rejected.
    """
    test_enablement_parser_discriminates()
    test_trigger_body_parser_discriminates()
    document = yaml.safe_load(_TEST_WORKFLOW.read_text(encoding="utf-8"))
    job = _job(document, _JOB)
    assert job is not None

    triggers = _workflow_triggers(document)
    assert "push" in triggers and "pull_request" in triggers, (
        f"{_TEST_WORKFLOW} no longer declares push/pull_request triggers at the "
        "workflow level -- update this guard's assumptions if that changed deliberately"
    )

    # Presence of the keys above is necessary but not sufficient (finding 1b):
    # a paths/paths-ignore filter that can never match the workflow's own path,
    # or a branches filter that excludes the default branch, keeps `push`/
    # `pull_request` declared while the job can never actually run for a real
    # push or PR against this repo.
    for event_name in ("push", "pull_request"):
        trigger_body = triggers.get(event_name)
        assert not _paths_filter_excludes_own_workflow(trigger_body), (
            f"the `{event_name}` trigger's path filters would exclude changes to "
            f"{_WORKFLOW_RELATIVE_PATH} itself -- a paths-ignore/paths filter this "
            f"broad silences the whole workflow while `{event_name}` stays declared "
            f"as a trigger. trigger body: {trigger_body!r}"
        )
        assert not _branches_filter_excludes_default_branch(trigger_body), (
            f"the `{event_name}` trigger's branch filters exclude the default branch "
            f"({_DEFAULT_BRANCH!r}) -- a real push/PR against {_DEFAULT_BRANCH!r} would "
            f"never run this job. trigger body: {trigger_body!r}"
        )

    condition = _condition(job)
    for event_name in ("push", "pull_request"):
        try:
            enabled = _runs_for_event(job, event_name)
        except _UnsupportedExpression as exc:
            raise AssertionError(
                f"the `{_JOB}` job's `if:` condition ({condition!r}) uses syntax this "
                f"guard cannot evaluate ({exc}), so it cannot prove the job actually "
                "runs on a real push/PR event. Rewrite the condition using the "
                "supported subset (==, !=, &&, ||, !, parens, string/bool literals, "
                "github.event_name), or extend this guard deliberately."
            ) from exc
        assert enabled, (
            f"the `{_JOB}` job's `if:` condition ({condition!r}) evaluates to False "
            f"for github.event_name == {event_name!r}. A job whose steps are all "
            "correctly written but never RUNS is exactly the fail-open shape this "
            "guard exists to prevent -- every other test in this file would still "
            "pass. Fix the condition so the job runs on real push/PR events; a "
            "schedule-only skip (github.event_name != 'schedule') is fine and is "
            "not what this assertion checks."
        )


def test_step_enablement_parser_discriminates() -> None:
    """Fixtures for the STEP-level `if:` evaluator (round 4, finding 1),
    mirroring test_enablement_parser_discriminates. `_runs_for_event` is the
    exact same evaluator used for jobs -- GitHub Actions' `if:` grammar is
    identical for a job and a step -- applied here directly to a step
    mapping instead of a job mapping."""
    for disabling in (
        {"if": False},
        {"if": "${{ false }}"},
        {"if": "github.event_name == 'schedule'"},
    ):
        for event_name in ("push", "pull_request"):
            assert _runs_for_event(disabling, event_name) is False, disabling

    # No `if:` at all -- the step always runs.
    assert _runs_for_event({}, "push") is True
    assert _runs_for_event({}, "pull_request") is True

    # The real workflow's own legitimate spelling -- the `if:` on the `test`
    # job's "Run tests" and "Run CI gate regression suite" steps -- must not
    # be false-rejected by the step-level evaluator either.
    legitimate = {"if": "github.event_name != 'schedule'"}
    assert _runs_for_event(legitimate, "push") is True
    assert _runs_for_event(legitimate, "pull_request") is True
    assert _runs_for_event(legitimate, "schedule") is False


def test_swiss_job_suite_step_is_not_conditionally_skipped() -> None:
    """Round 4, finding 1: every check above -- including
    test_swiss_job_runs_the_suite_with_the_fail_closed_flag and
    test_swiss_job_is_actually_enabled_on_its_real_triggers -- inspects the
    JOB's `if:` but never looks at the STEP's own `if:`. Add a disabling
    `if:` to ONLY the suite step (the `swiss-ephemeris` job's "Run the full
    suite against real Swiss data" step in `.github/workflows/test.yml`): the
    job has no job-level `if:` blocking it, every other step still runs, and
    GitHub Actions marks that one step `skipped` while the JOB still reports
    `success`. Every other test in this file would still pass -- the exact
    fail-open shape this whole file exists to prevent, one level below the
    job's own `if:` (see test_swiss_job_is_actually_enabled_on_its_real_triggers's
    docstring for the job-level version of this same argument).

    This is not scope creep: test_swiss_job_does_not_continue_on_error
    already iterates steps for the sibling `continue-on-error` vector, and
    this file's own module
    docstring already frames "correctly written but never RUNS" as the
    invariant to defend. The `test` job's own "Run tests" and "Run CI gate
    regression suite" steps use step-level `if:` legitimately -- see
    test_legitimate_step_level_if_in_the_test_job_is_not_false_rejected for
    the concrete proof this guard does not false-reject that spelling.
    """
    test_step_enablement_parser_discriminates()
    job = _real_job()
    step = _suite_step(job)
    assert step is not None, (
        "no step in the swiss-ephemeris job runs pytest tests/ with "
        f"{_FLAG}=1 in scope -- see test_swiss_job_runs_the_suite_with_the_fail_closed_flag"
    )
    condition = _condition(step)
    for event_name in ("push", "pull_request"):
        try:
            enabled = _runs_for_event(step, event_name)
        except _UnsupportedExpression as exc:
            raise AssertionError(
                f"the suite step's `if:` condition ({condition!r}) uses syntax this "
                f"guard cannot evaluate ({exc}), so it cannot prove the step actually "
                "runs on a real push/PR event. Rewrite the condition using the "
                "supported subset, or extend this guard deliberately."
            ) from exc
        assert enabled, (
            f"the suite step's `if:` condition ({condition!r}) evaluates to False "
            f"for github.event_name == {event_name!r}. A step-level `if:` that skips "
            "the one step that actually runs the accuracy suite lets the job report "
            "success while validating nothing -- every other test in this file would "
            "still pass."
        )


def test_legitimate_step_level_if_in_the_test_job_is_not_false_rejected() -> None:
    """In `.github/workflows/test.yml`, the `test` job's own "Run tests" and
    "Run CI gate regression suite" steps use step-level
    `if: github.event_name != 'schedule'` legitimately -- skipping
    pytest on the weekly schedule-only run, exactly like the job-level
    condition on `swiss-ephemeris`. The step-level evaluator introduced for
    round 4, finding 1 must not mistake these for a disabling condition."""
    document = yaml.safe_load(_TEST_WORKFLOW.read_text(encoding="utf-8"))
    test_job = _job(document, "test")
    assert test_job is not None, f"{_TEST_WORKFLOW} no longer has a `test` job"
    for step_name in ("Run tests", "Run CI gate regression suite"):
        step = next((s for s in _steps(test_job) if s.get("name") == step_name), None)
        assert step is not None, f"the `test` job no longer has a step named {step_name!r}"
        assert _runs_for_event(step, "push") is True, (
            f"step {step_name!r}'s `if:` was false-rejected for push"
        )
        assert _runs_for_event(step, "pull_request") is True, (
            f"step {step_name!r}'s `if:` was false-rejected for pull_request"
        )
        assert _runs_for_event(step, "schedule") is False, (
            f"step {step_name!r}'s `if:` should legitimately skip the weekly "
            "schedule-only run, but the evaluator reports it enabled"
        )


def test_swiss_job_does_not_continue_on_error() -> None:
    """`continue-on-error: true` lets a job (or a step) fail without failing the
    workflow -- a second way to make a red accuracy run look green. Neither the
    job nor any of its steps may set it."""
    job = _real_job()
    assert job.get("continue-on-error") is not True, (
        f"the `{_JOB}` job sets continue-on-error: true -- a failing accuracy run "
        "would no longer fail CI"
    )
    for step in _steps(job):
        assert step.get("continue-on-error") is not True, (
            f"a step in the `{_JOB}` job sets continue-on-error: true: {step}"
        )


# ---------------------------------------------------------------------------
# STRUCTURAL BACKSTOP (round 4). Rounds 1, 2 and 3 each hardened the semantic
# checks above and each time a NEW disabling vector appeared that they did
# not model: job-level `if:` -> `!` precedence -> presence-only triggers ->
# step-level `if:` -> paren-coercion -> glob negation. Reimplementing GHA's
# full semantics one gap at a time is an unbounded surface, and the score so
# far is round 1-3 each losing that race exactly once.
#
# The assertion below does not evaluate semantics at all, so a semantics
# divergence cannot defeat it: it snapshots every field that can affect
# whether the swiss-ephemeris job actually runs (the job's `if:`, every
# step's `if:`, `continue-on-error` at job and step level, and the full
# `on:` trigger bodies) and diffs that shape against a value committed here.
# ANY change to the shape reds, and updating _EXPECTED_ENABLEMENT_SNAPSHOT is
# a deliberate, reviewed act -- not something a stray workflow edit does by
# accident.
#
# THE SEMANTIC CHECKS ABOVE ARE NOT MADE REDUNDANT BY THIS. Keep both: the
# semantic checks give a precise, actionable error message for the forms
# they know about ("this `if:` evaluates False for push because ..."); this
# snapshot is the catch-all for a form nobody has thought of yet. A future
# reader should not delete either one thinking it duplicates the other --
# see test_enablement_snapshot_catches_forms_the_semantic_checks_do_not for
# concrete proof the two are not redundant.
# ---------------------------------------------------------------------------


def _enablement_snapshot(document: dict, job: dict) -> dict:
    """The full enablement-relevant shape of the workflow, for the structural
    backstop above: everything that decides whether `job` actually executes
    on a real push/PR, captured verbatim rather than evaluated."""
    return {
        "job_if": job.get("if"),
        "job_continue_on_error": job.get("continue-on-error"),
        "steps": [
            {
                "name": step.get("name"),
                "if": step.get("if"),
                "continue_on_error": step.get("continue-on-error"),
            }
            for step in _steps(job)
        ],
        "on": _workflow_triggers(document),
    }


_EXPECTED_ENABLEMENT_SNAPSHOT = {
    "job_if": "github.event_name != 'schedule'",
    "job_continue_on_error": None,
    "steps": [
        {"name": None, "if": None, "continue_on_error": None},
        {"name": None, "if": None, "continue_on_error": None},
        {
            "name": "Cache Swiss ephemeris data files",
            "if": None,
            "continue_on_error": None,
        },
        {
            "name": "Self-test the checksum verifier",
            "if": None,
            "continue_on_error": None,
        },
        {
            "name": "Fetch + verify the Swiss ephemeris data files",
            "if": None,
            "continue_on_error": None,
        },
        # The two steps below joined this job when the uv toolchain was pinned:
        # CI used to install uv with a floating `pip install --upgrade uv` while
        # both Dockerfiles digest-pin it, and nothing asserted uv.lock was still
        # fresh against pyproject.toml. Neither carries an `if:` or a
        # `continue-on-error:`, so this job's enablement shape is unchanged in
        # every respect this snapshot exists to police — the entries are added
        # because the snapshot is positional, not because anything about when
        # this job runs has moved. See
        # ci/tests/test_environment_convergence.py sections 5 and 6.
        {
            "name": "Install uv, at the version the shipped images install",
            "if": None,
            "continue_on_error": None,
        },
        {
            "name": "The lockfile is FRESH (uv.lock still satisfies pyproject.toml)",
            "if": None,
            "continue_on_error": None,
        },
        {
            "name": "Install the FROZEN dependency set",
            "if": None,
            "continue_on_error": None,
        },
        {
            "name": "Run the full suite against real Swiss data",
            "if": None,
            "continue_on_error": None,
        },
    ],
    "on": {
        "push": {"paths-ignore": ["**.md", "LICENSE"]},
        "pull_request": {"paths-ignore": ["**.md", "LICENSE"]},
        "schedule": [{"cron": "0 6 * * 1"}],
    },
}


def test_swiss_job_enablement_snapshot_matches_committed_shape() -> None:
    """THE STRUCTURAL BACKSTOP -- see the module-level comment just above this
    function for why it exists alongside, not instead of, the semantic
    checks. This assertion does not evaluate `if:` expressions or glob
    filters at all; it snapshots their raw shape and diffs against a value
    committed here. ANY change to that shape reds and requires a deliberate,
    reviewed update to _EXPECTED_ENABLEMENT_SNAPSHOT.
    """
    document = yaml.safe_load(_TEST_WORKFLOW.read_text(encoding="utf-8"))
    job = _job(document, _JOB)
    assert job is not None
    snapshot = _enablement_snapshot(document, job)
    assert snapshot == _EXPECTED_ENABLEMENT_SNAPSHOT, (
        f"the `{_JOB}` job's enablement-relevant shape changed. If this is a "
        "deliberate, reviewed change, update _EXPECTED_ENABLEMENT_SNAPSHOT to "
        f"match it. Actual snapshot:\n{snapshot!r}"
    )


def test_enablement_snapshot_catches_forms_the_semantic_checks_do_not() -> None:
    """Proof the backstop is not redundant with the semantic checks above:
    two disabling mutations that the EVALUATOR does not model at all (so
    none of the `if:`/trigger checks would flag them) still change the
    snapshot -- which is exactly what would turn
    test_swiss_job_enablement_snapshot_matches_committed_shape red if either
    mutation were made to the real workflow file. Mutating in-memory copies
    here (rather than the tracked test.yml) proves the same thing without
    ever leaving the real workflow in a broken state.
    """
    document = yaml.safe_load(_TEST_WORKFLOW.read_text(encoding="utf-8"))
    job = _job(document, _JOB)
    assert job is not None
    baseline = _enablement_snapshot(document, job)
    assert baseline == _EXPECTED_ENABLEMENT_SNAPSHOT

    # Form 1: `pull_request.types` restricted to an event type a normal PR
    # push/update never produces. This is the acknowledged non-blocking gap
    # ("types: filters unhandled") -- neither
    # _paths_filter_excludes_own_workflow nor
    # _branches_filter_excludes_default_branch inspects `types` at all, and
    # _runs_for_event never looks at trigger bodies, so nothing above would
    # flag it. The snapshot, which captures the full trigger body verbatim,
    # still catches it.
    mutated_types = yaml.safe_load(_TEST_WORKFLOW.read_text(encoding="utf-8"))
    mutated_types[True]["pull_request"]["types"] = ["closed"]
    mutated_job_1 = _job(mutated_types, _JOB)
    assert mutated_job_1 is not None
    mutated_snapshot_1 = _enablement_snapshot(mutated_types, mutated_job_1)
    assert mutated_snapshot_1 != _EXPECTED_ENABLEMENT_SNAPSHOT, (
        "a pull_request `types` restriction did not change the snapshot -- "
        "the backstop would not have caught it"
    )

    # Form 2: `if: false` on the FETCHER step -- not the suite step round 4
    # finding 1's fix specifically checks (test_swiss_job_suite_step_is_not_
    # conditionally_skipped only looks at the step _suite_step identifies).
    # _job_invokes_fetcher only checks that some `run:` body in the job's
    # steps textually invokes the fetcher; it never checks whether that
    # step itself would actually execute. The snapshot, which captures
    # every step's `if:` by position, still catches it.
    mutated_step_if = yaml.safe_load(_TEST_WORKFLOW.read_text(encoding="utf-8"))
    fetch_step = next(
        step
        for step in mutated_step_if["jobs"][_JOB]["steps"]
        if step.get("name") == "Fetch + verify the Swiss ephemeris data files"
    )
    fetch_step["if"] = False
    mutated_job_2 = _job(mutated_step_if, _JOB)
    assert mutated_job_2 is not None
    assert _job_invokes_fetcher(mutated_job_2), (
        "sanity check: the mutated fixture must still structurally look like "
        "it invokes the fetcher, or this isn't testing what it claims"
    )
    mutated_snapshot_2 = _enablement_snapshot(mutated_step_if, mutated_job_2)
    assert mutated_snapshot_2 != _EXPECTED_ENABLEMENT_SNAPSHOT, (
        "an `if: false` on the fetcher step did not change the snapshot -- "
        "the backstop would not have caught it"
    )


# ---------------------------------------------------------------------------
# The suite step must still REACH every swiss-gated module
# ---------------------------------------------------------------------------
#
# The checks above prove the job exists, fetches the data, installs frozen, and runs
# `pytest tests/…` with the fail-closed flag. None of them proves WHICH tests that
# pytest invocation reaches, and `_runs_the_test_suite` deliberately accepts any target
# under `tests/`. So this passes every assertion above:
#
#     REQUIRE_SWISS_EPHEMERIS: "1"
#     run: uv run --frozen python -m pytest tests/test_swiss_ephemeris.py -q
#
# and it silently drops tests/test_independent_reference_corpus.py (the NASA/JPL
# corpus) and tests/test_ayanamsa_zero_point.py out of the accuracy gate. Those modules
# are gated on the `swiss_ephemeris` fixture, so in the fast `test` job — which has no
# ephemeris data — they SKIP. Narrow the target here and they skip in BOTH jobs: the
# external-authority accuracy assertions stop running anywhere, green, silently. That
# is the same fail-open shape as deleting the job, reached by editing one path.
#
# SCOPE COMES FROM THE SOURCE OF TRUTH, NOT A HARDCODED LIST. The protected set is
# derived by parsing tests/*.py and finding functions that take the `swiss_ephemeris`
# fixture, so a THIRD swiss-gated module added tomorrow is protected the day it lands
# without anyone remembering to edit this file. A hardcoded list would silently stop
# covering exactly the module a future author forgot about.
#
# ast, not grep: `swiss_ephemeris` appears in comments, in docstrings, and in this very
# file. Only a parameter in a function signature means a test is actually gated.

_CORPUS_MODULE = "tests/test_independent_reference_corpus.py"
_FIXTURE = "swiss_ephemeris"

# ONE DEFINITION, TWO READERS. The flag tables live in ci/check_pytest_collection.py
# — the standalone checker that catches the pytest-config vector this file
# structurally cannot (see that module's docstring) — and are imported here rather
# than copied. Two copies would drift, and the copy that stopped covering a flag
# would be the one nobody re-read.
#
#   _VALUE_TAKING_DESELECT_FLAGS  deselecting flags that consume the next argv slot,
#                                 so `--ignore tests/x.py` does not leave the path
#                                 looking like a positional target.
#   _COLLECTION_ONLY_FLAGS        `--collect-only` / `--co`: deselect nothing, run
#                                 nothing. A guard modelling only deselection reports
#                                 "yes, every gated module is reached" — correctly,
#                                 and irrelevantly.
#   _NARROWING_FLAGS              the union, which is what this file tests against.
_VALUE_TAKING_DESELECT_FLAGS = _COLLECTION_CHECKER.VALUE_TAKING_DESELECT_FLAGS
_COLLECTION_ONLY_FLAGS = _COLLECTION_CHECKER.COLLECTION_ONLY_FLAGS
_NARROWING_FLAGS = _COLLECTION_CHECKER.NARROWING_FLAGS


def _swiss_gated_modules(root: Path = _REPO_ROOT) -> list[str]:
    """Repo-relative paths of test modules with at least one `swiss_ephemeris`-gated test.

    ``tests/**/*.py``, not ``tests/*.py``. The flat glob matched the layout exactly
    as it stands — every test module is directly in ``tests/`` today — and would
    have gone on matching it silently on the day that stopped being true. An
    accuracy module added at ``tests/accuracy/test_something.py`` would simply not
    join the protected set, so narrowing the job's target past it would raise no
    objection from the check whose entire purpose is to object. Deriving scope from
    a pattern that cannot see part of the tree is the same defect as deriving it
    from a hardcoded list, one level less obvious.

    Verified to be a no-op for the layout as committed: the set derived by both
    globs is byte-identical today (see the PR that introduced the recursive form).

    ``root`` is a parameter so the subdirectory case can be proved against a
    synthetic tree — the real repo is flat, so a test that only looked at it would
    be asserting the very blind spot it is meant to remove.
    """
    import ast

    gated: list[str] = []
    for path in sorted((root / "tests").glob("**/*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken test file fails elsewhere
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            args = node.args
            names = [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
            if _FIXTURE in names and node.name.startswith("test_"):
                gated.append(path.relative_to(root).as_posix())
                break
    return gated


def _pytest_targets(run: str) -> list[str]:
    """Positional (non-flag) arguments of the pytest command in ``run``.

    Flag VALUES are skipped in both spellings: `--ignore=x` collapses to one token,
    while `--ignore x` puts the path in the next argv slot where it would otherwise
    look like a target.
    """
    for tokens in _commands(run):
        if "pytest" not in tokens:
            continue
        targets: list[str] = []
        after_pytest = tokens[tokens.index("pytest") + 1 :]
        skip_next = False
        for token in after_pytest:
            if skip_next:
                skip_next = False
                continue
            if token.startswith("-"):
                # Only the VALUE-TAKING flags consume the next argv slot.
                # `--collect-only` takes no value, so skipping after it would
                # silently swallow a real positional target.
                if "=" not in token and token in _VALUE_TAKING_DESELECT_FLAGS:
                    skip_next = True
                continue
            targets.append(token)
        return targets
    return []


def _narrowing_flags(run: str) -> list[str]:
    """Flags on the pytest command that cost the run assertions, however spelled.

    Covers both mechanisms: deselection (`--ignore`, `-k`, ...) and
    collection-only (`--collect-only`, `--co`), which deselects nothing and runs
    nothing. Matched on the flag NAME after splitting an `=`, so `--ignore=x` and
    `--ignore x` are both caught while `--color=no` (a prefix of nothing here) and a
    positional path containing the string are not.
    """
    found: list[str] = []
    for tokens in _commands(run):
        if "pytest" not in tokens:
            continue
        for token in tokens[tokens.index("pytest") + 1 :]:
            if not token.startswith("-"):
                continue
            name = token.split("=", 1)[0]
            if name in _NARROWING_FLAGS:
                found.append(name)
    return found


def _target_reaches(target: str, module: str) -> bool:
    """True when a pytest positional argument would collect ``module``.

    A DIRECTORY target collects everything beneath it, at any depth — `pytest tests`
    reaches `tests/accuracy/test_x.py` exactly as it reaches `tests/test_y.py`. That
    is written as a prefix test rather than a special case for the literal string
    `tests`, so that once a gated module can live in a subdirectory (see
    `_swiss_gated_modules`) a legitimate `pytest tests/accuracy` target is not
    false-rejected. A guard that reds on correct input is a guard the next person
    weakens.
    """
    normalised = target.replace("\\", "/").rstrip("/").split("::", 1)[0]
    if normalised == ".":
        return True
    # An explicit file, with or without a `::node` selector.
    if normalised == module:
        return True
    return module.startswith(f"{normalised}/")


def _job_reaches(job: dict, module: str) -> bool:
    step = _suite_step(job)
    if step is None:
        return False
    run = str(step.get("run", ""))
    if _narrowing_flags(run):
        return False
    return any(_target_reaches(target, module) for target in _pytest_targets(run))


_FIXTURE_TARGET_NARROWED = """
jobs:
  swiss-ephemeris:
    steps:
      - name: Run the full suite against real Swiss data
        env:
          REQUIRE_SWISS_EPHEMERIS: "1"
        run: uv run --frozen python -m pytest tests/test_swiss_ephemeris.py -q
"""

_FIXTURE_TARGET_IGNORES_CORPUS = """
jobs:
  swiss-ephemeris:
    steps:
      - name: Run the full suite against real Swiss data
        env:
          REQUIRE_SWISS_EPHEMERIS: "1"
        run: uv run --frozen python -m pytest tests/ -q --ignore=tests/test_independent_reference_corpus.py
"""

_FIXTURE_TARGET_IGNORES_SPACE_SEPARATED = """
jobs:
  swiss-ephemeris:
    steps:
      - name: Run the full suite against real Swiss data
        env:
          REQUIRE_SWISS_EPHEMERIS: "1"
        run: uv run --frozen python -m pytest tests/ --ignore tests/test_independent_reference_corpus.py -q
"""

_FIXTURE_TARGET_DESELECTED_BY_K = """
jobs:
  swiss-ephemeris:
    steps:
      - name: Run the full suite against real Swiss data
        env:
          REQUIRE_SWISS_EPHEMERIS: "1"
        run: uv run --frozen python -m pytest tests/ -q -k "not corpus"
"""

# NOTE THE `r` PREFIX. Without it the Python string parser consumes the
# backslash-newline itself, so this fixture collapsed to a ONE-LINE command and
# never once exercised the continued form it appears to describe (PR #65 review,
# non-blocking item 3). As a raw string the backslash survives into the YAML, the
# `run:` body really is two physical lines, and `_commands` has to handle the shell
# continuation the way a shell does.
_FIXTURE_TARGET_EXPLICIT_FILE = r"""
jobs:
  swiss-ephemeris:
    steps:
      - name: Run the full suite against real Swiss data
        env:
          REQUIRE_SWISS_EPHEMERIS: "1"
        run: |
          uv run --frozen python -m pytest tests/test_swiss_ephemeris.py \
            tests/test_independent_reference_corpus.py -q
"""

# The same continued shape, but NARROWED on the continuation line. Joining
# continuations must not create a blind spot: a `--ignore` that happens to sit
# after the line break has to be found exactly like one on the first line.
_FIXTURE_TARGET_CONTINUED_BUT_IGNORES_CORPUS = r"""
jobs:
  swiss-ephemeris:
    steps:
      - name: Run the full suite against real Swiss data
        env:
          REQUIRE_SWISS_EPHEMERIS: "1"
        run: |
          uv run --frozen python -m pytest tests/ -q \
            --ignore=tests/test_independent_reference_corpus.py
"""

_FIXTURE_TARGET_ONLY_ECHOED = """
jobs:
  swiss-ephemeris:
    steps:
      - name: Run the full suite against real Swiss data
        env:
          REQUIRE_SWISS_EPHEMERIS: "1"
        run: |
          echo "pytest tests/ -q"
          uv run --frozen python -m pytest tests/test_swiss_ephemeris.py -q
"""

# `--collect-only` (and its documented short form `--co`) is a different mechanism
# from every fixture above: it DESELECTS NOTHING. The whole tree is still the
# target, every gated module is still collected, and pytest exits 0 having
# executed no test body and asserted nothing whatsoever. A guard that only models
# deselection reports this job as reaching every module it needs to reach — which
# is true, and completely beside the point. (PR #65 review, non-blocking item 4.)
_FIXTURE_TARGET_COLLECT_ONLY = """
jobs:
  swiss-ephemeris:
    steps:
      - name: Run the full suite against real Swiss data
        env:
          REQUIRE_SWISS_EPHEMERIS: "1"
        run: uv run --frozen python -m pytest tests/ -q --collect-only
"""

_FIXTURE_TARGET_COLLECT_ONLY_SHORT = """
jobs:
  swiss-ephemeris:
    steps:
      - name: Run the full suite against real Swiss data
        env:
          REQUIRE_SWISS_EPHEMERIS: "1"
        run: uv run --frozen python -m pytest tests/ --co -q
"""


def test_reachability_parser_discriminates() -> None:
    """Fixtures the coverage check must get right — each one keeps the job, the fetch
    step and the flag, and differs ONLY in which tests the suite step reaches."""
    corpus = _CORPUS_MODULE

    def job_of(fixture: str) -> dict:
        parsed = _job(yaml.safe_load(fixture), _JOB)
        assert parsed is not None
        return parsed

    # The real shape (whole tree) reaches everything.
    assert _job_reaches(job_of(_FIXTURE_GOOD), corpus)
    # Narrowing the target to one module drops the corpus.
    assert not _job_reaches(job_of(_FIXTURE_TARGET_NARROWED), corpus)
    # --ignore, in both spellings.
    assert not _job_reaches(job_of(_FIXTURE_TARGET_IGNORES_CORPUS), corpus)
    assert not _job_reaches(job_of(_FIXTURE_TARGET_IGNORES_SPACE_SEPARATED), corpus)
    # -k deselection.
    assert not _job_reaches(job_of(_FIXTURE_TARGET_DESELECTED_BY_K), corpus)
    # Naming the file explicitly is legitimate coverage, so it must NOT false-reject.
    # This fixture is a RAW string, so its `run:` body really is two physical lines
    # joined by a shell backslash-continuation — the form a long pytest invocation
    # is actually written in. Before `_commands` joined continuations, shlex raised
    # "No escaped character" on the first line, `_commands` swallowed that as an
    # opaque line, and the whole command parsed to ZERO targets: a correctly-wired
    # workflow REDDED this guard.
    assert _job_reaches(job_of(_FIXTURE_TARGET_EXPLICIT_FILE), corpus)
    # ...and joining must not hide a narrowing flag that sits after the line break.
    assert not _job_reaches(job_of(_FIXTURE_TARGET_CONTINUED_BUT_IGNORES_CORPUS), corpus)
    # A narrowed real command is not rescued by the full command appearing in an echo.
    assert not _job_reaches(job_of(_FIXTURE_TARGET_ONLY_ECHOED), corpus)

    # `--collect-only` deselects NOTHING — the whole tree is still the target and
    # every gated module is still collected — yet no test body runs and the job
    # exits 0 having asserted nothing. Both spellings must be rejected.
    for fixture in (_FIXTURE_TARGET_COLLECT_ONLY, _FIXTURE_TARGET_COLLECT_ONLY_SHORT):
        assert not _job_reaches(job_of(fixture), corpus), (
            "a --collect-only invocation was accepted: it collects every module and "
            "runs none of them, so the accuracy gate asserts nothing while green"
        )
    assert _narrowing_flags("pytest tests/ -q --collect-only") == ["--collect-only"]
    assert _narrowing_flags("pytest tests/ --co -q") == ["--co"]
    # ...and it must not be confused with a legitimate flag that merely starts the
    # same way, or with a positional target that contains the string.
    assert _narrowing_flags("pytest tests/ -q --color=no") == []
    assert _narrowing_flags("pytest tests/test_collect_only.py -q") == []

    # The space-separated `--ignore <path>` form must not leave the path looking like a
    # target: without the skip_next branch this would read as a positional argument.
    assert "tests/test_independent_reference_corpus.py" not in _pytest_targets(
        "pytest tests/ --ignore tests/test_independent_reference_corpus.py -q"
    )

    # A directory target reaches modules at any depth beneath it, and does not
    # reach a sibling directory that merely shares a prefix.
    assert _target_reaches("tests", "tests/accuracy/test_deep.py")
    assert _target_reaches("tests/", "tests/accuracy/test_deep.py")
    assert _target_reaches("tests/accuracy", "tests/accuracy/test_deep.py")
    assert not _target_reaches("tests/accuracy", "tests/test_flat.py")
    assert not _target_reaches("tests", "tests_helpers/test_x.py")

    # And the module-discovery half must actually discover something, or every
    # assertion below is vacuous on an empty set.
    discovered = _swiss_gated_modules()
    assert corpus in discovered, (
        f"{corpus} is not being discovered as a swiss-gated module — the ast scan is "
        f"broken and the real assertion would be vacuous. Found: {discovered}"
    )
    assert "tests/test_swiss_ephemeris.py" in discovered, discovered


def test_gated_module_discovery_reaches_subdirectories(tmp_path: Path) -> None:
    """A gated module in a `tests/` SUBDIRECTORY must join the protected set.

    Proved against a synthetic tree, deliberately. The real `tests/` tree is flat,
    so a test that only inspected it would pass under the old `tests/*.py` glob and
    under the new `tests/**/*.py` one alike — it would be asserting the blind spot
    rather than removing it. The layout being flat TODAY is exactly why the flat
    glob looked correct and would have failed silently the day it stopped being.

    The negative cases matter as much: discovery must still key on a `swiss_ephemeris`
    PARAMETER of a `test_`-prefixed function, at any depth, and not on the string
    appearing in a docstring, a comment, or a non-test helper's signature.
    """
    tests_dir = tmp_path / "tests"
    (tests_dir / "accuracy").mkdir(parents=True)
    (tests_dir / "helpers").mkdir(parents=True)

    (tests_dir / "test_flat.py").write_text(
        "def test_flat_case(swiss_ephemeris):\n    pass\n", encoding="utf-8"
    )
    (tests_dir / "accuracy" / "test_deep.py").write_text(
        "def test_deep_case(swiss_ephemeris):\n    pass\n", encoding="utf-8"
    )
    (tests_dir / "accuracy" / "test_deeper.py").write_text(
        "async def test_async_case(swiss_ephemeris):\n    pass\n", encoding="utf-8"
    )
    # Decoys, at depth, that must NOT be picked up.
    (tests_dir / "helpers" / "test_mentions_only.py").write_text(
        '"""Talks about swiss_ephemeris in a docstring."""\n'
        "# and in a comment: swiss_ephemeris\n"
        "def helper(swiss_ephemeris):\n    pass\n"  # not a test_ function
        "def test_not_gated():\n    pass\n",
        encoding="utf-8",
    )
    (tests_dir / "helpers" / "conftest.py").write_text(
        "def swiss_ephemeris():\n    pass\n", encoding="utf-8"
    )

    discovered = _swiss_gated_modules(tmp_path)

    assert "tests/accuracy/test_deep.py" in discovered, (
        "a swiss-gated module in a tests/ subdirectory was not discovered, so "
        "narrowing the accuracy job past it would raise no objection"
    )
    assert "tests/accuracy/test_deeper.py" in discovered, "async gated test missed"
    assert "tests/test_flat.py" in discovered, "the flat case regressed"
    assert "tests/helpers/test_mentions_only.py" not in discovered, (
        "discovery matched a mention rather than a fixture parameter — it must "
        "parse signatures, not scan text"
    )
    assert "tests/helpers/conftest.py" not in discovered


def test_swiss_job_reaches_every_swiss_gated_module() -> None:
    """The accuracy job's pytest target must still collect every fixture-gated module.

    Deleting the job is caught by ``_real_job``; this catches the quieter edit that
    keeps the job and narrows what it runs. Both end the same way — an accuracy
    assertion that no job on earth executes, with CI green.
    """
    test_parser_discriminates()
    test_reachability_parser_discriminates()
    job = _real_job()

    gated = _swiss_gated_modules()
    assert gated, (
        "no test module takes the `swiss_ephemeris` fixture — either the fixture was "
        "renamed (update _FIXTURE here with it) or the accuracy modules are gone. "
        "Either way this guard has silently stopped guarding anything."
    )
    assert _CORPUS_MODULE in gated, (
        f"{_CORPUS_MODULE} no longer has any `swiss_ephemeris`-gated test. That module "
        "carries the only externally-sourced (NASA/JPL Horizons) accuracy assertions in "
        "this repo; if it is genuinely gone, this guard must be revisited deliberately."
    )

    step = _suite_step(job)
    assert step is not None, f"the `{_JOB}` job has no suite step (see the check above)"
    run = str(step.get("run", ""))

    narrowing = _narrowing_flags(run)
    assert not narrowing, (
        f"the `{_JOB}` job's suite step carries narrowing pytest flag(s) {narrowing}. "
        "This job exists to RUN the WHOLE suite against real ephemeris data; anything "
        "that removes tests from it can silently disarm an accuracy module. Note "
        f"{list(_COLLECTION_ONLY_FLAGS)} deselect nothing and still count: they collect "
        "every gated module, execute no test body, and exit 0 — the gate reports green "
        f"having asserted nothing at all. run:\n{run}"
    )

    unreached = [module for module in gated if not _job_reaches(job, module)]
    assert not unreached, (
        f"the `{_JOB}` job's pytest invocation does not collect {unreached}.\n"
        f"targets parsed: {_pytest_targets(run)}\nrun:\n{run}\n\n"
        "Those modules are gated on the `swiss_ephemeris` fixture, so they SKIP in the "
        "fast `test` job (which has no ephemeris data). This job is the only one that "
        "asserts them. A target that misses them means they now run NOWHERE — the gate "
        "reports green while the accuracy assertions it exists to run never execute."
    )


# ---------------------------------------------------------------------------
# NARROWING THAT NEVER TOUCHES THE RUN LINE (PR #65 review, non-blocking item 1)
# ---------------------------------------------------------------------------
#
# Every check above reads the suite step's `run:` body. pytest takes arguments
# from two other places that a reader of that line cannot see:
#
#   1. `PYTEST_ADDOPTS` in the environment. GitHub Actions resolves `env:` at
#      three levels — workflow, job, step — and any of them reaches the pytest
#      process. `PYTEST_ADDOPTS: "-k nothing"` next to REQUIRE_SWISS_EPHEMERIS
#      leaves the run line reading `pytest tests/ -q`, every existing guard green,
#      and zero tests executed.
#   2. `addopts` in pytest's own config. This repo configures pytest in
#      pyproject.toml; `addopts = "-k not_corpus"` there narrows every pytest
#      invocation in the repo, including the accuracy job's, with no workflow
#      change at all.
#
# This is the deliberate-evasion class rather than the accidental-edit class the
# run-line checks target, which is exactly why it is worth closing: an accidental
# narrowing is at least visible in the diff of the line that runs the suite.
#
# PARSED, NOT GREPPED, on both arms — for the same reason the rest of this file
# parses: `# PYTEST_ADDOPTS: "-k nothing"` in a comment, or the string inside an
# `echo`, must not be mistaken for the real thing.

_ADDOPTS_ENV = "PYTEST_ADDOPTS"
_PYPROJECT = _REPO_ROOT / "pyproject.toml"


def _addopts_env_declarations(document: dict, job: dict) -> list[str]:
    """Every place ``PYTEST_ADDOPTS`` is set in scope for the accuracy job.

    Workflow-, job- and step-level ``env:`` are all checked because GitHub Actions
    resolves all three into the step's environment; leaving any of them out is a
    hole the shape of the whole finding.
    """
    found: list[str] = []

    workflow_env = document.get("env")
    if isinstance(workflow_env, dict) and _ADDOPTS_ENV in workflow_env:
        found.append(f"workflow-level env: {workflow_env[_ADDOPTS_ENV]!r}")

    job_env = job.get("env")
    if isinstance(job_env, dict) and _ADDOPTS_ENV in job_env:
        found.append(f"job-level env: {job_env[_ADDOPTS_ENV]!r}")

    for step in _steps(job):
        label = step.get("name") or "<unnamed step>"
        step_env = step.get("env")
        if isinstance(step_env, dict) and _ADDOPTS_ENV in step_env:
            found.append(f"step {label!r} env: {step_env[_ADDOPTS_ENV]!r}")
        run = step.get("run")
        if run and _run_body_names_addopts(str(run)):
            found.append(f"step {label!r} run: names {_ADDOPTS_ENV}")

    return found


# The pyproject arm is the standalone checker's, imported rather than duplicated —
# see _COLLECTION_CHECKER above. These aliases keep the assertions below readable
# while leaving exactly one implementation of the parsing.
_addopts_tokens = _COLLECTION_CHECKER.addopts_tokens
_narrowing_addopts = _COLLECTION_CHECKER.narrowing_addopts


def test_addopts_parser_discriminates() -> None:
    """Fixtures both addopts arms must get right — each is something a textual
    scan of the workflow or of pyproject.toml gets wrong."""
    # --- the run-body arm ----------------------------------------------------
    # PRESENCE, not argv position. The position-based version of this check missed
    # `>> "$GITHUB_ENV"` -- the ONLY form that persists to a later step, and the one
    # a sibling pytest step actually runs under (PR #66 round-2 review). Every form
    # below is refused, including a bare mention.
    for run in (
        'echo "PYTEST_ADDOPTS=--collect-only" >> "$GITHUB_ENV"',
        "echo PYTEST_ADDOPTS=--co >> $GITHUB_ENV",
        'PYTEST_ADDOPTS=-k nothing uv run pytest tests/',
        'export PYTEST_ADDOPTS="-k nothing"',
        'REQUIRE_SWISS_EPHEMERIS=1 PYTEST_ADDOPTS=-x pytest tests/',
        'echo "PYTEST_ADDOPTS=-k nothing"',
        'echo "PYTEST_ADDOPTS"',
    ):
        assert _run_body_names_addopts(run), f"run body not flagged: {run!r}"

    # A run body that does not name it is clean, including a $GITHUB_ENV write of a
    # DIFFERENT variable -- the rule is about this variable, not about the idiom.
    for run in (
        "pytest tests/ -q",
        "uv sync --frozen --extra dev",
        'echo "REQUIRE_SWISS_EPHEMERIS=1" >> "$GITHUB_ENV"',
    ):
        assert not _run_body_names_addopts(run), f"clean run body flagged: {run!r}"

    def job_and_document(text: str) -> tuple[dict, dict]:
        document = yaml.safe_load(text)
        job = _job(document, _JOB)
        assert job is not None
        return document, job

    # The three env levels GitHub Actions resolves, each of which reaches pytest.
    for text, where in (
        (
            'env:\n  PYTEST_ADDOPTS: "-k nothing"\n'
            "jobs:\n  swiss-ephemeris:\n    steps: []\n",
            "workflow-level",
        ),
        (
            "jobs:\n  swiss-ephemeris:\n"
            '    env:\n      PYTEST_ADDOPTS: "-k nothing"\n    steps: []\n',
            "job-level",
        ),
        (
            "jobs:\n  swiss-ephemeris:\n    steps:\n"
            "      - name: Run the full suite against real Swiss data\n"
            '        env:\n          PYTEST_ADDOPTS: "-k nothing"\n'
            "        run: pytest tests/ -q\n",
            "step",
        ),
    ):
        document, job = job_and_document(text)
        assert _addopts_env_declarations(document, job), (
            f"a {where} PYTEST_ADDOPTS was not detected"
        )

    # A COMMENT mentioning it is not a declaration — the whole reason this parses.
    document, job = job_and_document(
        "jobs:\n  swiss-ephemeris:\n    steps:\n"
        '      # env:\n      #   PYTEST_ADDOPTS: "-k nothing"\n'
        "      - run: pytest tests/ -q\n"
    )
    assert _addopts_env_declarations(document, job) == []

    # An ECHO of it inside a run body IS now a declaration — this assertion was
    # inverted before (PR #66 round-2 review). `echo "PYTEST_ADDOPTS=..." >>
    # "$GITHUB_ENV"` is GitHub's own cross-step mechanism and the ONLY form that
    # persists to a later step; telling it apart from a harmless echo means
    # modelling shell redirection, and that modelling is exactly what let it
    # through. Presence is the rule for a run body now.
    for body in (
        '      - run: echo "PYTEST_ADDOPTS=-k nothing"\n',
        '      - run: echo "PYTEST_ADDOPTS=--collect-only" >> "$GITHUB_ENV"\n',
        '      - run: PYTEST_ADDOPTS="-k nothing" pytest tests/ -q\n',
    ):
        document, job = job_and_document(
            "jobs:\n  swiss-ephemeris:\n    steps:\n" + body
        )
        assert _addopts_env_declarations(document, job), f"not flagged: {body!r}"

    # A run body that does not name it stays clean, including a $GITHUB_ENV write
    # of a different variable.
    document, job = job_and_document(
        "jobs:\n  swiss-ephemeris:\n    steps:\n"
        '      - run: echo "REQUIRE_SWISS_EPHEMERIS=1" >> "$GITHUB_ENV"\n'
    )
    assert _addopts_env_declarations(document, job) == []

    # --- the pyproject arm ---------------------------------------------------
    narrowing_forms = (
        '[tool.pytest.ini_options]\naddopts = "-k not_corpus"\n',
        '[tool.pytest.ini_options]\naddopts = "-m \'not accuracy\'"\n',
        '[tool.pytest.ini_options]\naddopts = "--ignore=tests/test_independent_reference_corpus.py"\n',
        '[tool.pytest.ini_options]\naddopts = ["-q", "--deselect", "tests/test_swiss_ephemeris.py"]\n',
        '[tool.pytest.ini_options]\naddopts = "--collect-only"\n',
        # A single list entry holding two arguments, which pytest shell-splits.
        '[tool.pytest.ini_options]\naddopts = ["-k not_corpus"]\n',
    )
    for text in narrowing_forms:
        tokens = _addopts_tokens(tomllib.loads(text))
        assert _narrowing_addopts(tokens), f"narrowing addopts not detected: {text!r}"

    legitimate_forms = (
        "",
        "[tool.pytest.ini_options]\n",
        '[tool.pytest.ini_options]\naddopts = "-q --strict-markers"\n',
        '[tool.pytest.ini_options]\naddopts = ["-q", "--color=no"]\n',
        # Only in a COMMENT — invisible to a parser, which is the point.
        '[tool.pytest.ini_options]\n# addopts = "-k not_corpus"\n',
        # A marker DEFINITION is not a marker SELECTION.
        '[tool.pytest.ini_options]\nmarkers = ["accuracy: swiss data"]\n',
    )
    for text in legitimate_forms:
        tokens = _addopts_tokens(tomllib.loads(text))
        assert _narrowing_addopts(tokens) == [], (
            f"legitimate pyproject was flagged as narrowing: {text!r}"
        )


def test_swiss_job_does_not_inject_pytest_addopts() -> None:
    """`PYTEST_ADDOPTS` anywhere in scope for the accuracy job is refused.

    Deliberately a PRESENCE check rather than an "is this particular addopts
    narrowing" check. Deciding whether an arbitrary addopts string removes tests
    means reimplementing pytest's own argument parsing — an unbounded surface, and
    the same race this file's module comment records losing three times. The
    accuracy job has no legitimate need to inject pytest arguments through the
    environment: whatever it should pass belongs on the run line, in the diff,
    where every other check in this file can see it.
    """
    document = yaml.safe_load(_TEST_WORKFLOW.read_text(encoding="utf-8"))
    job = _job(document, _JOB)
    assert job is not None
    test_addopts_parser_discriminates()

    declarations = _addopts_env_declarations(document, job)
    assert not declarations, (
        f"{_ADDOPTS_ENV} is set in scope for the `{_JOB}` job: {declarations}. pytest "
        "reads arguments from that variable, so it can narrow or disable the run "
        "while the suite step's run line still reads `pytest tests/ -q` and every "
        "other guard in this file stays green. Put arguments on the run line, where "
        "they are visible in the diff and covered by "
        "test_swiss_job_reaches_every_swiss_gated_module."
    )


def test_pytest_config_does_not_narrow_collection() -> None:
    """pytest's own `addopts` must not filter what the accuracy job collects.

    `addopts` in pyproject.toml applies to EVERY pytest invocation in the repo,
    including this job's, with no workflow change at all — so a narrowing value
    there disarms the accuracy gate through a file nothing in this guard's
    workflow-parsing arm would ever read.

    Parsed with tomllib, never grepped: `# addopts = "-k not_corpus"` is a comment
    and must stay invisible.
    """
    document = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    tokens = _addopts_tokens(document)
    narrowing = _narrowing_addopts(tokens)
    assert not narrowing, (
        f"pyproject.toml's [tool.pytest.ini_options] addopts carries narrowing "
        f"flag(s) {narrowing} (parsed: {tokens}). That applies to every pytest run "
        f"in this repo, so it removes assertions from the `{_JOB}` accuracy job "
        "without touching the workflow at all."
    )

    # FAIL CLOSED on a config file neither this guard nor the standalone checker
    # parses. pytest reads ini options from several files; only the repo-root
    # pyproject.toml exists here. If another appears it must be covered
    # deliberately rather than quietly left out of a check that claims to cover
    # the configuration.
    #
    # ANYWHERE IN THE TREE, not just the root: pytest resolves its inifile by
    # walking UP from the common ancestor of its arguments, so `tests/pytest.ini`
    # wins over the root pyproject.toml for `pytest tests/`. Measured before that
    # scan existed — the checker exited 0 "OK" while `pytest tests/ -q` collected
    # 937 tests and executed none.
    unparsed = _COLLECTION_CHECKER.unparsed_config_files(_REPO_ROOT)
    assert not unparsed, (
        f"{unparsed} exist(s) in this repository. pytest reads `addopts` from those "
        "files too, and only the ROOT pyproject.toml is parsed — so this would "
        "report green while a narrowing addopts sat somewhere nothing looks, and a "
        "copy inside tests/ or ci/tests/ would take precedence over the root file "
        "outright. Extend ci/check_pytest_collection.py to parse them."
    )


_COLLECTION_CHECKER_SCRIPT = "ci/check_pytest_collection.py"

# The events a real change arrives on. A step that is skipped for both of these
# never runs when it matters, whatever else the workflow says.
_REAL_CHANGE_EVENTS = ("push", "pull_request")


def _workflow_documents(repo_root: Path = _REPO_ROOT) -> list[tuple[Path, dict]]:
    """Every parsed workflow document, as (path, document) pairs.

    Scope comes from ``ci/workflow_scope.py`` -- git, both suffixes. This used
    to glob ``.github/workflows/*.yml``, and everything downstream of it is an
    assertion of the form "no workflow does X", which a half-enumeration
    satisfies by not looking. GitHub Actions runs ``.yaml`` identically, so a
    narrowing ``PYTEST_ADDOPTS``, an injected ``$GITHUB_ENV`` write, or a
    deleted accuracy step could all have sat in a ``.yaml`` workflow and been
    reported clean by every guard in this file.
    """
    documents: list[tuple[Path, dict]] = []
    for workflow_path in _workflow_scope.workflow_paths(repo_root):
        document = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        if isinstance(document, dict):
            documents.append((workflow_path, document))
    return documents


def _job_matrix_yields_a_run(job: dict) -> bool:
    """Whether the job's ``strategy.matrix``, if any, produces at least one run.

    A job whose matrix is empty is DECLARED and never executes — `strategy:
    {matrix: {include: []}}` is a job that appears in the workflow, appears in
    this guard's scan, and runs zero times.

    FAILS CLOSED on anything it cannot evaluate: a computed
    ``matrix: ${{ fromJSON(...) }}``, a non-list axis, or an ``exclude:`` block
    (whose removals could empty the product, and modelling them exactly means
    reimplementing GitHub's matrix expansion). STATED BOUND: this repo has no
    matrix on any job today, so none of those refusals is reachable now; if one
    is ever added, extending this is the deliberate act that clears it.
    """
    strategy = job.get("strategy")
    if strategy is None:
        return True
    if not isinstance(strategy, dict):
        return False
    if "matrix" not in strategy:
        return True

    matrix = strategy["matrix"]
    if not isinstance(matrix, dict) or "exclude" in matrix:
        return False

    include = matrix.get("include")
    include_count = len(include) if isinstance(include, list) else 0
    axes = {key: value for key, value in matrix.items() if key != "include"}
    if not axes:
        return include_count > 0

    product = 1
    for values in axes.values():
        if not isinstance(values, list):
            return False
        product *= len(values)
    return product > 0 or include_count > 0


def _discards_failure(mapping: dict) -> bool:
    """Whether ``continue-on-error`` would throw this job's or step's failure away.

    Fails closed on an expression: an unevaluable value is not a proven ``false``.
    """
    value = mapping.get("continue-on-error")
    return value is not None and value is not False and str(value).strip().lower() != "false"


def _why_not_enforced(job: dict, step: dict, event_name: str) -> str | None:
    """Why `step` would not actually enforce anything on `event_name`, or None.

    ONE META-LEVEL UP FROM THE STEP'S OWN `if:` (PR #66 review). Three ways a
    step that is present in the workflow enforces nothing, and the previous rule
    checked only the first:

      1. the STEP's `if:` skips it;
      2. the HOSTING JOB's `if:` or matrix means the job never runs — a step
         inside a job that does not run does not run, and the step's own `if:`
         says nothing whatever about that;
      3. `continue-on-error` at either level, which is worse than not running:
         the step executes, REFUSES, and the workflow reports success anyway.

    Returns a reason rather than a bool so the assertion can say which of the
    three fired, on which mapping.
    """
    for label, mapping in (("job", job), ("step", step)):
        try:
            runs = _runs_for_event(mapping, event_name)
        except _UnsupportedExpression as exc:
            # The contract on _runs_for_event: an expression this guard cannot
            # evaluate must fail the test, never be treated as "probably fine".
            return (
                f"the {label}'s `if:` ({_condition(mapping)!r}) is outside the "
                f"subset this guard can evaluate ({exc}), so it cannot be "
                f"certified as running on {event_name}"
            )
        if not runs:
            return (
                f"the {label}'s `if:` ({_condition(mapping)!r}) is False for "
                f"{event_name}, so it does not run on a real change"
            )
        if _discards_failure(mapping):
            return (
                f"the {label} is `continue-on-error: "
                f"{mapping.get('continue-on-error')!r}`, so this check can refuse "
                "and the workflow still reports success"
            )

    if not _job_matrix_yields_a_run(job):
        return (
            f"the job's `strategy` ({job.get('strategy')!r}) does not provably "
            "yield at least one run, so the step may never execute"
        )
    return None


def _plain_python_invocations(
    documents: list[tuple[Path, dict]]
) -> list[tuple[Path, str, dict, dict, str]]:
    """Every (path, job_name, job, step, run) invoking the checker as PLAIN python.

    Not through pytest: a narrowing pytest configuration would disarm it exactly
    as it disarms every other test, which is the hole it exists to close.
    """
    invocations: list[tuple[Path, str, dict, dict, str]] = []
    for workflow_path, document in documents:
        for job_name, job in (document.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            for step in _steps(job):
                run = str(step.get("run", ""))
                if not run or not _invokes(run, "python", _COLLECTION_CHECKER_SCRIPT):
                    continue
                if any(
                    "pytest" in tokens
                    for tokens in _commands(run)
                    if _COLLECTION_CHECKER_SCRIPT in " ".join(tokens)
                ):
                    continue
                invocations.append((workflow_path, job_name, job, step, run))
    return invocations


def _enforced_invocations(
    documents: list[tuple[Path, dict]]
) -> tuple[list[tuple[Path, str, dict, dict, str]], list[str]]:
    """(invocations that really run and really count, reasons the others do not)."""
    enforced: list[tuple[Path, str, dict, dict, str]] = []
    rejections: list[str] = []
    for workflow_path, job_name, job, step, run in _plain_python_invocations(documents):
        reasons = [
            reason
            for event in _REAL_CHANGE_EVENTS
            if (reason := _why_not_enforced(job, step, event)) is not None
        ]
        if reasons:
            rejections.append(f"{workflow_path.name} job {job_name!r}: {reasons[0]}")
        else:
            enforced.append((workflow_path, job_name, job, step, run))
    return enforced, rejections


def test_a_workflow_step_runs_the_standalone_collection_check() -> None:
    """The standalone checker is inert unless a workflow actually runs it.

    `test_pytest_config_does_not_narrow_collection` above covers the pyproject arm
    from inside pytest, and CANNOT cover the two cases where the narrowing config
    stops pytest running the guard itself (measured: `addopts = "--collect-only"`
    exits 0 having executed nothing; `addopts = "-k 'not narrow'"` exits 0 with the
    guard deselected). ci/check_pytest_collection.py closes those — but only while
    some step actually invokes it, and only while that step is a PLAIN python
    command rather than another pytest invocation, which the same config would
    disarm in exactly the same way.

    This is the same argument as the module docstring's: a check nothing runs is a
    check that is not there. `test_ci_runs_gate_regression_suite.py` makes it for
    `ci/tests/`; this makes it for the one check that has to live outside pytest.
    """
    documents = _workflow_documents()

    any_invocation = [
        (path, job_name)
        for path, document in documents
        for job_name, job in (document.get("jobs") or {}).items()
        if isinstance(job, dict)
        for step in _steps(job)
        if step.get("run") and _invokes(str(step["run"]), "python", _COLLECTION_CHECKER_SCRIPT)
    ]
    assert any_invocation, (
        f"no workflow step invokes {_COLLECTION_CHECKER_SCRIPT}. That script is the "
        "only check covering a pytest configuration that stops pytest running the "
        "tests -- including this file. Unrun, it protects nothing."
    )

    # It must not be smuggled in THROUGH pytest: a narrowing addopts would disarm
    # it exactly as it disarms every other test.
    assert _plain_python_invocations(documents), (
        f"{_COLLECTION_CHECKER_SCRIPT} is only ever invoked through pytest. The whole "
        "point of it is to run where a narrowing pytest configuration cannot reach; "
        "running it under pytest reintroduces the hole it exists to close."
    )

    # At least one invoking step must actually ENFORCE on a real push/PR, and must
    # self-test the detector first -- same ordering rule as the ephemeris fetcher's
    # `--self-test`: a detector that has stopped discriminating must never get as
    # far as certifying the real configuration.
    #
    # "Enforce", not merely "not skipped by its own `if:`" -- see _why_not_enforced.
    # The step's own condition is one of three ways it can be disarmed, and it was
    # the only one this checked before (PR #66 review). The hosting JOB's `if:` and
    # matrix decide whether the step runs at all, and `continue-on-error` at either
    # level decides whether its refusal counts for anything.
    enforced, rejections = _enforced_invocations(documents)
    assert enforced, (
        f"no step invoking {_COLLECTION_CHECKER_SCRIPT} actually enforces it on a "
        "real change:\n"
        + "\n".join(f"  - {rejection}" for rejection in rejections)
    )
    assert any(
        _invokes(run, "python", _COLLECTION_CHECKER_SCRIPT, "--self-test")
        for _path, _job_name, _job, _step, run in enforced
    ), (
        f"no enforced step runs `{_COLLECTION_CHECKER_SCRIPT} --self-test`. A "
        "detector that has stopped discriminating must not be able to certify the "
        "real configuration -- the same ordering ci/fetch_swiss_ephemeris.py uses."
    )


# ---------------------------------------------------------------------------
# ONE META-LEVEL UP: the step's `if:` is not the only thing that disarms it
# ---------------------------------------------------------------------------
#
# PR #66's review noted this gap and it is closed here. The reachability arm of
# test_a_workflow_step_runs_the_standalone_collection_check evaluated the STEP's
# own `if:` and nothing else — so a step with no `if:` at all was certified
# "reachable on push and pull_request" no matter what its hosting JOB said.
#
# A step inside a job that does not run does not run. Job-level `if:` is not a
# hypothetical idiom here either: THREE of this repo's jobs already use it
# (`swiss-ephemeris`, `production-image-ephemeris` and `docker-test-image` all
# carry `if: github.event_name != 'schedule'`), so adding one to `test` is an
# ordinary-looking edit that the old guard would have waved through.
#
# `continue-on-error` is in the same family and is arguably worse: the step runs,
# REFUSES, and the workflow reports success anyway. A check whose failure is
# discarded is not enforcing anything, so it is not counted as enforcing.


def test_why_not_enforced_rejects_a_disabled_hosting_job() -> None:
    """The JOB's enablement, not just the step's.

    Drives the real predicate the guard uses, against synthetic shapes, so a
    regression in it reds here with a readable reason rather than only showing
    up as a missing rejection three functions away.
    """
    step = {"run": "python ci/check_pytest_collection.py"}

    always = {"steps": [step]}
    assert _why_not_enforced(always, step, "push") is None, (
        "a job with no `if:` hosting a step with no `if:` must be enforced"
    )

    for job_if in (False, "${{ false }}", "github.event_name == 'schedule'"):
        job = {"if": job_if, "steps": [step]}
        reason = _why_not_enforced(job, step, "push")
        assert reason is not None, (
            f"a step in a job with `if: {job_if!r}` was certified as enforced on "
            "push — the job never runs, so neither does the step"
        )
        assert "job" in reason


def test_why_not_enforced_rejects_a_discarded_failure() -> None:
    """`continue-on-error` at either level means the refusal changes nothing."""
    step = {"run": "python ci/check_pytest_collection.py"}

    assert _why_not_enforced({"steps": [step]}, dict(step, **{"continue-on-error": True}), "push")
    assert _why_not_enforced({"steps": [step], "continue-on-error": True}, step, "push")
    # Fail closed on an expression: this guard cannot evaluate it, so it must
    # not certify it.
    assert _why_not_enforced(
        {"steps": [step]}, dict(step, **{"continue-on-error": "${{ github.actor }}"}), "push"
    )
    # An explicit false is the documented default and must NOT red.
    assert _why_not_enforced(
        {"steps": [step], "continue-on-error": False},
        dict(step, **{"continue-on-error": False}),
        "push",
    ) is None


def test_why_not_enforced_rejects_a_matrix_that_yields_no_run() -> None:
    """A job whose matrix is empty is DECLARED and never executes."""
    step = {"run": "python ci/check_pytest_collection.py"}

    for matrix in (
        {"include": []},
        {"python": []},
        {"python": ["3.11"], "os": []},
        # Computed at run time — unevaluable here, so not certifiable here.
        "${{ fromJSON(needs.setup.outputs.matrix) }}",
    ):
        job = {"strategy": {"matrix": matrix}, "steps": [step]}
        assert _why_not_enforced(job, step, "push") is not None, (
            f"a job with `strategy.matrix: {matrix!r}` was certified as enforced, "
            "but it produces no run at all"
        )

    ordinary = {"strategy": {"matrix": {"python": ["3.10", "3.11"]}}, "steps": [step]}
    assert _why_not_enforced(ordinary, step, "push") is None, (
        "an ordinary non-empty matrix was rejected"
    )
    assert _why_not_enforced({"strategy": {"fail-fast": False}, "steps": [step]}, step, "push") is None


def test_disabling_the_hosting_job_in_the_REAL_workflow_is_caught() -> None:
    """The mutation the old guard waved through, against the real file.

    This is the test that pins the guard rather than the helper: it takes the
    actual workflow documents, applies the single edit that disarms the
    collection check, and asserts the enforcement scan now finds nothing left.
    Under the step-only reachability rule this mutation changed nothing, because
    the step's own `if:` is still absent.
    """
    documents = _workflow_documents()
    enforced, _rejections = _enforced_invocations(documents)
    assert enforced, "sanity: the real workflows must enforce the check before mutation"

    mutated: list[tuple[Path, dict]] = []
    touched = 0
    for path, document in documents:
        copy = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in (copy.get("jobs") or {}).values():
            if not isinstance(job, dict):
                continue
            for step in _steps(job):
                if _invokes(str(step.get("run", "")), "python", _COLLECTION_CHECKER_SCRIPT):
                    job["if"] = "github.event_name == 'schedule'"
                    touched += 1
        mutated.append((path, copy))

    assert touched, "no step invoking the checker was found to mutate"
    still_enforced, rejections = _enforced_invocations(mutated)
    assert not still_enforced, (
        "disabling the HOSTING JOB left the collection check certified as "
        "enforced. The step's own `if:` is untouched by this edit, which is "
        "exactly why the step-only rule missed it."
    )
    assert rejections, "the scan rejected the invocation without saying why"


def test_manifest_and_goldens_are_committed() -> None:
    assert (_REPO_ROOT / _FETCHER).is_file(), f"{_FETCHER} is missing"
    assert (_REPO_ROOT / "ci" / "swiss_ephemeris.json").is_file(), (
        "ci/swiss_ephemeris.json (the checksum-pinned data manifest) is missing"
    )
    assert (_REPO_ROOT / "tests" / "goldens" / "swiss_ephemeris_goldens.json").is_file(), (
        "tests/goldens/swiss_ephemeris_goldens.json is missing — the Swiss accuracy "
        "assertions have nothing to compare against"
    )


def test_workflow_documents_reads_yaml_as_well_as_yml(tmp_path):
    """RED under the old ``*.yml`` glob, and this file is where it mattered most.

    Every guard in this module is an assertion of the form "no workflow does
    X" -- no narrowing ``PYTEST_ADDOPTS``, no ``$GITHUB_ENV`` write, no deleted
    accuracy step, no unpinned uv. A half-enumeration satisfies all of them by
    not looking, and a ``.yaml`` workflow is a file GitHub Actions executes
    identically. So the accuracy gate could have been switched off from a file
    this guard reported clean, which is the precise failure the module exists
    to prevent, arriving through the module's own scope.

    Not committed: ``--others`` keeps an untracked workflow in scope, because
    the cheapest moment to catch this is the commit that introduces the file.
    """
    body = (
        "name: Fixture\n"
        "on: [push]\n"
        "jobs:\n"
        "  t:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo hello\n"
    )
    root = tmp_path / "wf-fixture"
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "extra.yaml").write_text(
        body, encoding="utf-8", newline="\n"
    )
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)

    documents = _workflow_documents(root)
    assert [path.name for path, _ in documents] == ["extra.yaml"], (
        f"a .yaml workflow was not parsed: {[p.name for p, _ in documents]}"
    )


def test_this_repositorys_workflow_documents_are_non_vacuous():
    """The floor: every assertion in this module is vacuous over zero documents."""
    documents = _workflow_documents()
    assert len(documents) >= 3, (
        f"only {len(documents)} workflow document(s) parsed for this repository "
        "-- the enumeration is broken, not the tree"
    )
    assert all(path.suffix in {".yml", ".yaml"} for path, _ in documents), sorted(
        path.name for path, _ in documents
    )
