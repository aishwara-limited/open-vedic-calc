"""The stable-anchor citation convention is ENFORCED here, not merely observed.

PR #71 converted this tree's rotted ``file:line`` citations to **stable
anchors**: a citation names the SYMBOL it points at -- and, where the claim is
about containment, the enclosing function that holds it -- instead of a line
number that moves under the next edit above it.  That sweep was a one-time
measurement taken against one commit.  This module is the standing guard.  It
re-derives the anchor inventory from ``git ls-files`` on every run and asserts
that every anchor still resolves to a real symbol, so a rename that orphans a
citation reds CI instead of quietly minting fresh rot.

CLAUDE.md's own rule is that *a citation that rots silently is worse than none*.
Nothing in the tree enforced it until this file existed.

THE DISPATCH -- which citation forms this guard READS
=====================================================

The corpus is every tracked ``.py`` / ``.md`` / ``.yml`` / ``.yaml`` / ``.toml``
file, reduced to **prose only**: Python comments (via ``tokenize``) and
docstrings (via ``ast``), ``#`` comment lines in YAML/TOML, and the whole body of
Markdown.  Code string literals are deliberately outside the corpus -- see the
exclusions.  Soft-wrapped prose is rejoined first (a prose line ending in ``_``
is a mid-identifier break, so it joins with no separator), because an anchor
that wraps across two comment lines is still one anchor.

**Form A -- node-id anchor**  ``<module-ref>.py::<name>[::<name>...]``
    The pytest node-id spelling, used in Markdown, comments and docstrings alike.
    ``<module-ref>`` is resolved against tracked files by exact path first, then
    by unique path suffix (so a bare ``chart.py::_build_varga_chart`` resolves,
    and an ambiguous basename is a FAILURE naming every candidate, never a
    guess).  Each ``<name>`` in the chain must be a real symbol at the matching
    scope, found by parsing the target's AST -- never by grepping it.

**Form B -- declared-module bullet anchor**
    A **class or module** docstring that opens a block with ``named by function
    in <path>:`` or ``named by symbol in <path>:``, followed by bullets of the
    shape::

        - ``symbol`` -- what this test covers about it
        - ``enclosing`` -> ``callee`` -- what this test covers about the pair

    Each leading ``symbol`` must exist at module scope in the declared path
    (functions, classes and module-level assignments alike -- ``named by
    symbol`` exists precisely because one bullet names a table, not a def, and
    that table is assigned inside a module-level ``try``/``except``).  When a
    bullet names an ``enclosing -> callee`` pair, the CONTAINMENT is verified
    too: ``callee`` must actually be called somewhere inside ``enclosing``'s
    body.  Both halves resolving separately is not enough -- the arrow is a
    claim about where the callee lives.

    A scope declares exactly ONE subject module.  Two declarations in one
    docstring are a hard failure rather than "take the first", because the
    second would be silently ignored and every anchor written for it would
    resolve against the wrong module or, worse, coincidentally against the
    right-looking one.  Anchors into a second module are spelled in Form A.

**Form C -- declared-module member anchor**
    Inside a class carrying a Form B declaration, a test method whose docstring
    opens ``<symbol>: ...``.  ``<symbol>`` resolves against that class's declared
    module.  This is the bulk of the inventory and the form most exposed to rot,
    because the docstring sits far from the symbol it names.

**Form D -- SHA-pinned historical citation**  ``<sha> ... <path>:<line>``
    The one citation form that CANNOT rot, and so the one ``file:line`` form the
    convention keeps: a dated measurement pinned to an immutable commit.  It is
    VERIFIED rather than excluded -- ``git`` must resolve the SHA to a commit,
    the path must exist in that commit's tree, the file must be long enough to
    have the cited line, and that line must not be blank.  Excluding it would
    have been the cheaper choice and a worse one: a pin nobody checks is a pin
    that can name a commit that was never pushed.

**Form E -- the residue check** (``test_no_unpinned_file_line_citation_survives``)
    Every ``<path>:<line>`` in the corpus must be a Form D pin.  This is what
    makes PR #71 a standing convention instead of a snapshot: a fresh
    line-number citation reds here on the commit that introduces it.

**Form F -- declared-module comment anchor**  ``# <symbol>: ...``
    A comment line opening with an identifier and a colon, inside a file whose
    MODULE docstring carries the Form B header.  ``<symbol>`` resolves at module
    scope of the declared path, exactly as Form C's does.

    This form was exclusion #2 below until the header was lifted to module
    scope.  The anchors were always genuine; what they lacked was an owner a
    machine could read.  A comment has no enclosing AST node to inherit one
    from -- which is the whole reason a *module*-scope declaration was the
    missing piece, and the reason Form C remains class-scoped: a method
    docstring already has an owning scope and does not need the file to speak
    for it.

    The declaration is what removes the guesswork rather than tolerating it: the
    selector runs ONLY inside files that opted in, so a ``word:`` comment opener
    there IS a citation by construction, and the cost -- prose in that shape can
    no longer be written in a declared file -- is stated in each declaring
    docstring rather than discovered by whoever reds the build.

WHAT THIS GUARD DELIBERATELY DOES NOT READ
==========================================

A documented boundary beats a false-positive storm.  Each exclusion below is a
measurement, not a shrug.

1.  **Prose backtick mentions.**  CLAUDE.md is full of ``` `symbol` ``` and
    ``` `module.py`'s `symbol()` ``` written as English, not as citations
    (``the `utils.sidereal_houses` call in `Chart._compute```).  There is no syntactic
    difference between a prose mention of a name and a citation to it, so
    reading them means guessing.  They are covered indirectly: nearly all of
    them name a symbol that also appears in a Form A/B/C anchor.

2.  **Bare ``# <ident>: ...`` comment anchors in a file that declares NO module.**
    This exclusion used to be unconditional, and the reason was real: the module
    such an anchor resolves against was stated only in English, so selecting
    them meant selecting every ``word:`` clause in every comment in the tree,
    and measured over the corpus that selector also returns ``Additive:``,
    ``False:``, ``Measured:`` and ``navamsa:`` -- none of them citations.

    The convention change that removes the guesswork has now landed: the Form B
    header is admissible in a MODULE docstring, and a file that opts in has its
    comment anchors read as Form F above.  ``tests/test_compat_deep.py`` and
    ``tests/test_panchanga_fail_closed.py``, the two files this exclusion named,
    both declare.  How many anchors they carry is deliberately not written here
    -- a hand-typed count in prose is the same defect class as a hand-typed line
    number; the floor test prints the live number on every run.

    What remains excluded is a comment anchor in an UNDECLARED file, and it
    stays excluded on the same evidence as before.  The fix is one line of
    declaration, not a widened selector.

3.  **Code string literals.**  ``ci/tests/test_pytest_collection_check.py``
    holds synthetic pytest ``--deselect`` argv fixtures spelled as node-ids, one
    of them naming a ``tests/x.py`` module that does not exist and must not.
    They are Form A shaped and are not citations.  Restricting the corpus to
    comments and docstrings excludes them by construction rather than by a
    name-based allowlist that would need maintaining.

    Corollary, and it applies to this docstring: **the grammar has no
    placeholder escape.**  Anything Form A shaped in tracked prose is read as a
    citation, here included, so the grammar above is written with angle-bracket
    metavariables and every concrete example given is a real, resolving anchor.
    That is a property worth keeping -- an escape hatch is a way to write rot
    that the guard agrees to ignore.

4.  **Citations into vendored dependencies.**  CLAUDE.md cites
    ``jhora/const.py``'s ``house_owners`` assignment by symbol precisely because
    that file is not in this tree.  Its line numbers move with the pin, and its
    symbols are not resolvable from ``git ls-files``.  Anchors whose module-ref
    is not a tracked file are reported as unresolvable, so a vendored target
    must be cited in prose (as it is), never in Form A.

5.  **Non-Python anchor targets.**  Form A requires a ``.py`` module-ref.  There
    is no AST for a workflow step or a Markdown heading, so ``test.yml::<step>``
    has no defined resolution and the grammar does not admit it.

NON-VACUITY
===========

``test_the_anchor_inventory_meets_its_floor`` refuses an empty or shrunken
corpus.  "Every anchor resolves" is vacuously true of zero anchors, and a regex
that silently stops matching is exactly how a guard dies quietly.  The floors
are therefore asserted PER FORM rather than only in total, so one form going
dark cannot hide behind the others -- and PER CHUNK KIND as well, because the
corpus feeds Forms A, D and F: Forms B and C re-parse ASTs directly, so half the
corpus can vanish while their counts sit untouched.  That is measured, not
supposed; the constant block below carries the numbers.

Form F needs one floor MORE than its own count, and it is the one floor here set
at equality: the module-scope declarations that admit it.  A floor counting
class-scope and module-scope declarations together keeps clearing on the
class-scope ones alone, while Form F quietly finds nothing to read.

Extend this file, never weaken it.
"""
from __future__ import annotations

import ast
import io
import re
import subprocess
import tokenize
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Prose-bearing file kinds.  Measured over every tracked file: no anchor-form
# citation of any shape lives outside these suffixes.
_SCANNED_SUFFIXES = frozenset({".py", ".md", ".yml", ".yaml", ".toml"})
_HASH_COMMENT_SUFFIXES = frozenset({".yml", ".yaml", ".toml"})

# ---------------------------------------------------------------------------
# Non-vacuity floors.
#
# THIS BLOCK CARRIES NO INVENTORY COUNTS, AND THAT IS THE POINT.  It used to
# open with a narrative measurement -- so many files, so many chunks, so many
# anchors per form -- and that narrative went stale TWICE: once before it was
# first committed, having been measured before this file's own docstrings
# finished growing, and once again on the very branch that recorded the first
# lapse, where the figures were taken at the branch's opening commit and three
# later commits then moved them.  A hand-typed count of live tree state, sitting
# in the guard whose entire purpose is to stop hand-typed references rotting, is
# the one place the defect must not survive.  So the numbers are gone rather
# than re-typed: the only figures here are the floors below, which are ASSERTED
# on every run, and the live inventory, which `test_the_anchor_inventory_meets_
# its_floor` PRINTS on every run.  Read them there; nothing in this comment can
# disagree with the tree because nothing in it describes the tree.
#
# WHY THE FLOORS EXIST.  Every assertion in this module has the form "each
# anchor resolves", which is vacuously true of no anchors at all.  A regex that
# stops matching, a corpus extractor returning nothing, or a `git ls-files` that
# fails open would each turn the whole module green while checking nothing.
#
# WHY PER FORM.  A single total lets one form go dark behind the others' growth.
#
# WHY PER CHUNK KIND.  Measured: making `python_chunks` drop comments while
# keeping docstrings costs the entire comment half of the corpus, and every
# other floor here still passes -- Forms B and C never read the chunk corpus at
# all (they re-parse ASTs directly), and Form D's lone citation lives in a
# docstring.  The guard would stay GREEN with every Python comment in the tree
# unread, and a per-kind floor is the only thing that sees it.
#
# WHY ONE OF THESE IS AN EQUALITY, AND IS NAMED FOR IT.
# `_EXPECTED_MODULE_DECLARATIONS` is asserted with `==`, not `>=`.  It used to be
# spelled `_MIN_MODULE_DECLARATIONS` and asserted `>=` while this comment claimed
# it "matches exactly what the tree holds" -- a description and an assertion that
# disagreed, in the guard whose entire subject is prose disagreeing with code.
# Measured: staging a third declaring file left all 21 tests in this module GREEN
# with the inventory reporting 3 against a constant of 2, so the sentence was
# already false and nothing said so.
#
# The equality is the right half to keep, in BOTH directions:
#   * DELETING a declaring file must red, because the module-scope declarations
#     are what admit Form F at all, and losing one silently returns that file's
#     comment anchors to the unguarded state they spent PR #74 in.
#   * ADDING one must red too, and that is a feature rather than a cost.  A
#     declaration changes the MEANING of every `# Word: ...` comment in its file
#     -- they become citations, resolved on every run -- so it is a deliberate
#     act whose cost is recorded in each declaring docstring.  Something that
#     changes what the guard reads may not slip in unremarked.
# A hand-typed equality cannot rot SILENTLY: it reds on the commit that moves the
# tree away from it, which is the moment its author can cheaply re-derive it.  A
# floor rots exactly the way the citations this module polices do.
#
# `_MIN_DECLARED_MODULES` deliberately does NOT absorb them -- a floor counting
# class-scope and module-scope declarations together keeps clearing on the
# class-scope ones alone while the module-scope half is gone.
#
# Floors otherwise sit below the live counts with headroom, so ordinary
# refactoring and legitimate deletion do not red the guard.
# ---------------------------------------------------------------------------
_MIN_SCANNED_FILES = 80
_MIN_COMMENT_CHUNKS = 1200
_MIN_DOCSTRING_CHUNKS = 800
_MIN_NODE_ID_ANCHORS = 18
_MIN_DECLARED_MODULES = 6
_MIN_BULLET_ANCHORS = 28
_MIN_MEMBER_ANCHORS = 38
_MIN_SHA_PINNED_CITATIONS = 1
_EXPECTED_MODULE_DECLARATIONS = 2  # an EQUALITY, not a floor -- see above
_MIN_COMMENT_ANCHORS = 14
_MIN_TOTAL_ANCHORS = 105


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------
def _git(*args: str) -> subprocess.CompletedProcess[str]:
    """Run git and decode as UTF-8 -- explicitly, never at the locale's discretion.

    ``text=True`` alone decodes with the *locale* encoding, which is cp1252 on a
    Windows checkout.  Measured: ``git cat-file blob HEAD:CLAUDE.md`` then dies
    with ``UnicodeDecodeError`` on a reader thread and hands back ``stdout=None``
    -- a crash, not a verdict.  This tree's prose is full of em-dashes, arrows
    and degree signs, so the pin verifier would have been platform-dependent:
    green wherever the pinned file happened to be pure ASCII, and an
    ``AttributeError`` the day one was not.
    """
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _tracked_paths() -> tuple[str, ...]:
    """The scope comes from git, never from a filesystem walk.

    A walk sees build artefacts, virtualenvs and untracked scratch files, and
    misses nothing that matters; ``git ls-files`` is the source of truth for
    "what ships".
    """
    result = _git("ls-files")
    assert result.returncode == 0, f"git ls-files failed: {result.stderr}"
    return tuple(line for line in result.stdout.splitlines() if line.strip())


# ---------------------------------------------------------------------------
# Corpus extraction: prose only, with soft wraps rejoined
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Chunk:
    """One run of prose, with a per-character map back to source lines."""

    path: str
    kind: str
    text: str
    line_of: tuple[int, ...]

    def line_at(self, index: int) -> int:
        if not self.line_of:
            return 0
        return self.line_of[min(index, len(self.line_of) - 1)]

    def line_containing(self, index: int) -> str:
        start = self.text.rfind("\n", 0, index) + 1
        end = self.text.find("\n", index)
        return self.text[start:] if end == -1 else self.text[start:end]

    def where(self, index: int) -> str:
        return f"{self.path}:{self.line_at(index)} ({self.kind})"


def _normalise(numbered_lines: list[tuple[int, str]]) -> tuple[str, tuple[int, ...]]:
    """Join prose lines, healing soft wraps, and map every char to its source line.

    A prose line ending in ``_`` is a mid-identifier break: the convention wraps
    long anchors that way, and ``.github/workflows/test.yml`` carries a real one
    (``...::test_a_workflow_step_runs_the_`` + ``standalone_collection_check``).
    Joining those two with a space would hide the anchor from every form below,
    which is the shape of a guard that reports zero because it is broken.
    """
    buffer: list[str] = []
    line_of: list[int] = []
    previous_was_soft_wrap = False
    for index, (lineno, raw) in enumerate(numbered_lines):
        text = raw.rstrip()
        if index:
            separator = "" if previous_was_soft_wrap else "\n"
            buffer.append(separator)
            line_of.extend([lineno] * len(separator))
        buffer.append(text)
        line_of.extend([lineno] * len(text))
        previous_was_soft_wrap = text.endswith("_")
    return "".join(buffer), tuple(line_of)


def _chunk(path: str, kind: str, numbered_lines: list[tuple[int, str]]) -> Chunk:
    text, line_of = _normalise(numbered_lines)
    return Chunk(path=path, kind=kind, text=text, line_of=line_of)


def _group_consecutive(
    numbered_lines: list[tuple[int, str]]
) -> list[list[tuple[int, str]]]:
    runs: list[list[tuple[int, str]]] = []
    for lineno, text in numbered_lines:
        if runs and runs[-1][-1][0] == lineno - 1:
            runs[-1].append((lineno, text))
        else:
            runs.append([(lineno, text)])
    return runs


def _strip_hash(line: str) -> str:
    body = line.lstrip()
    assert body.startswith("#")
    body = body[1:]
    return body[1:] if body.startswith(" ") else body


def python_chunks(path: str, source: str) -> list[Chunk]:
    """Comments and docstrings -- never code string literals.

    That restriction is the whole reason the synthetic pytest node-ids in
    ``ci/tests/test_pytest_collection_check.py`` are not read as citations.
    """
    chunks: list[Chunk] = []

    comments: list[tuple[int, str]] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            comments.append((token.start[0], _strip_hash(token.string)))
    for run in _group_consecutive(comments):
        chunks.append(_chunk(path, "comment", run))

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        docstring = ast.get_docstring(node, clean=False)
        if not docstring:
            continue
        start = node.body[0].value.lineno  # type: ignore[attr-defined]
        numbered = [
            (start + offset, line) for offset, line in enumerate(docstring.splitlines())
        ]
        chunks.append(_chunk(path, "docstring", numbered))
    return chunks


def hash_comment_chunks(path: str, source: str) -> list[Chunk]:
    comments = [
        (index + 1, _strip_hash(line))
        for index, line in enumerate(source.splitlines())
        if line.lstrip().startswith("#")
    ]
    return [_chunk(path, "comment", run) for run in _group_consecutive(comments)]


def markdown_chunks(path: str, source: str) -> list[Chunk]:
    numbered = [(index + 1, line) for index, line in enumerate(source.splitlines())]
    return [_chunk(path, "markdown", numbered)] if numbered else []


def corpus() -> tuple[list[Chunk], list[str]]:
    """(prose chunks, files scanned).

    A file that cannot be decoded, tokenized or parsed is a HARD failure naming
    the file -- never a quiet ``continue``.  Skipping one is how a corpus shrinks
    without anyone noticing, and the floor test would then be measuring a
    smaller tree rather than a broken extractor.
    """
    chunks: list[Chunk] = []
    scanned: list[str] = []
    for relative in _tracked_paths():
        path = REPO_ROOT / relative
        if path.suffix not in _SCANNED_SUFFIXES or not path.is_file():
            continue
        try:
            source = path.read_text(encoding="utf-8")
            if path.suffix == ".py":
                chunks.extend(python_chunks(relative, source))
            elif path.suffix in _HASH_COMMENT_SUFFIXES:
                chunks.extend(hash_comment_chunks(relative, source))
            else:
                chunks.extend(markdown_chunks(relative, source))
        except Exception as exc:  # noqa: BLE001 -- re-raised with the file named
            raise AssertionError(
                f"could not extract prose from tracked file {relative}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        scanned.append(relative)
    return chunks, scanned


# ---------------------------------------------------------------------------
# Resolution: AST, never grep
# ---------------------------------------------------------------------------
def _scope_symbols(body: list[ast.stmt]) -> dict[str, ast.AST]:
    """Names bound in one scope: defs, classes and assignments.

    Module-level ``try``/``except``/``if``/``with`` bodies are descended into,
    because a real anchor needs it: ``bphs_core/vimshopaka.py``'s
    ``_DASHAVARGA_WEIGHTS_RAW`` is assigned in the ``except`` arm of a
    module-level import guard, and ``tests/test_edges.py`` cites it by name.
    """
    found: dict[str, ast.AST] = {}
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.setdefault(node.name, node)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found.setdefault(target.id, node)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                found.setdefault(node.target.id, node)
        elif isinstance(node, (ast.Try, ast.If, ast.With, ast.AsyncWith)):
            nested: list[ast.stmt] = list(node.body)
            nested.extend(getattr(node, "orelse", []))
            nested.extend(getattr(node, "finalbody", []))
            for handler in getattr(node, "handlers", []):
                nested.extend(handler.body)
            for name, value in _scope_symbols(nested).items():
                found.setdefault(name, value)
    return found


_symbol_cache: dict[str, dict[str, ast.AST]] = {}


def module_symbols(relative: str) -> dict[str, ast.AST]:
    if relative not in _symbol_cache:
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        _symbol_cache[relative] = _scope_symbols(ast.parse(source).body)
    return _symbol_cache[relative]


def called_names(node: ast.AST) -> set[str]:
    """Every name invoked inside *node*, direct or via an attribute."""
    names: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        function = child.func
        if isinstance(function, ast.Name):
            names.add(function.id)
        elif isinstance(function, ast.Attribute):
            names.add(function.attr)
    return names


class Unresolved(Exception):
    """Raised with the anchor, what was searched, and what was there instead."""


def resolve_module_ref(reference: str, tracked: tuple[str, ...]) -> str:
    """A path or a bare basename -> exactly one tracked ``.py`` file."""
    python_files = [p for p in tracked if p.endswith(".py")]
    if reference in python_files:
        return reference
    candidates = [p for p in python_files if p.endswith("/" + reference)]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise Unresolved(
            f"module-ref {reference!r} matches no tracked .py file "
            f"(searched {len(python_files)} tracked Python files by exact path "
            f"then by unique path suffix)"
        )
    raise Unresolved(
        f"module-ref {reference!r} is AMBIGUOUS across {len(candidates)} tracked "
        f"files: {sorted(candidates)}. Cite the full path."
    )


def resolve_symbol_chain(relative: str, chain: list[str]) -> ast.AST:
    scope = module_symbols(relative)
    trail: list[str] = []
    node: ast.AST | None = None
    for name in chain:
        if name not in scope:
            searched = "::".join(trail) or "module scope"
            raise Unresolved(
                f"{relative}::{'::'.join(chain)} -> {name!r} is not defined at "
                f"{searched} of {relative} "
                f"(searched {len(scope)} names there: {sorted(scope)[:12]}"
                f"{' ...' if len(scope) > 12 else ''})"
            )
        node = scope[name]
        trail.append(name)
        scope = (
            _scope_symbols(node.body)
            if isinstance(
                node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            )
            else {}
        )
    assert node is not None
    return node


def resolve_module_level_symbol(relative: str, name: str) -> ast.AST:
    return resolve_symbol_chain(relative, [name])


def verify_containment(relative: str, enclosing: str, callee: str) -> None:
    """``enclosing -> callee`` claims the callee is CALLED inside the enclosing body."""
    node = resolve_module_level_symbol(relative, enclosing)
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise Unresolved(
            f"{relative}: containment anchor `{enclosing}` -> `{callee}` names "
            f"{enclosing!r}, which is a {type(node).__name__}, not a function"
        )
    resolve_module_level_symbol(relative, callee)  # the callee must exist too
    invoked = called_names(node)
    if callee not in invoked:
        raise Unresolved(
            f"{relative}: containment anchor `{enclosing}` -> `{callee}` is BROKEN "
            f"-- {callee!r} is never called inside {enclosing}()'s body "
            f"(searched every ast.Call there; it calls {sorted(invoked)})"
        )


# ---------------------------------------------------------------------------
# The forms
# ---------------------------------------------------------------------------
_NODE_ID = re.compile(
    r"(?<![\w/.-])(?P<module>[\w./-]+\.py)(?P<chain>(?:::[A-Za-z_]\w*)+)"
)
_DECLARATION = re.compile(
    r"named by (?:function|symbol) in\s+(?P<module>[\w./-]+\.py)\s*:"
)
_BULLET = re.compile(
    r"^[ \t]*-[ \t]+``(?P<symbol>[A-Za-z_]\w*)``"
    r"(?:[ \t]*(?:→|->)[ \t]*``(?P<callee>[A-Za-z_]\w*)``)?",
    re.M,
)
_MEMBER_ANCHOR = re.compile(r"\A[ \t]*(?P<symbol>[A-Za-z_]\w*):[ \t]")
# Form F.  Deliberately the same grammar as Form C, matched per LINE (`re.M`)
# rather than at the start of one docstring, because a comment anchor opens its
# own comment line and a run of them is extracted as one chunk.  It is applied
# only inside files carrying a MODULE-scope declaration -- unqualified, the same
# selector returns `Additive:`, `False:`, `Measured:` and `navamsa:` across the
# tree, which is exactly why this form was excluded before the declaration
# existed.
_COMMENT_ANCHOR = re.compile(r"^[ \t]*(?P<symbol>[A-Za-z_]\w*):[ \t]", re.M)
_FILE_LINE = re.compile(
    r"(?<![\w/.-])(?P<path>[\w./-]+\.(?:py|md|ya?ml|toml)):(?P<line>\d+)(?!\d)"
)
_SHA = re.compile(r"(?<![\w])(?P<sha>[0-9a-f]{7,40})(?![\w])")


@dataclass(frozen=True)
class NodeIdAnchor:
    where: str
    module_ref: str
    chain: tuple[str, ...]
    raw: str


@dataclass(frozen=True)
class BulletAnchor:
    where: str
    module_ref: str
    symbol: str
    callee: str | None


@dataclass(frozen=True)
class MemberAnchor:
    where: str
    module_ref: str
    symbol: str
    owner: str


@dataclass(frozen=True)
class CommentAnchor:
    where: str
    module_ref: str
    symbol: str


@dataclass(frozen=True)
class ShaPinnedCitation:
    where: str
    sha_candidates: tuple[str, ...]
    path: str
    line: int
    raw: str


def collect_node_id_anchors(chunks: list[Chunk]) -> list[NodeIdAnchor]:
    anchors = []
    for chunk in chunks:
        for match in _NODE_ID.finditer(chunk.text):
            anchors.append(
                NodeIdAnchor(
                    where=chunk.where(match.start()),
                    module_ref=match.group("module"),
                    chain=tuple(match.group("chain").split("::")[1:]),
                    raw=match.group(0),
                )
            )
    return anchors


def sole_declaration(docstring: str, where: str) -> str | None:
    """The one module-ref a docstring declares, or ``None`` -- never a guess.

    TWO declarations in one docstring is a hard failure rather than "take the
    first": the second would be silently ignored, and every anchor the author
    wrote for it would resolve against the wrong module or, worse, resolve
    against the right-looking one by coincidence.  A scope declares one subject.
    """
    found = _DECLARATION.findall(docstring)
    if not found:
        return None
    if len(found) > 1:
        raise Unresolved(
            f"{where}: {len(found)} module declarations in one docstring "
            f"({found}). A scope declares exactly one subject module -- the "
            f"extras would be silently ignored. Split the block, or cite the "
            f"others in Form A (`<path>.py::<symbol>`)."
        )
    return found[0]


def collect_declared_blocks(
    tracked: tuple[str, ...]
) -> tuple[
    list[BulletAnchor],
    list[MemberAnchor],
    list[tuple[str, str, str]],
    dict[str, str],
]:
    """The tracked-file driver for :func:`collect_declared_blocks_from_source`."""
    return collect_declared_blocks_from_source(
        {
            relative: (REPO_ROOT / relative).read_text(encoding="utf-8")
            for relative in tracked
            if relative.endswith(".py")
        }
    )


def collect_declared_blocks_from_source(
    sources: dict[str, str]
) -> tuple[
    list[BulletAnchor],
    list[MemberAnchor],
    list[tuple[str, str, str]],
    dict[str, str],
]:
    """Form B bullets, Form C member anchors, the declarations, and the modules.

    Driven from ``{path: source}`` rather than from disk, for the same reason
    :func:`python_chunks` takes a source string: the grammar can then be
    exercised on a synthetic module, and a control that has to commit a file to
    the tree in order to test a rejection is a control nobody writes.

    The declaration header is read at TWO scopes.  On a class it declares that
    class's subject, as it always has.  On a MODULE it declares the whole file's
    subject, which is what gives a bare ``# <symbol>:`` comment a machine-readable
    owner -- a comment has no enclosing AST node to inherit one from, and that
    absence is the entire reason Form F could not be read before.

    Bullets are collected from either kind of docstring, because the grammar is
    the same grammar; member anchors stay a CLASS-scope form, because a method
    docstring already has an owning scope and does not need the file to speak
    for it.
    """
    bullets: list[BulletAnchor] = []
    members: list[MemberAnchor] = []
    declarations: list[tuple[str, str, str]] = []
    module_declarations: dict[str, str] = {}
    for relative, source in sources.items():
        tree = ast.parse(source)

        module_doc = ast.get_docstring(tree, clean=False)
        if module_doc:
            module_ref = sole_declaration(module_doc, f"{relative} (module docstring)")
            if module_ref:
                module_declarations[relative] = module_ref
                declarations.append((relative, "<module>", module_ref))
                for bullet in _BULLET.finditer(module_doc):
                    bullets.append(
                        BulletAnchor(
                            where=f"{relative}:1 (module docstring)",
                            module_ref=module_ref,
                            symbol=bullet.group("symbol"),
                            callee=bullet.group("callee"),
                        )
                    )

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            docstring = ast.get_docstring(node, clean=False)
            if not docstring:
                continue
            module_ref = sole_declaration(
                docstring, f"{relative}:{node.lineno} ({node.name} docstring)"
            )
            if not module_ref:
                continue
            owner = f"{relative}::{node.name}"
            declarations.append((relative, node.name, module_ref))
            for bullet in _BULLET.finditer(docstring):
                bullets.append(
                    BulletAnchor(
                        where=f"{relative}:{node.lineno} ({node.name} docstring)",
                        module_ref=module_ref,
                        symbol=bullet.group("symbol"),
                        callee=bullet.group("callee"),
                    )
                )
            for member in node.body:
                if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                member_doc = ast.get_docstring(member, clean=False)
                if not member_doc:
                    continue
                anchor = _MEMBER_ANCHOR.match(member_doc)
                if not anchor:
                    continue
                members.append(
                    MemberAnchor(
                        where=f"{relative}:{member.lineno} ({member.name} docstring)",
                        module_ref=module_ref,
                        symbol=anchor.group("symbol"),
                        owner=owner,
                    )
                )
    return bullets, members, declarations, module_declarations


def collect_comment_anchors(
    chunks: list[Chunk], module_declarations: dict[str, str]
) -> list[CommentAnchor]:
    """Form F: ``# <symbol>: ...`` inside a file that declared its subject module.

    Scoped to declared files, and to COMMENT chunks specifically.  A docstring in
    a declared file is left alone: its ``<symbol>:`` openers are Form C's
    business, and reading them here would count the same anchor twice under two
    forms, inflating a floor that is supposed to detect a form going dark.
    """
    anchors: list[CommentAnchor] = []
    for chunk in chunks:
        if chunk.kind != "comment":
            continue
        module_ref = module_declarations.get(chunk.path)
        if module_ref is None:
            continue
        for match in _COMMENT_ANCHOR.finditer(chunk.text):
            anchors.append(
                CommentAnchor(
                    where=chunk.where(match.start()),
                    module_ref=module_ref,
                    symbol=match.group("symbol"),
                )
            )
    return anchors


def collect_file_line_citations(chunks: list[Chunk]) -> list[ShaPinnedCitation]:
    citations = []
    for chunk in chunks:
        for match in _FILE_LINE.finditer(chunk.text):
            line = chunk.line_containing(match.start())
            candidates = tuple(
                m.group("sha") for m in _SHA.finditer(line)
            )
            citations.append(
                ShaPinnedCitation(
                    where=chunk.where(match.start()),
                    sha_candidates=candidates,
                    path=match.group("path"),
                    line=int(match.group("line")),
                    raw=line.strip(),
                )
            )
    return citations


def pinning_sha(citation: ShaPinnedCitation) -> str:
    """Which SHA on the citation's line names a real commit? (Form E's question.)

    Deliberately separate from :func:`verify_pin_target` -- "is this citation
    pinned at all" and "does the pin still describe the file it names" are two
    different failures with two different fixes, and a single function answering
    both would make its two callers the same test twice over.
    """
    tried: list[str] = []
    for candidate in citation.sha_candidates:
        commit = _git("rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}")
        if commit.returncode == 0:
            return candidate
        tried.append(f"{candidate}: not a commit in this clone")
    shallow = _git("rev-parse", "--is-shallow-repository").stdout.strip() == "true"
    hint = (
        "  This clone is SHALLOW -- the pinned commit may simply not have been "
        "fetched. Check the workflow out with `fetch-depth: 0` where this suite "
        "runs; a pin that cannot be checked must fail, never skip.\n"
        if shallow
        else ""
    )
    raise Unresolved(
        f"{citation.where}: `{citation.path}:{citation.line}` is a line-number "
        f"citation with no SHA pin.\n"
        f"  Line: {citation.raw}\n"
        f"  SHA-shaped tokens tried: "
        f"{list(citation.sha_candidates) or 'none on this line'}\n"
        + ("".join(f"    - {reason}\n" for reason in tried))
        + hint
        + "  Convert it to a stable anchor (`<path>.py::<symbol>`), or pin it to a "
        "commit SHA on the same line."
    )


def verify_pin_target(citation: ShaPinnedCitation, sha: str) -> str:
    """Does the pin still describe a real line of a real file AT THAT COMMIT?

    A pin naming a commit that does not contain the cited path, or a line the
    file was never long enough to have, is a fabricated record -- and a blank
    line is not a citation to anything.
    """
    blob = _git("cat-file", "blob", f"{sha}:{citation.path}")
    if blob.returncode != 0:
        raise Unresolved(
            f"{citation.where}: pinned at {sha}, but {citation.path} does not "
            f"exist in that commit's tree.\n  Line: {citation.raw}"
        )
    lines = blob.stdout.splitlines()
    if len(lines) < citation.line:
        raise Unresolved(
            f"{citation.where}: pinned at {sha}, but {citation.path} had only "
            f"{len(lines)} lines there, so line {citation.line} never existed.\n"
            f"  Line: {citation.raw}"
        )
    content = lines[citation.line - 1]
    if not content.strip():
        raise Unresolved(
            f"{citation.where}: pinned at {sha}, but {citation.path}:{citation.line} "
            f"is BLANK at that commit -- the pin cites nothing.\n"
            f"  Line: {citation.raw}"
        )
    return content.strip()


# ---------------------------------------------------------------------------
# Shared inventory
# ---------------------------------------------------------------------------
def build_inventory():
    tracked = _tracked_paths()
    chunks, scanned = corpus()
    node_ids = collect_node_id_anchors(chunks)
    bullets, members, declarations, module_declarations = collect_declared_blocks(
        tracked
    )
    comment_anchors = collect_comment_anchors(chunks, module_declarations)
    file_lines = collect_file_line_citations(chunks)
    return {
        "tracked": tracked,
        "chunks": chunks,
        "scanned": scanned,
        "node_ids": node_ids,
        "bullets": bullets,
        "members": members,
        "declarations": declarations,
        "module_declarations": module_declarations,
        "comment_anchors": comment_anchors,
        "file_lines": file_lines,
    }


# ===========================================================================
# The guard
# ===========================================================================
def test_the_anchor_inventory_meets_its_floor():
    """An empty inventory is a REFUSAL, not a pass.

    Every assertion below is of the form "each anchor resolves", which is
    vacuously true of no anchors at all.  A regex that stops matching, a corpus
    extractor that returns nothing, or a `git ls-files` that fails open would
    each turn this whole module green while checking nothing.
    """
    inventory = build_inventory()
    by_kind = Counter(chunk.kind for chunk in inventory["chunks"])
    counts = {
        "files scanned": len(inventory["scanned"]),
        "prose chunks": len(inventory["chunks"]),
        "  of which comment": by_kind["comment"],
        "  of which docstring": by_kind["docstring"],
        "  of which markdown": by_kind["markdown"],
        "Form A node-id anchors": len(inventory["node_ids"]),
        "Form B declared blocks": len(inventory["declarations"]),
        "  of which module-scope": len(inventory["module_declarations"]),
        "Form B bullet anchors": len(inventory["bullets"]),
        "Form C member anchors": len(inventory["members"]),
        "Form D file:line citations": len(inventory["file_lines"]),
        "Form F comment anchors": len(inventory["comment_anchors"]),
    }
    print("\nStable-anchor inventory:")
    for label, value in counts.items():
        print(f"  {label:34} {value}")

    total = (
        len(inventory["node_ids"])
        + len(inventory["bullets"])
        + len(inventory["members"])
        + len(inventory["file_lines"])
        + len(inventory["comment_anchors"])
    )
    print(f"  {'TOTAL anchors checked':34} {total}")

    assert len(inventory["scanned"]) >= _MIN_SCANNED_FILES, (
        f"only {len(inventory['scanned'])} tracked files were scanned "
        f"(floor {_MIN_SCANNED_FILES}) -- the corpus extractor is broken, not the tree"
    )

    # Per-KIND, because a file can be scanned and still yield no prose. Measured:
    # dropping comments alone costs 59% of the corpus and every OTHER floor here
    # still passes, so a total-only floor would not see it.
    assert by_kind["comment"] >= _MIN_COMMENT_CHUNKS, (
        f"only {by_kind['comment']} comment chunks (floor {_MIN_COMMENT_CHUNKS}) "
        f"-- the comment half of the corpus has gone dark, and Forms B and C "
        f"cannot notice because they re-parse ASTs rather than reading chunks"
    )
    assert by_kind["docstring"] >= _MIN_DOCSTRING_CHUNKS, (
        f"only {by_kind['docstring']} docstring chunks "
        f"(floor {_MIN_DOCSTRING_CHUNKS}) -- the docstring half of the corpus "
        f"has gone dark"
    )
    # Markdown gets an EQUALITY, not a floor: every tracked .md yields exactly one
    # chunk, so the two move together under an added or deleted file and diverge
    # only when the extractor drops one. A floor of 3 against 3 measured files
    # would red on a legitimate deletion and pass on a silent drop of two.
    markdown_files = [p for p in inventory["scanned"] if p.endswith(".md")]
    assert by_kind["markdown"] == len(markdown_files), (
        f"{by_kind['markdown']} markdown chunks for {len(markdown_files)} tracked "
        f".md files ({markdown_files}) -- each should yield exactly one"
    )

    assert len(inventory["node_ids"]) >= _MIN_NODE_ID_ANCHORS, (
        f"Form A found {len(inventory['node_ids'])} anchors, floor "
        f"{_MIN_NODE_ID_ANCHORS} -- the node-id form has gone dark"
    )
    assert len(inventory["declarations"]) >= _MIN_DECLARED_MODULES, (
        f"Form B found {len(inventory['declarations'])} declared-module blocks, "
        f"floor {_MIN_DECLARED_MODULES}"
    )
    assert len(inventory["bullets"]) >= _MIN_BULLET_ANCHORS, (
        f"Form B found {len(inventory['bullets'])} bullet anchors, floor "
        f"{_MIN_BULLET_ANCHORS}"
    )
    assert len(inventory["members"]) >= _MIN_MEMBER_ANCHORS, (
        f"Form C found {len(inventory['members'])} member anchors, floor "
        f"{_MIN_MEMBER_ANCHORS}"
    )
    assert len(inventory["file_lines"]) >= _MIN_SHA_PINNED_CITATIONS, (
        f"Form D found {len(inventory['file_lines'])} SHA-pinned citations, floor "
        f"{_MIN_SHA_PINNED_CITATIONS} -- the residue check has nothing to check"
    )
    # Floored SEPARATELY from the declared-block total above: a combined count
    # of 9 keeps clearing a floor of 6 with both module-scope declarations gone,
    # and Form F would then silently find nothing to check.
    assert len(inventory["module_declarations"]) == _EXPECTED_MODULE_DECLARATIONS, (
        f"{len(inventory['module_declarations'])} module-scope declarations "
        f"({sorted(inventory['module_declarations'])}), expected exactly "
        f"{_EXPECTED_MODULE_DECLARATIONS}. FEWER: Form F has lost a file to "
        f"read, and the comment anchors it carried are unguarded prose again. "
        f"MORE: a file has newly declared a subject module, which turns every "
        f"`# Word: ...` comment in it into a resolved citation -- a deliberate "
        f"act, so update this constant in the same change rather than relaxing "
        f"the assertion."
    )
    assert len(inventory["comment_anchors"]) >= _MIN_COMMENT_ANCHORS, (
        f"Form F found {len(inventory['comment_anchors'])} comment anchors, "
        f"floor {_MIN_COMMENT_ANCHORS} -- the comment form has gone dark"
    )
    assert total >= _MIN_TOTAL_ANCHORS, (
        f"{total} anchors in total, floor {_MIN_TOTAL_ANCHORS}"
    )


def test_every_node_id_anchor_resolves_to_a_real_symbol():
    """Form A: ``<path>.py::<name>`` -- the module is tracked, the name is defined."""
    inventory = build_inventory()
    anchors = inventory["node_ids"]
    assert anchors, "Form A found nothing -- see the floor test"
    failures: list[str] = []
    for anchor in anchors:
        try:
            relative = resolve_module_ref(anchor.module_ref, inventory["tracked"])
            resolve_symbol_chain(relative, list(anchor.chain))
        except Unresolved as exc:
            failures.append(f"{anchor.where}: `{anchor.raw}` -- {exc}")
    assert not failures, "Rotted node-id anchors:\n" + "\n".join(failures)


def test_every_declared_module_bullet_anchor_resolves():
    """Form B: each bullet's leading symbol exists; each ``->`` pair CONTAINS."""
    inventory = build_inventory()
    bullets = inventory["bullets"]
    assert bullets, "Form B found nothing -- see the floor test"
    failures: list[str] = []
    containment_checked = 0
    for bullet in bullets:
        try:
            relative = resolve_module_ref(bullet.module_ref, inventory["tracked"])
            resolve_module_level_symbol(relative, bullet.symbol)
            if bullet.callee:
                verify_containment(relative, bullet.symbol, bullet.callee)
                containment_checked += 1
        except Unresolved as exc:
            arrow = f" -> `{bullet.callee}`" if bullet.callee else ""
            failures.append(f"{bullet.where}: `{bullet.symbol}`{arrow} -- {exc}")
    assert not failures, "Rotted declared-module bullet anchors:\n" + "\n".join(failures)
    print(f"\nForm B: {len(bullets)} bullets, {containment_checked} containment pairs")


def test_every_declared_module_member_anchor_resolves():
    """Form C: a test docstring opening ``<symbol>:`` names a real symbol."""
    inventory = build_inventory()
    members = inventory["members"]
    assert members, "Form C found nothing -- see the floor test"
    failures: list[str] = []
    for member in members:
        try:
            relative = resolve_module_ref(member.module_ref, inventory["tracked"])
            resolve_module_level_symbol(relative, member.symbol)
        except Unresolved as exc:
            failures.append(
                f"{member.where}: anchor `{member.symbol}:` under {member.owner} "
                f"(declared module {member.module_ref}) -- {exc}"
            )
    assert not failures, "Rotted member anchors:\n" + "\n".join(failures)


def test_every_declared_module_comment_anchor_resolves():
    """Form F: ``# <symbol>: ...`` in a file whose MODULE declares its subject.

    This form was the guard's documented exclusion #2 until the Form B header
    was lifted to module scope.  The anchors were always genuine -- the reason
    they could not be read is that the module they resolve against was stated
    only in English, so selecting them meant selecting every ``word:`` clause in
    every comment in the tree, which measurably returns ``Additive:``,
    ``False:``, ``Measured:`` and ``navamsa:`` among the real ones.

    A machine-readable declaration removes the guesswork instead of tolerating
    it: the selector now runs ONLY inside files that opted in by naming their
    subject module, and inside those files a ``word:`` comment opener IS a
    citation by construction.
    """
    inventory = build_inventory()
    anchors = inventory["comment_anchors"]
    assert anchors, "Form F found nothing -- see the floor test"
    failures: list[str] = []
    for anchor in anchors:
        try:
            relative = resolve_module_ref(anchor.module_ref, inventory["tracked"])
            resolve_module_level_symbol(relative, anchor.symbol)
        except Unresolved as exc:
            failures.append(
                f"{anchor.where}: comment anchor `{anchor.symbol}:` "
                f"(module declared as {anchor.module_ref}) -- {exc}"
            )
    assert not failures, "Rotted comment anchors:\n" + "\n".join(failures)


def test_the_two_files_that_carried_unguarded_comment_anchors_are_declared():
    """The premise of the form above, named rather than left implicit.

    Form F is vacuous unless some file actually declares its module.  These two
    are the files the exclusion named, and the count is DERIVED from each file's
    own comments rather than written down here -- a hand-typed anchor count in
    prose is the same defect class as a hand-typed line number.
    """
    inventory = build_inventory()
    declared = inventory["module_declarations"]
    for path, expected_module in (
        ("tests/test_compat_deep.py", "bphs_core/compat.py"),
        ("tests/test_panchanga_fail_closed.py", "bphs_core/lagna_shuddhi.py"),
    ):
        assert declared.get(path) == expected_module, (
            f"{path} does not declare {expected_module} at module scope "
            f"(declared: {declared.get(path)!r}), so its comment anchors are "
            f"outside the guarded inventory again"
        )
        found = [a for a in inventory["comment_anchors"] if a.where.startswith(path)]
        assert found, f"{path} declares a module but yielded no comment anchors"


def test_every_sha_pinned_citation_resolves_at_its_sha():
    """Form D: the one ``file:line`` form that cannot rot -- because it is verified.

    A pin is only a pin if something reads it.  This arm asks whether the pinned
    commit still describes what the citation claims: the path must exist in that
    commit's tree, and the cited line must exist and be non-blank THERE.  Whether
    a pin exists at all is the residue check's question, one test down.
    """
    inventory = build_inventory()
    citations = inventory["file_lines"]
    assert citations, "Form D found nothing -- see the floor test"
    failures: list[str] = []
    resolved: list[str] = []
    for citation in citations:
        try:
            sha = pinning_sha(citation)
        except Unresolved:
            continue  # unpinned entirely -- that is the residue check's failure
        try:
            content = verify_pin_target(citation, sha)
            resolved.append(f"{citation.path}:{citation.line} @ {sha} -> {content!r}")
        except Unresolved as exc:
            failures.append(str(exc))
    assert not failures, "SHA pins that no longer describe their target:\n" + "\n".join(
        failures
    )
    assert resolved, (
        "not one citation was verified at a pinned commit -- every one was "
        "unpinned, so this test examined nothing"
    )
    print(f"\nForm D verified at their pinned commits: {resolved}")


def test_no_unpinned_file_line_citation_survives():
    """Form E: every ``file:line`` in tracked prose is SHA-pinned, or it is rot.

    This is what makes the anchor convention STANDING rather than a snapshot of
    one sweep.  A fresh line-number citation reds on the commit that adds it,
    which is the only moment its author can cheaply convert it to an anchor.
    """
    inventory = build_inventory()
    unpinned: list[str] = []
    for citation in inventory["file_lines"]:
        try:
            pinning_sha(citation)
        except Unresolved as exc:
            unpinned.append(str(exc))
    assert not unpinned, (
        "Line-number citations with no SHA pin -- convert each to a stable "
        "anchor (`<path>.py::<symbol>`):\n" + "\n".join(unpinned)
    )


# ===========================================================================
# Negative controls -- a check that cannot fail is not a check
# ===========================================================================
_SYNTHETIC_SOURCE = '''\
"""Module docstring citing bphs_core/chart.py::Chart."""
ARGV = ["--deselect", "tests/nonexistent.py::test_nothing"]


class Widget:
    """Edge branches covered here, named by function in bphs_core/chart.py:

      - ``ChartSnapshot`` -- a real symbol.
    """

    def test_one(self):
        """ChartSnapshot: a member anchor."""
        return "bphs_core/chart.py::AlsoNotAnAnchorBecauseItIsCode"

# a wrapped anchor: bphs_core/chart.py::_jd_from_
# person continues here
'''


def test_the_corpus_reads_prose_and_refuses_code_string_literals():
    """The exclusion that keeps the synthetic argv fixtures out is load-bearing."""
    chunks = python_chunks("synthetic.py", _SYNTHETIC_SOURCE)
    anchors = {a.raw for a in collect_node_id_anchors(chunks)}
    assert "bphs_core/chart.py::Chart" in anchors, (
        "the docstring anchor was not read -- the corpus extractor is broken"
    )
    assert not any("nonexistent" in a for a in anchors), (
        "a pytest argv fixture inside a code string literal was read as a "
        f"citation: {anchors}"
    )
    assert not any("AlsoNotAnAnchorBecauseItIsCode" in a for a in anchors), (
        f"a return-value string literal was read as a citation: {anchors}"
    )


def test_a_soft_wrapped_anchor_is_rejoined_before_matching():
    """``.github/workflows/test.yml`` carries a real one; a space would hide it."""
    chunks = python_chunks("synthetic.py", _SYNTHETIC_SOURCE)
    anchors = {a.raw for a in collect_node_id_anchors(chunks)}
    assert "bphs_core/chart.py::_jd_from_person" in anchors, (
        f"the wrapped anchor was not rejoined: {anchors}"
    )


def test_the_guard_is_not_exempt_from_itself():
    """This file's own prose is inside the corpus it checks.

    It was not, while it was untracked -- and that is exactly how a guard ships
    with rot in its own docstring.  ``git ls-files`` is the scope, so the day
    this file is committed its every example anchor becomes a claim the guard
    itself has to honour.  Measured on the way in: two metasyntactic
    ``<path>.py::<symbol>`` placeholders written here and in CLAUDE.md were
    caught by this guard the moment the file was staged.
    """
    _, scanned = corpus()
    own_path = str(Path(__file__).resolve().relative_to(REPO_ROOT)).replace("\\", "/")
    assert own_path in scanned, (
        f"{own_path} is not in the scanned corpus ({len(scanned)} files) -- either "
        "it is untracked, or the extractor skips it. A guard exempt from itself "
        "can carry the rot it exists to catch."
    )


def test_the_symbol_resolver_refuses_a_name_that_is_not_defined():
    """Neuter control for Forms A/B/C: an absent symbol must RAISE, loudly."""
    resolve_module_level_symbol("bphs_core/chart.py", "Chart")  # the control passes
    try:
        resolve_module_level_symbol("bphs_core/chart.py", "Chart_renamed_by_a_refactor")
    except Unresolved as exc:
        message = str(exc)
        assert "Chart_renamed_by_a_refactor" in message, message
        assert "bphs_core/chart.py" in message, message
        assert "searched" in message, (
            f"the failure must say what was searched, not just that it failed: {message}"
        )
    else:
        raise AssertionError(
            "resolve_module_level_symbol accepted a name that does not exist -- "
            "the resolver cannot fail, so it is not a check"
        )


def test_the_module_ref_resolver_refuses_an_unknown_and_an_ambiguous_reference():
    tracked = ("bphs_core/chart.py", "app/chart.py", "bphs_core/utils.py")
    assert resolve_module_ref("bphs_core/chart.py", tracked) == "bphs_core/chart.py"
    assert resolve_module_ref("utils.py", tracked) == "bphs_core/utils.py"
    try:
        resolve_module_ref("chart.py", tracked)
    except Unresolved as exc:
        assert "AMBIGUOUS" in str(exc), str(exc)
    else:
        raise AssertionError("an ambiguous basename was silently resolved to a guess")
    try:
        resolve_module_ref("no_such_module.py", tracked)
    except Unresolved as exc:
        assert "matches no tracked" in str(exc), str(exc)
    else:
        raise AssertionError("an unknown module-ref was silently accepted")


def test_the_containment_check_refuses_a_callee_that_is_not_called_there():
    """The ``enclosing -> callee`` arrow is a claim about WHERE, not just WHAT.

    Both halves resolving separately is not evidence: this control names two
    real, module-level functions that have no calling relationship.
    """
    verify_containment(
        "bphs_core/dashas.py", "get_dasha_timeline", "_vimshottari_antardashas"
    )  # the true pair passes
    try:
        verify_containment(
            "bphs_core/dashas.py", "get_active_dasha", "_vimshottari_antardashas"
        )
    except Unresolved as exc:
        message = str(exc)
        assert "BROKEN" in message, message
        assert "never called inside" in message, message
    else:
        raise AssertionError(
            "containment accepted a callee that the enclosing function never calls"
        )


def _synthetic_citation(**overrides) -> ShaPinnedCitation:
    fields = {
        "where": "synthetic",
        "sha_candidates": (),
        "path": "bphs_core/compat.py",
        "line": 1,
        "raw": "synthetic citation",
    }
    fields.update(overrides)
    return ShaPinnedCitation(**fields)  # type: ignore[arg-type]


def test_the_pin_detector_refuses_a_citation_with_no_resolvable_sha():
    """Neuter control for Form E: an unpinned line-number citation must RAISE."""
    for candidates, expected in (
        ((), "none on this line"),
        (("deadbeefcafe",), "not a commit"),
    ):
        try:
            pinning_sha(_synthetic_citation(sha_candidates=candidates))
        except Unresolved as exc:
            assert "no SHA pin" in str(exc), str(exc)
            assert expected in str(exc), str(exc)
        else:
            raise AssertionError(
                f"a citation with SHA candidates {candidates!r} was accepted as pinned"
            )


def test_the_pin_target_verifier_refuses_a_pin_that_no_longer_describes_its_target():
    """Neuter control for Form D: each of the three target arms must actually fail.

    The control SHA is this repo's own HEAD, so the arms are exercised against a
    real commit holding a real file -- otherwise every arm would fail for the
    same uninteresting reason (no such commit) and prove nothing about the arm
    it names.  HEAD is used rather than the root commit because CLAUDE.md
    postdates the root, and because HEAD is the one commit a shallow clone is
    guaranteed to have.
    """
    root = _git("rev-parse", "HEAD").stdout.strip()
    present = _git("cat-file", "blob", f"{root}:CLAUDE.md")
    assert present.returncode == 0, "expected CLAUDE.md to exist at HEAD"
    length = len(present.stdout.splitlines())

    verify_pin_target(_synthetic_citation(path="CLAUDE.md", line=1), root)  # passes

    for citation, expected in (
        (_synthetic_citation(path="no/such/file.py", line=1), "does not exist in that"),
        (_synthetic_citation(path="CLAUDE.md", line=length + 1000), "never existed"),
    ):
        try:
            verify_pin_target(citation, root)
        except Unresolved as exc:
            assert expected in str(exc), str(exc)
        else:
            raise AssertionError(
                f"verify_pin_target accepted {citation.path}:{citation.line} at {root}"
            )

    blank = next(
        (
            index + 1
            for index, line in enumerate(present.stdout.splitlines())
            if not line.strip()
        ),
        None,
    )
    assert blank is not None, "expected CLAUDE.md to contain a blank line to cite"
    try:
        verify_pin_target(_synthetic_citation(path="CLAUDE.md", line=blank), root)
    except Unresolved as exc:
        assert "BLANK" in str(exc), str(exc)
    else:
        raise AssertionError("a pin citing a blank line was accepted")


_SYNTHETIC_DECLARED_MODULE = '''\
"""A module that declares its subject, named by function in bphs_core/chart.py:

  - ``ChartSnapshot`` -- a bullet read from a MODULE docstring, not a class one.
"""

# ChartSnapshot: a comment anchor, owned by the module declaration above.
# _jd_from_person: a second one.
VALUE = 1
'''

_SYNTHETIC_UNDECLARED_MODULE = '''\
"""A module that declares nothing at all."""

# Measured: this is prose, and must NOT be read as a citation.
VALUE = 1
'''


def test_a_module_scope_declaration_owns_its_files_comment_anchors():
    """Form F's mechanism, exercised on a synthetic file rather than only the tree.

    Two halves, and the second is the one that matters: the identical comment in
    an UNDECLARED file must stay invisible.  Reading it there is the
    false-positive storm the exclusion was written to avoid, and ``Measured:``
    is one of the four openers actually measured over this corpus.
    """
    _bullets, _members, _declarations, declared = collect_declared_blocks_from_source(
        {"declared.py": _SYNTHETIC_DECLARED_MODULE}
    )
    assert declared == {"declared.py": "bphs_core/chart.py"}

    chunks = python_chunks("declared.py", _SYNTHETIC_DECLARED_MODULE)
    anchors = collect_comment_anchors(chunks, declared)
    assert sorted(a.symbol for a in anchors) == ["ChartSnapshot", "_jd_from_person"], (
        f"the declared file's comment anchors were not read: {anchors}"
    )

    undeclared_chunks = python_chunks("plain.py", _SYNTHETIC_UNDECLARED_MODULE)
    assert collect_comment_anchors(undeclared_chunks, declared) == [], (
        "a `Word: ...` comment in a file that declares nothing was read as a "
        "citation -- that is the false-positive storm exclusion #2 exists to "
        "prevent"
    )


def test_a_module_scope_declaration_also_carries_its_bullets():
    """The Form B grammar is the same grammar wherever the header sits."""
    bullets, _members, _declarations, _declared = collect_declared_blocks_from_source(
        {"declared.py": _SYNTHETIC_DECLARED_MODULE}
    )
    assert [b.symbol for b in bullets] == ["ChartSnapshot"], (
        f"a bullet under a module-scope declaration was not read: {bullets}"
    )
    assert all(b.module_ref == "bphs_core/chart.py" for b in bullets)


def test_two_declarations_in_one_docstring_are_refused_not_silently_halved():
    """"Take the first" would discard a whole block of anchors without a word."""
    doc = (
        "named by function in bphs_core/chart.py:\n"
        "\nand also named by function in bphs_core/compat.py:\n"
    )
    assert sole_declaration("named by function in bphs_core/chart.py:", "x") == (
        "bphs_core/chart.py"
    )
    assert sole_declaration("no declaration here", "x") is None
    try:
        sole_declaration(doc, "synthetic.py (module docstring)")
    except Unresolved as exc:
        assert "2 module declarations" in str(exc), str(exc)
    else:
        raise AssertionError(
            "two declarations in one docstring were accepted, so the second "
            "module's anchors would resolve against the first"
        )


def test_the_comment_anchor_resolver_refuses_a_symbol_that_moved():
    """Neuter control for Form F: the anchor must actually be checked.

    A form that collects anchors but resolves nothing is a counter, not a guard.
    """
    resolve_module_level_symbol("bphs_core/compat.py", "_vasya")  # the control passes
    try:
        resolve_module_level_symbol("bphs_core/compat.py", "_vasya_renamed")
    except Unresolved as exc:
        assert "_vasya_renamed" in str(exc), str(exc)
    else:
        raise AssertionError("a renamed comment-anchor target resolved anyway")


def test_the_declaration_and_bullet_grammar_reject_prose_that_is_not_a_citation():
    """The grammar must not read every backticked word as an anchor."""
    assert _DECLARATION.search("named by function in bphs_core/dashas.py:")
    assert _DECLARATION.search("named by symbol in bphs_core/vimshopaka.py:")
    assert not _DECLARATION.search("named after the function in bphs_core/dashas.py")
    assert [m.group("symbol") for m in _BULLET.finditer("  - ``alpha`` -- x\n")] == [
        "alpha"
    ]
    assert not _BULLET.search("the ``alpha`` helper is described in prose here")
    assert not _MEMBER_ANCHOR.match("Build a snapshot where Sun is in `sun_house`.")
    assert not _MEMBER_ANCHOR.match("False arc of _mangal_dosha_raw's cancellation.")
    assert _MEMBER_ANCHOR.match("kalsarp_dosh: Rahu absent -> present=False.")
