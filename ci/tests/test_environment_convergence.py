"""Regression guard: ONE dependency resolve, validated where it ships.

WHY THIS FILE EXISTS
--------------------
This repository resolved its dependencies in more than one way at once, and the
resolve the test suite validated was not the resolve that shipped. Measured on
2026-08-05, four distinct installed sets existed simultaneously:

  * the ``test`` jobs in ``test.yml`` and ``publish.yml`` installed with a
    floating ``pip install -e ".[dev]"`` — which ignores ``uv.lock`` entirely
    and resolves whatever is newest at the moment the job runs;
  * the ``swiss-ephemeris`` job and ``Dockerfile.test`` installed
    ``uv sync --frozen --extra dev``;
  * the shipped ``Dockerfile`` installs ``uv sync --frozen --no-dev``;
  * a developer checkout's ``.venv`` was a fourth resolve again, on a
    different interpreter entirely.

The floating set differed from the shipped set on **13 packages that ship**
(fastapi 0.141.1 vs 0.136.3, uvicorn 0.52.1 vs 0.48.0, anyio, certifi, cffi,
charset-normalizer, click, idna, pytz, typing-extensions, websockets,
annotated-types, annotated-doc). So the suite that gates every merge was
certifying a dependency set no deployment ever ran.

THE LOCK FORKED ON THE INTERPRETER
---------------------------------
A universal ``uv.lock`` is not necessarily one resolve — it can FORK on the
interpreter, and this one did while ``requires-python`` read ``>=3.10``.
Measured then: of 73 locked dependency names, exactly two resolved to more
than one version, both split on the same boundary, ``python_full_version``
3.11:

    numpy            2.2.6  (< 3.11)   /  2.4.6  (>= 3.11)
    timezonefinder   8.2.0  (< 3.11)   /  8.2.5  (>= 3.11)

The ``< 3.11`` side was a resolve for an interpreter nothing here builds or
tests, and it was also the side the security updater resolved on — see
``test_requires_python_floor_is_the_pinned_interpreter`` below.
``requires-python`` now reads exactly ``>=`` the pinned interpreter, and the
regenerated lock holds 73 entries (72 dependencies and the project itself),
each at one version, with no ``resolution-markers`` at all. It can fork again
the day a dependency's newest release drops an interpreter ``requires-python``
still admits, and wherever it forks "the locked set" does not name a single
set of versions until the interpreter is fixed. A base-image tag edit also
changes the interpreter an image installs for — and with it the wheels and
the marker-gated packages — while ``pyproject.toml`` and ``uv.lock`` stay
byte-identical. ``.github/dependabot.yml`` watches the ``docker`` ecosystem
weekly precisely so the pinned base image gets CVE-driven bumps, so that edit
arrives on its own schedule.

WHAT THE FORK DID *NOT* ESTABLISH — READ BEFORE RE-ARGUING IT
-------------------------------------------------------------
An earlier revision of this file claimed the consequence was numeric: that
``numpy`` sits in the served compute path via
``jhora/horoscope/chart/strength.py`` (Shadbala/Bhavabala rounded and summed
through ``np.floor``/``np.rint``/``np.around``) and
``jhora/horoscope/chart/ashtakavarga.py`` (varga tables summed through
``np.asarray(...).sum(axis=0)`` and ``np.multiply``).

**That claim is false, and it is recorded here so it is not reintroduced.**
This project computes Shadbala, Bhavabala and Ashtakavarga *itself*, in
``bphs_core/strength.py``, which contains no numpy at all. ``bphs_core``
imports only ``drik``, ``charts``, ``const`` and ``utils``; ``charts.py`` in
turn imports only ``math``/``drik``/``const``/``utils``/``house``. Both cited
modules ship inside the dependency and are never imported.

Measured 2026-08-05 by wrapping ``np.floor``/``np.rint``/``np.around``/
``np.sum``/``np.asarray``/``np.multiply``/``np.array``/``np.where`` with
counters, with the instrument PROVEN LIVE BEFORE ANY ZERO WAS READ — direct
calls moved every counter, and a direct call into the dependency's own
``get_ashtaka_varga`` moved ``asarray`` 0 -> 1, so a zero below is absence and
not a dead probe:

    every route: the 15 /v1/* plus /healthz     ..  every counter 0
      and /source, 17 of 17 answering 200/202,
      both async scan jobs polled to terminal
      status so worker-thread compute counted
    the full 697-test suite, whole run ...........  2 numpy calls, both
                                                    at import, 0 during
                                                    test execution
    jhora.horoscope.chart.strength ...............  never in sys.modules
    jhora.horoscope.chart.ashtakavarga ...........  never in sys.modules

Those two calls are one expression — the ``house_owners = np.where(...)``
assignment in ``jhora/const.py``, an integer index extraction building a
constant lookup table. Cited by symbol, not by line: it sits in a vendored
dependency whose line numbers move with the pinned version. Whether crossing
the fork perturbed it was measured rather than assumed in either direction: the
expression on the same table yields ``[2, 5, 3, 1, 0, 3, 5, 2, 4, 6, 6, 4]``
under numpy 2.2.6 on python 3.10 and under numpy 2.4.6 on python 3.11, same
values and same element types.

WHAT THIS GUARD ACTUALLY RESTS ON
---------------------------------
What the gating suite tests must be what ships — the 13-package divergence
above. That is the whole of it, and it deliberately does not depend on the
numpy question resolving either way. Two supporting reasons for declaring the
interpreter in exactly one place: a fork leaves "the locked set" ambiguous
while the interpreter floats, and reachability is a property of *today's*
code, not a guarantee — the day something here calls into the dependency's own
strength/ashtakavarga modules, or a new dependency puts float arithmetic on
the served path, a fork stops being inert with nothing in the diff to
announce it.

WHAT THIS GUARD ASSERTS
-----------------------
1. The running interpreter is the pinned one (``.python-version``) — because a
   lock that forks is only one resolve once the interpreter is fixed — and
   ``requires-python`` is exactly ``>=`` that interpreter, with ``uv.lock``
   resolved for the same range, so the lock is never resolved for, and no
   updater resolves on, an interpreter nothing here runs.
2. Every installed distribution matches what ``uv.lock`` resolves FOR THAT
   INTERPRETER, and the comparison provably included the pins named in
   ``_ACCURACY_CRITICAL`` below.
3. Every CI job that runs the suite installs from the frozen lock and takes
   its interpreter from ``.python-version`` — so the divergence cannot be
   reintroduced in a workflow edit.
4. Both Dockerfiles' base images are on that same pinned interpreter — so the
   base-image bump above cannot silently move the interpreter an image
   installs for.
5. The uv BUILD TOOL is one version across CI and both images, and no workflow
   installs it from a floating index resolve.
6. Every job that installs the frozen lock also asserts the lock is FRESH.

THE INSTALLER IS PART OF THE RESOLVE TOO
----------------------------------------
Everything above pins what is installed and the interpreter it is installed
for. It said nothing about the tool doing the installing. Measured 2026-08-21
on this repository, three CI steps installed uv with a bare
``python -m pip install --upgrade uv`` — ``test.yml``'s ``test`` and
``swiss-ephemeris`` jobs and ``publish.yml``'s ``test`` job — which resolves
whatever is newest on the index at the moment the job runs, while ``Dockerfile``
and ``Dockerfile.test`` both install uv from a digest-pinned
``FROM ghcr.io/astral-sh/uv:<version>@sha256:<digest> AS uv`` stage. So CI could
resolve, sync and test through a *different* uv than the one that builds the
shipped image — the same "the gating suite is not running what ships" shape as
the 13-package divergence, one layer further out.

**Which reference is the source of truth, and why the equality is the
maintenance mechanism rather than a chore.** The Dockerfile reference is
watched: ``.github/dependabot.yml`` runs the ``docker`` ecosystem weekly and
that ecosystem parses ``FROM`` instructions, so a uv release arrives as a pull
request on its own schedule. The workflow's ``version:`` input is watched by
**nothing** — dependabot's ``github-actions`` ecosystem bumps the ``uses:`` ref
of an action, never the value of an input to it. A pin nobody watches is a pin
that rots. Asserting the two are EQUAL is what fixes that: the watched
reference moves first, this test goes red, and the unwatched one has to follow
inside the same reviewed change. That is deliberately the inverse of
``test_dockerfile_image_pins.py::test_the_build_tool_is_installed_from_a_pinned_stage``,
which asserts the *shape* and never a version precisely so it does not fail on
the bumps it exists to enable — nothing here pins a version literal either. The
expected value is DERIVED from the Dockerfiles, so the only thing that can fail
is disagreement.

WHY A SEPARATE FRESHNESS CHECK, AND NOT ``uv sync --locked``
------------------------------------------------------------
``--frozen`` installs ``uv.lock`` exactly as committed and never consults
``pyproject.toml``, so a dependency edit that never got a ``uv lock`` run is
installed and tested as though it had not happened. Measured 2026-08-21 on a
scratch copy of this project's own ``pyproject.toml``/``uv.lock`` pair, with
``pyjhora==4.8.7`` edited to ``==4.8.6`` in ``pyproject.toml`` alone and
``uv.lock`` left byte-identical:

    uv lock --check ..............  exit 1, "the lockfile needs to be updated"
    uv export --frozen ...........  exit 0  <-- the silent pass
    uv export --locked ...........  exit 2

and on the unmodified pair all three exit 0. So the drift is real and
``--frozen`` is blind to it by design.

The fix is an ADDITIONAL ``uv lock --check`` step, not a flip of the install to
``uv sync --locked``, for three reasons. (1) The shipped ``Dockerfile`` installs
with ``uv sync --frozen``; this project's rule is to run the EXACT command CI
runs rather than an equivalent, and flipping only CI would put the image and
its gate on two different install paths — reintroducing a divergence in the act
of closing one. (2) It keeps the ``installs_frozen`` arm of
``test_every_workflow_job_that_runs_the_suite_installs_from_the_frozen_lock``
below intact rather than requiring it to be taught to accept a second spelling.
(3) A stale lock then reports itself as a stale lock, in its own named step,
instead of surfacing as an install failure. Measured cost on the in-sync pair:
``uv lock --check`` resolves offline in ~1 ms and the whole invocation returns
in under 0.1 s.

WHY STRUCTURE AND MEASUREMENT, NOT A LINE-SCAN
----------------------------------------------
Every assertion below reads a parsed representation: ``uv.lock`` and
``pyproject.toml`` through a TOML parser, the workflows through PyYAML, the
Dockerfiles through the instruction parser already proven by
``test_image_bakes_ephemeris.py`` (reused by path, not imported as a package —
``ci/`` has no ``__init__.py`` by design). A ``grep`` for ``uv sync --frozen``
matches the string in a comment, including the comment explaining this guard.

And the comparison itself is asserted to be non-empty: "no differences found"
is vacuously true of a comparison that examined nothing, so the number of
distributions compared is printed and floored against the project's own
declared runtime dependencies.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import sys
import tomllib
from importlib import metadata

import pytest
import yaml

# `packaging` is deliberately NOT declared in the dev extras: it is a hard
# dependency of pytest itself, so it cannot be absent in any environment
# capable of running this file. The TOML parser is stdlib `tomllib`, present on
# every interpreter requires-python admits.
from packaging.markers import Marker
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_LOCK = _REPO_ROOT / "uv.lock"
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_PYTHON_VERSION_FILE = _REPO_ROOT / ".python-version"
_DOCKERFILES = (_REPO_ROOT / "Dockerfile", _REPO_ROOT / "Dockerfile.test")

# The four pins whose drift would matter most. The set is NOT homogeneous, and
# this comment used to say it was ("the four pins that can move a served
# number") while the docstring above measured one of them unreachable — so the
# two reasons are kept apart deliberately:
#
#   pyswisseph, pyjhora  — MEASURED to move served numbers. The ephemeris
#       itself, and the library owning the lunar-node and position-flag levers
#       (the 576 flag word, the 1.98 deg node — see the project's CLAUDE.md).
#   numpy, timezonefinder — the two packages uv.lock forked on at python 3.11
#       while requires-python still admitted 3.10.
#       Both are measured NOT to be reached by the served compute path as the
#       code stands (docstring above). They stay pinned and asserted anyway:
#       dropping a pin the moment you cannot prove harm is a pin that fails
#       open, and reachability can change with nothing in the diff to show it.
#
# If the comparison below ever runs without these in it, it is not checking the
# thing it exists to check — so their presence is asserted, not assumed.
_ACCURACY_CRITICAL = frozenset(
    {"pyswisseph", "pyjhora", "numpy", "timezonefinder"}
)

# Installer plumbing a virtualenv may carry without it appearing in the lock.
# Deliberately tiny: anything else installed-but-unlocked means the environment
# is not the one the lock describes.
_NOT_LOCKED_OK = frozenset({"setuptools", "wheel", "uv", "pkg-resources"})

# The uv build tool: the registry repository both Dockerfiles install it from,
# and the action every workflow must install it with. Repository and action
# name only — the VERSION is derived from the Dockerfiles, never written here.
_UV_IMAGE_REPOSITORY = "ghcr.io/astral-sh/uv"
_SETUP_UV_ACTION = "astral-sh/setup-uv"

# The command that asserts uv.lock still satisfies pyproject.toml. `--frozen`
# is blind to that drift by construction (measured — see the module docstring).
_LOCK_FRESHNESS_COMMAND = "uv lock --check"


# ---------------------------------------------------------------------------
# Reuse the proven Dockerfile parser rather than writing a second one.
# ---------------------------------------------------------------------------
def _load_dockerfile_parser():
    """Load ``parse_dockerfile`` from its sibling guard BY PATH.

    ``ci/`` has no ``__init__.py`` by design, so ``from ci.tests… import …``
    raises under the bare ``pytest`` console script that CI actually invokes
    (it does not put the CWD on ``sys.path``; ``python -m pytest`` does). Path
    loading works under both, which is the documented pattern for this tree.
    """
    module_path = pathlib.Path(__file__).with_name("test_image_bakes_ephemeris.py")
    spec = importlib.util.spec_from_file_location(
        "_image_bake_guard_for_convergence", module_path
    )
    assert spec is not None and spec.loader is not None, (
        f"could not load the Dockerfile parser from {module_path}"
    )
    module = importlib.util.module_from_spec(spec)
    # Register before executing: the sibling defines a @dataclass, and
    # dataclasses resolves `sys.modules[cls.__module__]` while processing the
    # class. A module executed from a spec without being registered has no
    # entry there, which made the decorator raise on Python 3.10; the pinned
    # interpreter is now 3.11, where this registration is harmless defence.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.parse_dockerfile


parse_dockerfile = _load_dockerfile_parser()


def _load_workflow_scope():
    """Load ``ci/workflow_scope.py`` -- the shared workflow enumeration, by path.

    Shared, not universal: which readers take their scope from it is recorded
    in that module's own docstring, not restated here.
    """
    module_path = _REPO_ROOT / "ci" / "workflow_scope.py"
    spec = importlib.util.spec_from_file_location(
        "_workflow_scope_for_convergence", module_path
    )
    assert spec is not None and spec.loader is not None, module_path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_workflow_scope = _load_workflow_scope()


def _load_image_reference_vocabulary():
    """Load the image-reference helpers from the image-pin guard BY PATH.

    ``repository_of`` / ``tag_of`` / ``external_from_images`` already handle the
    cases a naive split gets wrong — a registry host carrying a port read as a
    tag, a ``--platform=`` flag read as an image, a ``FROM`` that names an
    earlier build stage rather than a download. Re-deriving them here would be a
    second, subtly different vocabulary to keep correct, and the sibling's is
    proven by its own discrimination tests.
    """
    module_path = pathlib.Path(__file__).with_name("test_dockerfile_image_pins.py")
    spec = importlib.util.spec_from_file_location(
        "_image_pin_guard_for_convergence", module_path
    )
    assert spec is not None and spec.loader is not None, (
        f"could not load the image-reference vocabulary from {module_path}"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_image_pins = _load_image_reference_vocabulary()
repository_of = _image_pins.repository_of
tag_of = _image_pins.tag_of
external_from_images = _image_pins.external_from_images


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _pinned_python() -> tuple[int, int]:
    """The (major, minor) every environment here must run, from the one file
    that declares it."""
    assert _PYTHON_VERSION_FILE.is_file(), (
        f"{_PYTHON_VERSION_FILE.name} is missing. It is the single declaration "
        "of the interpreter this project resolves against — uv reads it, "
        "actions/setup-python reads it via python-version-file, and the "
        "Dockerfile base images and requires-python are checked against it. "
        "Without it, nothing fixes the interpreter uv.lock is installed for, "
        "and wherever the lock forks on the interpreter 'the locked set' names "
        "more than one set of versions."
    )
    raw = _PYTHON_VERSION_FILE.read_text(encoding="utf-8").strip()
    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.\d+)?", raw)
    assert match, (
        f"{_PYTHON_VERSION_FILE.name} must hold a plain 'MAJOR.MINOR' (or "
        f"'MAJOR.MINOR.PATCH') version; found {raw!r}."
    )
    return int(match.group(1)), int(match.group(2))


def _lock_data() -> dict:
    return tomllib.loads(_LOCK.read_text(encoding="utf-8"))


def _declared_runtime_dependencies() -> set[str]:
    """Canonical names of the project's own ``[project].dependencies``.

    Used as a DERIVED floor for the comparison below — a hard-coded count would
    rot the moment a dependency is added or removed, and a floor that rots is a
    floor that stops failing.
    """
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    names = set()
    for requirement in data["project"]["dependencies"]:
        # Strip extras, markers and version specifiers: "uvicorn[standard]>=0.29"
        name = re.split(r"[\[<>=!~; ]", requirement.strip(), maxsplit=1)[0]
        if name:
            names.add(canonicalize_name(name))
    return names


def _locked_versions_for_this_interpreter() -> dict[str, str]:
    """Resolve ``uv.lock`` down to ONE version per package for the interpreter
    that is running right now, by evaluating each entry's resolution markers."""
    resolved: dict[str, str] = {}
    for package in _lock_data()["package"]:
        name = canonicalize_name(package["name"])
        markers = package.get("resolution-markers") or []
        # No markers => the entry applies to every interpreter in range.
        if markers and not any(Marker(expression).evaluate() for expression in markers):
            continue
        previous = resolved.get(name)
        assert previous is None or previous == package["version"], (
            f"uv.lock resolves {name} ambiguously for this interpreter: both "
            f"{previous} and {package['version']} select. A forked package "
            "whose markers overlap means 'the locked version' is not a single "
            "value, which is exactly the condition this guard exists to "
            "prevent."
        )
        resolved[name] = package["version"]
    return resolved


def _installed_versions() -> dict[str, str]:
    installed: dict[str, str] = {}
    for distribution in metadata.distributions():
        name = distribution.metadata["Name"]
        if not name:
            continue
        installed[canonicalize_name(name)] = distribution.version
    return installed


def _workflow_files() -> list[pathlib.Path]:
    """Both suffixes, asked of git rather than globbed off the disk.

    This already read both extensions, so the change is scope rather than
    coverage: ``--exclude-standard`` keeps a developer's ignored scratch
    workflow from deciding this guard's verdict, and ``--others`` brings an
    untracked one in at the commit that introduces it rather than one commit
    later. Delegated so the four ``ci/tests/`` guards share ONE answer to "what
    are the workflows" -- three had their own, and two of those read ``*.yml``
    only. The claim is scoped to ``ci/tests/`` on purpose: two production
    checkers still enumerate the directory themselves, as
    ``ci/workflow_scope.py``'s docstring records.
    """
    return _workflow_scope.workflow_paths(_REPO_ROOT)


def _job_steps(job: dict) -> list[dict]:
    return [step for step in (job.get("steps") or []) if isinstance(step, dict)]


def _runs_the_suite(step: dict) -> bool:
    """True when a step invokes pytest against this repo's test trees."""
    command = step.get("run") or ""
    if "pytest" not in command:
        return False
    return any(target in command for target in ("tests/", "tests ", "ci/tests"))


def _all_jobs() -> list[tuple[str, str, dict]]:
    """Every (workflow file, job name, job) declared under .github/workflows."""
    found: list[tuple[str, str, dict]] = []
    for path in _workflow_files():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job_name, job in (data.get("jobs") or {}).items():
            if isinstance(job, dict):
                found.append((path.name, job_name, job))
    return found


def _suite_jobs() -> list[tuple[str, str, dict]]:
    """Every (workflow file, job name, job) that runs the test suite."""
    return [
        (workflow, job_name, job)
        for workflow, job_name, job in _all_jobs()
        if any(_runs_the_suite(step) for step in _job_steps(job))
    ]


def _shell_lines(command: str) -> list[str]:
    """The non-blank, non-comment lines of a ``run:`` body.

    A ``#`` comment is text, not a command. This project has been bitten by the
    inverse mistake — a ``grep`` for ``uv sync --frozen`` matching the comment
    that explains the rule — so every command detector below reads this rather
    than the raw body.

    KNOWN BOUND, stated rather than assumed away: this strips whole comment
    LINES, not a comment trailing a real command on the same line. A trailing
    comment cannot hide a command (the command is still on the line and still
    matches), but it can supply a phrase a detector then credits to the job.
    Modelling shell syntax properly is what ``ci/check_pytest_collection.py``
    tried and abandoned in favour of bluntness; the same judgement applies here.
    """
    return [
        line
        for line in (raw.strip() for raw in command.splitlines())
        if line and not line.startswith("#")
    ]


def _run_commands(job: dict) -> list[str]:
    """Every ``run:`` body in a job, comments stripped, one string per step."""
    return [
        "\n".join(_shell_lines(step.get("run") or ""))
        for step in _job_steps(job)
        if step.get("run")
    ]


# `uv`/`uvx` invoked as a command — at the start of a line or after a shell
# separator, so `requirements.frozen.txt` and `--extra dev` cannot match.
_UV_INVOCATION = re.compile(r"(?:^|[\s;&|(])uvx?\s", re.MULTILINE)

# pip asked to install something. Matched loosely on purpose; WHAT it installs
# is then decided on the parsed argument tokens, not by extending this pattern.
_PIP_INSTALL = re.compile(r"\bpip[\d.]*\s+install\b")

# A requirement naming the uv distribution: `uv`, `uv==0.12.5`, `uv[x]`, ...
_UV_REQUIREMENT = re.compile(r"^uv(?:\[[^\]]*\])?(?:[<>=!~].*)?$", re.IGNORECASE)


def _uv_invoking_jobs() -> list[tuple[str, str, dict]]:
    """Jobs whose steps invoke the uv binary — so uv must be on their PATH."""
    return [
        (workflow, job_name, job)
        for workflow, job_name, job in _all_jobs()
        if any(_UV_INVOCATION.search(command) for command in _run_commands(job))
    ]


def _pip_installs_uv(command: str) -> list[str]:
    """The lines of a ``run:`` body that pip-install the uv distribution.

    Decided on the non-flag ARGUMENT tokens rather than by pattern-matching the
    whole line: `python -m pip install --upgrade uv`, `pip install uv==0.12.5`
    and `pip3 install -U 'uv[foo]'` are the same defect wearing three spellings,
    while `uv run --frozen pip-audit …` merely contains the letters.
    """
    offenders: list[str] = []
    for line in _shell_lines(command):
        if not _PIP_INSTALL.search(line):
            continue
        tail = _PIP_INSTALL.split(line, maxsplit=1)[-1]
        arguments = [
            token.strip("\"'") for token in tail.split() if not token.startswith("-")
        ]
        if any(_UV_REQUIREMENT.match(argument) for argument in arguments):
            offenders.append(line)
    return offenders


def _setup_uv_version(step: dict) -> str | None:
    """The uv version an ``astral-sh/setup-uv`` step pins, or None if it floats."""
    options = step.get("with") or {}
    version = options.get("version")
    return None if version is None else str(version).strip()


def _setup_uv_steps(job: dict) -> list[dict]:
    return [
        step
        for step in _job_steps(job)
        if isinstance(step.get("uses"), str)
        and step["uses"].split("@", 1)[0].strip() == _SETUP_UV_ACTION
    ]


def _dockerfile_uv_versions() -> dict[str, str]:
    """The uv build-tool version each Dockerfile installs, keyed by file name.

    This is the SOURCE OF TRUTH for the pin: it is the reference dependabot
    watches (the ``docker`` ecosystem parses ``FROM`` instructions), so it is
    the one that moves first.
    """
    versions: dict[str, str] = {}
    for dockerfile in _DOCKERFILES:
        instructions = parse_dockerfile(dockerfile.read_text(encoding="utf-8"))
        tags = [
            tag_of(image)
            for image in external_from_images(instructions)
            if repository_of(image) == _UV_IMAGE_REPOSITORY
        ]
        assert len(tags) == 1, (
            f"{dockerfile.name} declares {len(tags)} `FROM "
            f"{_UV_IMAGE_REPOSITORY}` stage(s) ({tags}); exactly one is "
            "expected. Either the build tool stopped being installed from a "
            "pinned stage — which "
            "ci/tests/test_dockerfile_image_pins.py covers in its own right — "
            "or this guard can no longer find the version CI must match."
        )
        assert tags[0], (
            f"{dockerfile.name} pins {_UV_IMAGE_REPOSITORY} by digest with no "
            "version tag. A digest-only reference is frozen forever: dependabot "
            "compares TAGS to decide a newer release exists, so it would never "
            "be offered a bump, and there is no version for CI to match."
        )
        versions[dockerfile.name] = tags[0]
    return versions


# ---------------------------------------------------------------------------
# 1 — the interpreter is the pinned one
# ---------------------------------------------------------------------------
def test_running_interpreter_matches_the_pinned_python_version() -> None:
    """The interpreter decides what installs from the lock: the wheels, every
    marker-gated package, and the side of any interpreter fork. So an
    environment on any other minor version has installed something other than
    what ships, however green it looks."""
    expected = _pinned_python()
    actual = (sys.version_info.major, sys.version_info.minor)
    assert actual == expected, (
        f"this interpreter is {actual[0]}.{actual[1]}, but "
        f"{_PYTHON_VERSION_FILE.name} pins {expected[0]}.{expected[1]}. "
        "The interpreter decides which wheels and marker-gated packages "
        "install, and which side of any interpreter fork in uv.lock (it forked "
        "at 3.11 until requires-python was raised to the pin), so this "
        "environment has installed a resolve no deployment runs, and "
        "whatever it certifies is not what ships. Recreate the environment "
        "with `uv sync --frozen --extra dev` (uv reads .python-version)."
    )


def test_requires_python_floor_is_the_pinned_interpreter() -> None:
    """``requires-python`` must read exactly ``>=`` the interpreter
    ``.python-version`` pins, and ``uv.lock`` must have been resolved for it.

    It is the range the universal lock is resolved FOR, and the interpreter an
    automated dependency updater resolves ON. It used to read ``>=3.10`` while
    every image, CI job and developer checkout here ran 3.11, and both of those
    readings went wrong in measured ways. The lock carried a second resolve for
    an interpreter nothing here builds or tests (numpy 2.2.6 and timezonefinder
    8.2.0, below 3.11). And the security updater resolved on Python 3.10.20 and
    reported ``security_update_not_possible`` for a vulnerable locked pin,
    filelock 3.29.6, because the first release patching every advisory against
    it, 4.2.1, requires Python >= 3.11 — so a vulnerable dependency stayed
    locked on behalf of an interpreter that nothing runs.

    A floor ABOVE the pinned interpreter fails the other way round: ``uv sync``
    refuses the very interpreter every environment reads. So the floor is not
    merely bounded by the pin, it IS the pin. Any other shape — a lower floor, a
    second clause, a ceiling — is a separate decision, made by editing this
    test deliberately rather than by editing one line of ``pyproject.toml``.
    """
    major, minor = _pinned_python()
    expected = f">={major}.{minor}"
    project = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"]
    declared = project.get("requires-python")
    assert isinstance(declared, str) and declared.strip(), (
        f"{_PYPROJECT.name} declares no [project].requires-python. Without it "
        "uv resolves the lock for every interpreter it can imagine, and an "
        "updater picks whichever it likes to resolve on."
    )
    clauses = list(SpecifierSet(declared))
    print(
        f"requires-python = {declared!r}; {_PYTHON_VERSION_FILE.name} pins "
        f"{major}.{minor}; {len(clauses)} clause(s): {[str(c) for c in clauses]}"
    )
    is_the_pin = (
        len(clauses) == 1
        and clauses[0].operator == ">="
        and Version(clauses[0].version) == Version(f"{major}.{minor}")
    )
    assert is_the_pin, (
        f"{_PYPROJECT.name} declares requires-python = {declared!r}, but "
        f"{_PYTHON_VERSION_FILE.name} pins {major}.{minor}, so it must read "
        f"{expected!r}. A floor below the pin resolves uv.lock for an "
        "interpreter nothing here builds or tests, and lets the security "
        "updater resolve on it: measured, it resolved on Python 3.10.20 and "
        "reported filelock's patched release (which requires >= 3.11) as "
        "impossible to take. A floor above the pin makes `uv sync` refuse the "
        "interpreter every environment reads."
    )

    locked = _lock_data().get("requires-python")
    assert isinstance(locked, str) and SpecifierSet(locked) == SpecifierSet(declared), (
        f"uv.lock was resolved for requires-python = {locked!r}, but "
        f"{_PYPROJECT.name} declares {declared!r}. The lock is stale against "
        "the manifest; regenerate it with `uv lock`, using the uv version the "
        "Dockerfiles install."
    )


# ---------------------------------------------------------------------------
# 2 — the installed set IS the locked set
# ---------------------------------------------------------------------------
def test_installed_distributions_match_the_lock_for_this_interpreter() -> None:
    """Compare the RESOLVED sets, rather than asserting they match.

    This is deliberately a measurement of the live environment, not a reading
    of configuration: a ``pyproject.toml`` constraint is a declaration, and two
    environments that declare the same thing can and did install different
    versions.
    """
    locked = _locked_versions_for_this_interpreter()
    installed = _installed_versions()

    compared = sorted(set(locked) & set(installed))
    # A comparison that examined nothing reports no differences. Floor it
    # against the project's own declared runtime dependencies, which must all
    # be installed and locked in any environment able to serve a request.
    required = _declared_runtime_dependencies()
    print(
        f"compared {len(compared)} installed distributions against uv.lock "
        f"on python {sys.version_info.major}.{sys.version_info.minor} "
        f"({len(locked)} locked entries select for this interpreter, "
        f"{len(installed)} distributions installed)"
    )

    missing_required = sorted(required - set(compared))
    assert not missing_required, (
        "these declared runtime dependencies were not part of the comparison "
        f"(absent from the environment or from uv.lock): {missing_required}. "
        "A comparison that skips the project's own dependencies proves "
        "nothing about the environment."
    )
    assert len(compared) >= len(required), (
        f"only {len(compared)} distributions were compared against uv.lock, "
        f"fewer than the {len(required)} runtime dependencies this project "
        "declares. The comparison is not seeing the environment."
    )

    missing_critical = sorted(_ACCURACY_CRITICAL - set(compared))
    assert not missing_critical, (
        f"the accuracy-critical pins {missing_critical} were not compared. "
        "These are the ephemeris itself, the chart library that owns the "
        "lunar-node and position-flag levers, and the two packages uv.lock "
        "forked on at python 3.11 — see _ACCURACY_CRITICAL above, where the "
        "two groups are listed under deliberately different reasons. A "
        "convergence check that silently omits them is not a convergence "
        "check."
    )

    mismatched = [
        f"{name}: installed {installed[name]}, uv.lock resolves {locked[name]}"
        for name in compared
        if installed[name] != locked[name]
    ]
    assert not mismatched, (
        "the installed environment is not the one uv.lock describes for this "
        "interpreter:\n  " + "\n  ".join(mismatched) + "\n"
        "Recreate it with `uv sync --frozen --extra dev`. A floating install "
        "(`pip install -e \".[dev]\"`) resolves whatever is newest today, "
        "which is how the suite came to validate a set no deployment ran."
    )

    unlocked = sorted(set(installed) - set(locked) - _NOT_LOCKED_OK)
    assert not unlocked, (
        f"installed but absent from uv.lock: {unlocked}. The environment has "
        "packages the lock does not describe, so it is not the shipped "
        "resolve. Recreate it with `uv sync --frozen --extra dev`."
    )


# ---------------------------------------------------------------------------
# 3 — no workflow may reintroduce a floating resolve
# ---------------------------------------------------------------------------
def test_every_workflow_job_that_runs_the_suite_installs_from_the_frozen_lock() -> None:
    """Structural, over parsed YAML — the divergence this repo had was a
    workflow edit away, and it is a workflow edit away again."""
    suite_jobs = _suite_jobs()
    print(
        f"checked {len(suite_jobs)} workflow job(s) that run the test suite: "
        + ", ".join(f"{wf}:{job}" for wf, job, _ in suite_jobs)
    )
    # Positive floor: test.yml's `test` and `swiss-ephemeris` jobs and
    # publish.yml's `test` job all run the suite. Zero found would mean the
    # detector stopped detecting, and every assertion below would pass
    # vacuously.
    assert len(suite_jobs) >= 3, (
        f"only {len(suite_jobs)} workflow job(s) were found running the test "
        "suite; at least 3 are expected (test.yml's `test` and "
        "`swiss-ephemeris`, publish.yml's `test`). Either a gate was deleted "
        "or this guard's detector no longer recognises the invocation — both "
        "are failures."
    )

    failures: list[str] = []
    for workflow, job_name, job in suite_jobs:
        steps = _job_steps(job)
        commands = [step.get("run") or "" for step in steps]

        installs_frozen = any(
            ("uv sync" in command and "--frozen" in command)
            or ("uv run" in command and "--frozen" in command)
            for command in commands
        )
        if not installs_frozen:
            failures.append(
                f"{workflow}:{job_name} runs the suite but never installs from "
                "the frozen lock (`uv sync --frozen` / `uv run --frozen`)"
            )

        # `--editable` is pip's long form of `-e` and was NOT matched by the
        # original `(-e\s+)?`: measured, a step running
        # `pip install --editable .` alongside a frozen install left this
        # assertion green. Defence in depth — the installs_frozen arm above and
        # the live lock-conformance test in this file both cover that case in
        # more depth — but a floating install should be named by the check that
        # exists to name floating installs.
        floating = [
            command
            for command in commands
            if re.search(r"pip\s+install\s+(?:(?:-e|--editable)\s+)?[\"']?\.", command)
        ]
        if floating:
            failures.append(
                f"{workflow}:{job_name} installs the project with a floating "
                f"resolve that ignores uv.lock: {floating!r}"
            )

        setup_python = [
            step
            for step in steps
            if isinstance(step.get("uses"), str)
            and step["uses"].startswith("actions/setup-python")
        ]
        for step in setup_python:
            options = step.get("with") or {}
            if "python-version-file" not in options:
                failures.append(
                    f"{workflow}:{job_name} pins its interpreter inline "
                    f"({options.get('python-version')!r}) instead of reading "
                    f"{_PYTHON_VERSION_FILE.name}. A second declaration of the "
                    "interpreter is a second chance to test a different resolve "
                    "from the one that ships."
                )
                continue
            # Presence is not the property that matters — the VALUE is.
            # Measured: pointing this key at any other filename left the check
            # green while the job resolved its interpreter from a file this
            # repository does not maintain, which is the same divergence under
            # a different name.
            declared = str(options["python-version-file"]).strip().replace("\\", "/")
            if declared.startswith("./"):
                declared = declared[2:]
            if declared != _PYTHON_VERSION_FILE.name:
                failures.append(
                    f"{workflow}:{job_name} reads its interpreter from "
                    f"{options['python-version-file']!r}, not "
                    f"{_PYTHON_VERSION_FILE.name}. There is exactly one file "
                    "that declares the interpreter here; a job reading a "
                    "different one is a second declaration wearing the right "
                    "key's name."
                )

    assert not failures, "\n  ".join(["", *failures])


# ---------------------------------------------------------------------------
# 4 — the images are on the pinned interpreter too
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("dockerfile", _DOCKERFILES, ids=lambda p: p.name)
def test_dockerfile_base_images_are_the_pinned_python_version(
    dockerfile: pathlib.Path,
) -> None:
    """A base-image bump changes what the image installs with no diff in
    pyproject.toml or uv.lock, so it must not be able to move the interpreter
    without also changing the pin every environment reads."""
    major, minor = _pinned_python()
    instructions = parse_dockerfile(dockerfile.read_text(encoding="utf-8"))

    tags: list[str] = []
    for instruction in instructions:
        if instruction.keyword != "FROM":
            continue
        image = instruction.value.split()[0]
        if image.startswith("python:"):
            tags.append(image.split(":", 1)[1])

    print(f"{dockerfile.name}: found {len(tags)} python base image(s): {tags}")
    assert tags, (
        f"{dockerfile.name} declares no `FROM python:...` stage. Either the "
        "base image stopped being an official python image — in which case "
        "the interpreter this image runs is no longer checked against "
        f"{_PYTHON_VERSION_FILE.name} — or this parser stopped seeing it."
    )

    wrong = [tag for tag in tags if not re.match(rf"^{major}\.{minor}(?:\.\d+)?(?:-|$)", tag)]
    assert not wrong, (
        f"{dockerfile.name} builds on python {wrong}, but "
        f"{_PYTHON_VERSION_FILE.name} pins {major}.{minor}. Moving the "
        "interpreter changes which wheels and marker-gated packages install "
        "(and, wherever uv.lock forks on the interpreter, which versions) with "
        "no change to pyproject.toml or uv.lock, so the image would ship a "
        "resolve nothing tested. dependabot watches the docker ecosystem "
        "weekly, so this is a bump that arrives on its own. Moving the "
        "interpreter is a deliberate, separately-reviewed change that moves "
        ".python-version and requires-python together and re-runs the Swiss "
        "goldens — not a base-image tag edit."
    )


# ---------------------------------------------------------------------------
# 5 — the INSTALLER is pinned too, and it is the images' installer
# ---------------------------------------------------------------------------
def test_no_workflow_installs_uv_from_a_floating_index_resolve() -> None:
    """``pip install uv`` resolves whatever is newest when the job runs.

    That is the floating-resolve defect this file already refuses for the
    project's own dependencies, applied to the tool that installs them.
    Measured 2026-08-21, three steps did exactly this: ``test.yml``'s ``test``
    (the fast suite) and ``swiss-ephemeris`` (the accuracy gate) jobs, and
    ``publish.yml``'s ``test`` job, which gates the image build.
    """
    jobs = _all_jobs()
    print(f"scanned {len(jobs)} workflow job(s) for a floating uv install")
    assert len(jobs) >= 4, (
        f"only {len(jobs)} workflow job(s) were found; this repository declares "
        "more than that across test.yml and publish.yml. A scan that sees "
        "almost nothing reports almost no violations."
    )

    offenders = [
        f"{workflow}:{job_name}: {line}"
        for workflow, job_name, job in jobs
        for command in _run_commands(job)
        for line in _pip_installs_uv(command)
    ]
    assert not offenders, (
        "these workflow steps install uv with a floating index resolve:\n  "
        + "\n  ".join(offenders)
        + "\nBoth Dockerfiles install uv from a digest-pinned `FROM "
        f"{_UV_IMAGE_REPOSITORY}:<version>@sha256:<digest>` stage, so a "
        "floating CI install lets the suite resolve, sync and test through a "
        "different uv than the one that builds the shipped image. Install it "
        f"with `{_SETUP_UV_ACTION}` and an explicit `version:` equal to the "
        "Dockerfiles' tag instead."
    )


def test_every_job_that_invokes_uv_installs_it_from_the_pinned_action() -> None:
    """uv must be ON PATH for those steps, and at a known version.

    This is the arm that catches a half-done conversion: drop the floating
    ``pip install uv`` and forget the action, and the test above goes green
    while every ``uv sync``/``uv run`` step either fails at runtime or, worse,
    succeeds against whatever uv the runner image happens to ship.
    """
    uv_jobs = _uv_invoking_jobs()
    print(
        f"checked {len(uv_jobs)} workflow job(s) that invoke uv: "
        + ", ".join(f"{wf}:{job}" for wf, job, _ in uv_jobs)
    )
    assert len(uv_jobs) >= 3, (
        f"only {len(uv_jobs)} workflow job(s) were found invoking uv; at least "
        "3 are expected (test.yml's `test` and `swiss-ephemeris`, publish.yml's "
        "`test`). Either a gate was deleted or this detector no longer "
        "recognises the invocation — both are failures, and both would make "
        "the assertions below pass vacuously."
    )

    failures: list[str] = []
    for workflow, job_name, job in uv_jobs:
        steps = _setup_uv_steps(job)
        if not steps:
            failures.append(
                f"{workflow}:{job_name} invokes uv but never installs it with "
                f"`{_SETUP_UV_ACTION}`"
            )
            continue
        for step in steps:
            version = _setup_uv_version(step)
            if not version:
                failures.append(
                    f"{workflow}:{job_name} uses {_SETUP_UV_ACTION} without an "
                    "explicit `version:`. The action then defaults to the "
                    "newest release, which is the floating resolve wearing a "
                    "different name."
                )
            elif version in {"latest", "latest-known"}:
                failures.append(
                    f"{workflow}:{job_name} pins uv to {version!r}, which is "
                    "re-resolved per run. The version must equal the tag both "
                    "Dockerfiles install, so CI and the image share one "
                    "installer."
                )

    assert not failures, "\n  ".join(["", *failures])


def test_ci_installs_the_same_uv_version_the_images_ship() -> None:
    """One uv across CI and both images — the equality IS the update mechanism.

    Nothing here writes a version literal. The expected value is DERIVED from
    the Dockerfiles, which are what dependabot watches: its ``docker`` ecosystem
    parses ``FROM`` instructions, while its ``github-actions`` ecosystem bumps
    an action's ``uses:`` ref and never the value of an input to it. So the
    workflow pin is watched by nothing, and this assertion is what drags it
    along — the image bump lands, this goes red, and the workflow follows inside
    the same reviewed change instead of drifting quietly behind it.
    """
    image_versions = _dockerfile_uv_versions()
    workflow_versions = {
        f"{workflow}:{job_name}": _setup_uv_version(step)
        for workflow, job_name, job in _all_jobs()
        for step in _setup_uv_steps(job)
    }
    print(f"uv build tool — images: {image_versions}, workflows: {workflow_versions}")

    assert len(image_versions) == len(_DOCKERFILES), (
        f"found a pinned uv stage in {len(image_versions)} of "
        f"{len(_DOCKERFILES)} Dockerfiles ({sorted(image_versions)}). The "
        "version CI must match is read from them, so a missing one means this "
        "comparison is running on less than it thinks."
    )
    assert len(workflow_versions) >= 3, (
        f"only {len(workflow_versions)} workflow step(s) install uv from "
        f"{_SETUP_UV_ACTION}; at least 3 are expected (test.yml's `test` and "
        "`swiss-ephemeris`, publish.yml's `test`). An equality over an empty "
        "set of workflow pins holds vacuously."
    )

    declared = set(image_versions.values()) | set(workflow_versions.values())
    assert len(declared) == 1, (
        "the uv build tool is not one version across this repository:\n"
        + "".join(f"  {name}: {version}\n" for name, version in image_versions.items())
        + "".join(
            f"  {name}: {version}\n" for name, version in workflow_versions.items()
        )
        + "The Dockerfiles are the source of truth (dependabot watches their "
        "FROM lines; it cannot see an action input), so bring the workflow "
        "`version:` inputs to the tag the images install. Until they agree, CI "
        "resolves and tests the lock through a different uv than the one that "
        "builds the image — this file's founding defect, moved from the "
        "dependency set to the tool that installs it."
    )


# ---------------------------------------------------------------------------
# 6 — the lock is FRESH, not merely installed as-is
# ---------------------------------------------------------------------------
def test_every_job_that_installs_the_frozen_lock_also_checks_it_is_fresh() -> None:
    """``--frozen`` never reads pyproject.toml, so it cannot see a stale lock.

    Measured 2026-08-21 on a scratch copy of this project's own pair, one pin
    edited in ``pyproject.toml`` and ``uv.lock`` left byte-identical:
    ``uv export --frozen`` exited 0 while ``uv lock --check`` exited 1. Every
    job that installs from the lock therefore also asserts the lock still
    satisfies the manifest it claims to resolve.

    Presence, not ordering: a stale lock fails the job from either position, and
    the freshness step is placed first only so the failure reads as one.
    """
    installing_jobs = [
        (workflow, job_name, job)
        for workflow, job_name, job in _all_jobs()
        if any(
            "uv sync" in command and "--frozen" in command
            for command in _run_commands(job)
        )
    ]
    print(
        f"checked {len(installing_jobs)} workflow job(s) that install the frozen "
        "lock: " + ", ".join(f"{wf}:{job}" for wf, job, _ in installing_jobs)
    )
    assert len(installing_jobs) >= 3, (
        f"only {len(installing_jobs)} workflow job(s) were found installing "
        "with `uv sync --frozen`; at least 3 are expected (test.yml's `test` "
        "and `swiss-ephemeris`, publish.yml's `test`). Either an install was "
        "deleted or this detector stopped recognising it."
    )

    missing = [
        f"{workflow}:{job_name}"
        for workflow, job_name, job in installing_jobs
        if not any(_LOCK_FRESHNESS_COMMAND in command for command in _run_commands(job))
    ]
    assert not missing, (
        f"these jobs install `uv sync --frozen` without ever running "
        f"`{_LOCK_FRESHNESS_COMMAND}`: {missing}. `--frozen` installs uv.lock "
        "exactly as committed and never consults pyproject.toml, so a "
        "dependency edit committed without re-running `uv lock` is installed, "
        "tested and shipped as though it had not happened — silently, because "
        "nothing fails. The check costs ~0.1 s and resolves offline when the "
        "lock is fresh."
    )
