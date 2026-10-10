"""Classify one surviving mutant: CHANGED / UNCHANGED / LOGGING / LINTED / EQUIV.

Extracted from mutation.sh, where it lived twice verbatim — once for the
survivor loop and once for the no-covering-test loop. Two copies of 356 lines
is a fix applied twice and a divergence waiting to happen, so it is one file
invoked from both.

Argv: <survivor-line> <workdir> <changed-ranges-json> <module-path>

Prints exactly one verdict and exits 1 for a verdict the lane must act on
(CHANGED/UNCHANGED/LOGGING/LINTED) or 0 for EQUIV. Any other exit is a classifier
failure, and the caller fails closed on it rather than dropping the mutant —
an unclassified survivor silently leaving every bucket is the same
silence-read-as-success this gate exists to stop.
"""

import ast
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlparse

survivor, workdir, changed_ranges = sys.argv[1].strip().split(": ", 1)[0], sys.argv[2], sys.argv[3]
module_path = sys.argv[4]
module, mutant_name = survivor.rsplit(".", 1)
mutant_file = f"{workdir}/mutants/{module.replace('.', '/')}.py"
src = Path(mutant_file).read_text()
# The mutants dict is per function, named without the mutant id:
#   mutants_<base>__mutmut['_mutmut_orig'] = <base>__mutmut_orig
# For a METHOD the right-hand side is QUALIFIED by its class:
#   mutants_xǁCǁm__mutmut['_mutmut_orig'] = C.xǁCǁm__mutmut_orig
# `[\w.]+` then the tail after the last dot, because `\w+` stopped at the dot and
# captured the CLASS name — which resolves to no function, so every method
# survivor left this script with an empty verdict and mutation.sh (correctly)
# failed closed on it. Observed on
# accounting.LLMAccountingMiddleware.aafter_model.
base = re.sub(r"__mutmut_\d+$", "", mutant_name)
dict_name = f"mutants_{base}__mutmut"
orig_match = re.search(
    rf"^{re.escape(dict_name)}\['_mutmut_orig'\]\s*=\s*([\w.]+)", src, re.MULTILINE
)
if not orig_match:
    sys.exit(1)
orig_name = orig_match.group(1).rsplit(".", 1)[-1]
# Split ONLY at mutmut's own generated names (x_..__mutmut_N / xǁClassǁ..), at
# any indentation: methods are emitted inside their class (a module-level-only
# split found no body for them), and a plain any-def split truncated every
# CONTAINER function at its first nested def — the header alone then compared
# equal to every mutant and 788 real survivors on one module were stamped
# provably equivalent. Both are the false green this script exists to prevent.
blocks = re.split(r"^[ \t]*(?:async )?def (?=x[\w.ǁ]*__mutmut_)", src, flags=re.MULTILINE)


def _def_lines(path: str) -> dict[str, int]:
    """Qualified function name -> the line its ``def`` sits on, in the REAL file."""
    found: dict[str, int] = {}

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                found[prefix + child.name] = child.lineno
                walk(child, f"{prefix}{child.name}.")
            elif isinstance(child, ast.ClassDef):
                walk(child, f"{prefix}{child.name}.")

    walk(ast.parse(Path(path).read_text()), "")
    return found


# The survivor's line must be resolved against the REAL module, not the
# mutants copy: mutmut expands every function into one variant per mutant, so
# the copy runs to ~20x the length and its line numbers share no coordinate
# space with the PR's diff ranges. Comparing the two (as this once did) let a
# survivor on an untouched line land inside a changed range by arithmetic
# coincidence and fail the lane.
#
# mutmut names the original `x_<func>__mutmut_orig`, or
# `xǁ<Class>ǁ<method>__mutmut_orig` for a method.
qualified = orig_name.removesuffix("__mutmut_orig")
qualified = ".".join(qualified.split("ǁ")[1:]) if "ǁ" in qualified else qualified.removeprefix("x_")
orig_line = _def_lines(f"{workdir}/{module_path}").get(qualified)
if orig_line is None:
    sys.exit(1)


def _body(name: str) -> list[str]:
    for block in blocks:
        if block.split("(", 1)[0].strip() == name:
            return block.splitlines()[1:]
    return []


def _first_argument_end(text: str, i: int) -> int:
    """Index just past the first call argument starting at ``i``.

    That is the comma that ends it, or the closing bracket of a one-argument call.
    Bracket/quote balanced: a type arg like ``dict[str, object] | None`` (or a
    quoted forward ref) holds commas a regex stops at, and a half-blanked cast
    then reads as a real change.
    """
    depth = 0
    quote: str | None = None
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote and text[i - 1] != "\\":
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif ch == "," and depth == 0:
            break
        i += 1
    return i


def _normalized(lines: list[str]) -> list[str]:
    """Blank the TYPE argument of every ``cast()``.

    typing.cast(T, x) is documented to return x unchanged at runtime, so a mutant
    that only rewrites T is behaviorally identical. Matched across the joined body
    rather than line by line: the formatter puts a long cast's type argument on
    its own line, and a per-line regex then finds no ``cast(`` to anchor to and
    reports a provably equivalent mutant as a survivor (observed on
    create_agent._fallback_config, where ``cast(RunnableConfig,`` is split).

    The substitution preserves the line COUNT so the caller's index arithmetic
    still maps a differing line back to the real file.
    """

    joined = "\n".join(lines)
    out: list[str] = []
    pos = 0
    while (start := joined.find("cast(", pos)) != -1:
        i = _first_argument_end(joined, start + len("cast("))
        if i < len(joined) and joined[i] == ",":
            arg = joined[start + len("cast(") : i]
            out.append(joined[pos:start] + "cast(" + "\n" * arg.count("\n") + "_")
        else:
            out.append(joined[pos:i])
        pos = i
    out.append(joined[pos:])
    return "".join(out).split("\n")


def _blank_call_next_arg(lines: list[str]) -> list[str]:
    """Blank the sole argument of every ``call_next(...)``.

    Starlette's ``BaseHTTPMiddleware`` builds ``call_next`` as a closure over the
    request's own ``scope``/``receive``/``send`` and calls
    ``self.app(scope, receive_or_disconnect, send_no_error)`` — it never reads
    its ``request`` parameter (starlette/middleware/base.py, ``async def
    call_next(request: Request)``). So ``call_next(request)`` and
    ``call_next(None)`` are the same program, and mutmut's argument-to-None
    mutation of that one call is unkillable by any test rather than a gap in
    one. Same class of provable no-op as the ``cast()`` type argument above.

    Narrow on purpose: only a call spelled ``call_next``, and only its first
    argument. Every ``call_next`` in this codebase is that closure — a helper
    of that name which DID read its argument would be mis-blanked here.

    Line COUNT is preserved so the caller's index arithmetic still maps a
    differing line back to the real file.
    """
    joined = "\n".join(lines)
    out: list[str] = []
    pos = 0
    needle = "call_next("
    while (start := joined.find(needle, pos)) != -1:
        i = _first_argument_end(joined, start + len(needle))
        arg = joined[start + len(needle) : i]
        out.append(joined[pos:start] + needle + "\n" * arg.count("\n") + "_")
        pos = i
    out.append(joined[pos:])
    return "".join(out).split("\n")


orig_raw = _body(orig_name)
mut_raw = _body(mutant_name)
orig_lines = _blank_call_next_arg(_normalized(orig_raw))
mut_lines = _blank_call_next_arg(_normalized(mut_raw))
if orig_lines == mut_lines:
    print("EQUIV")
    sys.exit(0)
# The ONLY unassertable logging is log.debug/log.info. Verified in
# libs/shared/py/wide_events.py: those two just emit a loguru line, while
# warning/error/critical/exception call _append(), which stores
# entry = {"msg": message, **kwargs} on the wide event. So on the recorded
# levels BOTH the message and the kwargs land in warnings[]/errors[] — a
# consumed, queryable surface that tests already assert against
# (tests/integration/api/test_wide_event_contracts.py) — and every mutation of
# them is killable. log.audit, log.set and log.set_ns are likewise never
# excluded. Only debug/info are, and for those the whole call goes: their
# kwargs never reach anywhere a test could read them.
_LOG_NARRATION = {"debug", "info"}


def _excluded_span(path: str, line_no: int):
    """Span of the log.debug/log.info call covering line_no, or None."""
    try:
        tree = ast.parse(Path(path).read_text())
    except SyntaxError:
        return None
    best = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "log"
            and func.attr in _LOG_NARRATION
        ):
            continue
        if node.lineno <= line_no <= (node.end_lineno or node.lineno):
            # Innermost enclosing call wins.
            if best is None or best.lineno < node.lineno:
                best = node
    if best is None:
        return None
    return (best.lineno, best.col_offset, best.end_lineno or best.lineno, best.end_col_offset)


def _falsy_literal(node) -> bool:
    """Return True for a literal that is falsy — None/False/0/"" and empty containers."""
    if isinstance(node, ast.Constant):
        return not node.value
    if isinstance(node, ast.List | ast.Tuple | ast.Set):
        return not node.elts
    if isinstance(node, ast.Dict):
        return not node.keys
    return False


def _mutated_token(span, line_no: int, orig_line: str, mut_line: str) -> str | None:
    """Return the text the mutation put where the literal at ``span`` was, or None.

    Column-exact rather than a common-prefix/suffix diff. mutmut changes ONE
    construct per mutant, so everything left of the literal is untouched and
    the replacement ends exactly len(mut_line) - len(orig_line) further along.
    A character diff gets this wrong the moment the two literals share an
    edge: False -> None shares a trailing "e" and slices to "Non", which then
    fails to literal_eval and misreports an equivalent mutant as a survivor.
    Returns None for a literal spilling across lines, where the arithmetic
    does not hold.
    """
    start_line, start_col, end_line, end_col = span
    if start_line != line_no or end_line != line_no:
        return None
    return mut_line[start_col : end_col + len(mut_line) - len(orig_line)]


def _falsy_replacement(replacement: str | None, *, removal_stays_falsy: bool) -> bool:
    """Return True when the mutation put another falsy literal where the original was.

    ``removal_stays_falsy`` answers the one case the text cannot: mutmut also
    DELETES the argument, and what the call then does is the callee's business.
    ``d.get(k)`` still hands back None, so the mutant is equivalent; ``d.pop(k)``
    and ``getattr(o, n)`` raise instead, and ``json.dumps`` falls back to
    ``ensure_ascii=True`` — all three observable, none of them falsy.
    """
    if replacement is None:
        return False
    stripped = replacement.strip()
    if not stripped:
        return removal_stays_falsy
    try:
        return not ast.literal_eval(stripped)
    except (ValueError, SyntaxError):
        return False


def _boolean_consumer(node) -> bool:
    """Return True when node's own value reaches only a test every falsy value answers alike."""
    parent = getattr(node, "parent", None)
    if isinstance(parent, ast.BoolOp) and isinstance(parent.op, ast.Or):
        # `x or y` evaluates to y for EVERY falsy x, so which falsy x it was is lost.
        return parent.values[-1] is not node
    if isinstance(parent, ast.BoolOp) and isinstance(parent.op, ast.And):
        # `x and y` is the opposite: for falsy x it evaluates to x ITSELF, so the
        # distinction survives into the BoolOp's result and dies (or does not)
        # wherever that result goes. Follow it rather than answering here —
        # `if x and y:` collapses every falsy x exactly as `if x:` does, while
        # `return x and y` hands the caller the falsy value it was.
        return _boolean_consumer(parent)
    if isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not):
        # `not x` is True for every falsy x — the distinction dies here no
        # matter where the result then flows.
        return True
    if (
        isinstance(parent, ast.Call)
        and isinstance(parent.func, ast.Name)
        and parent.func.id == "bool"
        and not parent.keywords
        and len(parent.args) == 1
        and parent.args[0] is node
    ):
        # `bool(x)` is False for every falsy x — the same collapse as `not x`,
        # written the other way round.
        return True
    return isinstance(parent, ast.If | ast.IfExp) and parent.test is node


def _is_not_name(node, name: str) -> bool:
    return (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.Not)
        and isinstance(node.operand, ast.Name)
        and node.operand.id == name
    )


def _early_exit_on_falsy(stmt, name: str) -> bool:
    """Return True for ``if not name: <exit>`` — everything after runs only on truthy.

    An ``or`` chain holding ``not name`` is the same guard for that name: a falsy
    value makes the whole test true, so ``if not w or not h: return`` leaves
    every later read of ``w`` (and of ``h``) on the truthy side.
    """
    if not (
        isinstance(stmt, ast.If)
        and not stmt.orelse
        and all(isinstance(s, ast.Return | ast.Raise | ast.Continue | ast.Break) for s in stmt.body)
    ):
        return False
    test = stmt.test
    operands = (
        test.values if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or) else [test]
    )
    return any(_is_not_name(operand, name) for operand in operands)


def _tests_truthy(test, name: str) -> bool:
    """Return True when reaching a body past ``test`` requires ``name`` to be truthy.

    Either the test IS the name, or it is an ``and`` chain containing it: ``and``
    short-circuits, so `if x and y:` reaches its body only on a truthy x, exactly
    as `if x:` does. ``or`` is deliberately not here — `if x or y:` runs its body
    with x falsy, so the falsy value is still observable inside.
    """
    if isinstance(test, ast.Name):
        return test.id == name
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
        return any(isinstance(v, ast.Name) and v.id == name for v in test.values)
    return False


def _guarded_by(node, name: str) -> bool:
    """Return True when node sits in code that runs only while `name` is truthy."""
    child = node
    parent = getattr(node, "parent", None)
    while parent is not None:
        test = getattr(parent, "test", None)
        if isinstance(parent, ast.If | ast.IfExp) and _tests_truthy(test, name):
            body = parent.body if isinstance(parent.body, list) else [parent.body]
            if any(child is stmt for stmt in body):
                return True
        # An earlier `if not name: return/raise/continue/break` sibling means
        # this statement is only reached on the truthy side.
        for field in ("body", "orelse", "finalbody"):
            stmts = getattr(parent, field, None)
            if isinstance(stmts, list) and child in stmts:
                idx = stmts.index(child)
                if any(_early_exit_on_falsy(s, name) for s in stmts[:idx]):
                    return True
        child, parent = parent, getattr(parent, "parent", None)
    return False


def _through_casts(node):
    """Hop out of enclosing ``cast(T, node)`` calls — cast returns node unchanged."""
    parent = getattr(node, "parent", None)
    while (
        isinstance(parent, ast.Call)
        and isinstance(parent.func, ast.Name)
        and parent.func.id == "cast"
        and len(parent.args) == 2
        and parent.args[1] is node
    ):
        node, parent = parent, getattr(parent, "parent", None)
    return node


def _through_conditionals(node):
    """Hop out of an enclosing ``a if c else node`` — on that arm the expression IS the node.

    The reasoning extractor binds ``x.get(k) if isinstance(x, dict) else getattr(x, k, "")``
    and truth-tests the name; the lookup's consumer is the conditional's consumer.
    """
    parent = getattr(node, "parent", None)
    while isinstance(parent, ast.IfExp) and (parent.body is node or parent.orelse is node):
        node, parent = parent, getattr(parent, "parent", None)
    return node


def _only_boolean_uses(call) -> bool:
    """Return True when nothing downstream of `call` can tell one falsy value from another."""
    call = _through_conditionals(_through_casts(call))
    if _boolean_consumer(call):
        return True
    # Bound to a name first: then EVERY read of that name has to be blind to
    # which falsy value it holds, or the default is observable after all.
    assign = getattr(call, "parent", None)
    if not (
        isinstance(assign, ast.Assign)
        and len(assign.targets) == 1
        and isinstance(assign.targets[0], ast.Name)
    ):
        return False
    target = assign.targets[0]
    scope = assign
    while scope is not None and not isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef):
        scope = getattr(scope, "parent", None)
    if scope is None:
        return False
    for node in ast.walk(scope):
        if not isinstance(node, ast.Name) or node.id != target.id or node is target:
            continue
        if not isinstance(node.ctx, ast.Load):
            return False  # rebound or deleted; the reads after it are another value
        if not (_boolean_consumer(node) or _guarded_by(node, target.id)):
            return False
    return True


def _lookup_with_default(node) -> bool:
    """Return True for ``x.get(k, d)``, ``x.pop(k, d)`` or ``getattr(o, n, d)``.

    Each hands back ``d`` only when the lookup misses, so the same reasoning
    about which falsy fallback was written applies to every spelling — pop's
    removal side effect happens either way.
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in ("get", "pop") and len(node.args) == 2:
        return True
    return isinstance(func, ast.Name) and func.id == "getattr" and len(node.args) == 3


def _outermost_lookup(node):
    """Follow a fallback that is itself another lookup's fallback, to the last one.

    ``a.get(k, b.get(j, 0))`` delivers that 0 through the OUTER call, so the outer
    call's consumers are the ones that decide whether the literal is observable.
    Checking the inner call alone answered "its value is an argument, so it might
    be", and reported an unkillable mutant on every nested-fallback read.
    """
    current = node
    while True:
        parent = getattr(current, "parent", None)
        if _lookup_with_default(parent) and parent.args[-1] is current:
            current = parent
            continue
        return current


def _unobservable_get_default(
    path: str, line_no: int, col: int, orig_line: str, mut_line: str
) -> bool:
    """Return True when the mutation only changed a .get() default nothing can observe.

    A falsy default is unobservable when every consumer of the value collapses
    all falsy values to one answer — `x or y`, `if x:`, `x if x else y`, and
    code reachable only on the truthy side of such a test. On the missing-key
    path each of those takes the identical branch, so no test can tell which
    falsy default was written.

    Deliberately NOT a blanket .get-default rule: the discriminator is the
    CONSUMER, not the call. app/agents/middleware/completion.py carries both
    verdicts on the same call shape — `state.get("messages", [])` feeding
    `len(messages)` in current_delegation is observable (None raises, and a
    real test kills that mutant), while the identical call in
    reply_promises_future_work feeds only `messages[-1] if messages else None`
    and is not. A TRUTHY default stays observable too (`d.get(k, 1) or 0`
    returns 1 when the key is absent), and mutmut increments numeric defaults,
    so the replacement must be falsy as well. Anything unparseable fails closed.
    """
    try:
        tree = ast.parse(Path(path).read_text())
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node
    for node in ast.walk(tree):
        if not _lookup_with_default(node):
            continue
        default = node.args[-1]
        if not _falsy_literal(default):
            continue
        span = (
            default.lineno,
            default.col_offset,
            default.end_lineno or default.lineno,
            default.end_col_offset,
        )
        if not _within(span, line_no, col):
            continue
        # Only ``.get`` survives losing its default with a falsy value (None);
        # ``.pop`` and ``getattr`` raise, which every test can see.
        func = node.func
        removal_stays_falsy = isinstance(func, ast.Attribute) and func.attr == "get"
        return _falsy_replacement(
            _mutated_token(span, line_no, orig_line, mut_line),
            removal_stays_falsy=removal_stays_falsy,
        ) and _only_boolean_uses(_outermost_lookup(node))
    return False


def _reads_only_as_boolean(assign: ast.Assign) -> bool:
    """Return True when every LOAD of the assigned name collapses all falsy values.

    Unlike ``_only_boolean_uses`` this does not bail when the name is rebound:
    the mutation only changed the initial literal, and if every read of the name
    is a truthiness test then no read can tell one falsy value from another —
    whatever later assignment overwrote it first. Store reads are the rebinds
    themselves and carry no value to observe — EXCEPT an ``AugAssign`` target
    (``x += 1``): augmented assignment reads the previous value first, so
    ``x = False`` vs ``x = None`` diverges there (``False + 1`` is 1,
    ``None + 1`` raises) even though both are falsy.
    """
    target = assign.targets[0]
    if not isinstance(target, ast.Name):
        return False
    scope = assign
    while scope is not None and not isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef):
        scope = scope.parent
    if scope is None:
        return False
    for node in ast.walk(scope):
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            if node.target.id == target.id:
                return False
        if (
            isinstance(node, ast.Name)
            and node.id == target.id
            and node is not target
            and isinstance(node.ctx, ast.Load)
            and not (_boolean_consumer(node) or _guarded_by(node, target.id))
        ):
            return False
    return True


def _unobservable_falsy_assignment(
    path: str, line_no: int, col: int, orig_line: str, mut_line: str
) -> bool:
    """Return True when a falsy-to-falsy literal swap is unobservable.

    The mutation only changed the initial literal of an assignment whose name
    nothing can tell apart. The canonical case is ``cancelled = False`` mutated to ``cancelled = None``:
    the name is read only by a truthiness test (``elif cancelled:``), and every
    falsy value answers that test identically, so no test can distinguish them —
    the same CONSUMER-based reasoning as the .get()-default rule, applied to a
    plain assignment instead of a lookup. A TRUTHY original or replacement stays
    observable (``cancelled = True`` really does select another branch), so both
    the original literal and its replacement must be falsy; anything unparseable
    fails closed.
    """
    try:
        tree = ast.parse(Path(path).read_text())
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        value = node.value
        if not _falsy_literal(value):
            continue
        span = (
            value.lineno,
            value.col_offset,
            value.end_lineno or value.lineno,
            value.end_col_offset,
        )
        if not _within(span, line_no, col):
            continue
        return _falsy_replacement(
            _mutated_token(span, line_no, orig_line, mut_line),
            removal_stays_falsy=False,
        ) and _reads_only_as_boolean(node)
    return False


def _unobservable_header_case(
    path: str, line_no: int, col: int, orig_line: str, mut_line: str
) -> bool:
    """Return True when the mutation only re-cased an HTTP header name in a lookup.

    HTTP header field names are case-insensitive (RFC 9110 §5.1), and every
    ``.headers`` mapping in this stack implements that: Starlette's
    ``Headers.__getitem__`` lowercases the key before comparing (verified on the
    installed version), and httpx/requests/aiohttp do the same. So
    ``request.headers.get("X-Bot-API-Key")`` and ``...get("x-bot-api-key")``
    return the identical value on every input — no test can tell them apart, and
    six of them survived as "real" on app/core/bot_auth_middleware.py.

    Deliberately narrow on both sides:

    - The receiver must be an ATTRIBUTE named ``headers`` (``x.headers.get``).
      A bare local ``headers = {...}`` is an ordinary dict built for an OUTGOING
      request, where case is preserved and a re-cased lookup really does miss.
    - The change must be case-ONLY. mutmut also rewrites the literal to
      ``"XXX-Bot-API-KeyXX"``, which asks for a different header entirely and is
      exactly as observable as any other wrong key.
    """
    try:
        tree = ast.parse(Path(path).read_text())
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("get", "getlist")
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "headers"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            continue
        name = node.args[0]
        span = (
            name.lineno,
            name.col_offset,
            name.end_lineno or name.lineno,
            name.end_col_offset,
        )
        if not _within(span, line_no, col):
            continue
        replacement = _mutated_token(span, line_no, orig_line, mut_line)
        if replacement is None:
            return False
        try:
            mutated = ast.literal_eval(replacement.strip())
        except (ValueError, SyntaxError):
            return False
        original = name.value
        return (
            isinstance(mutated, str) and mutated != original and mutated.lower() == original.lower()
        )
    return False


def _unobservable_response_header_case(
    path: str, line_no: int, col: int, orig_line: str, mut_line: str
) -> bool:
    """Return True when the mutation only re-cased a header name a Response is SENDING.

    The sibling rule above covers header LOOKUPS and is deliberately narrow
    about outgoing dicts, because a dict built for an outgoing REQUEST does
    preserve case. A Response is the one outgoing case where it does not:
    Starlette's ``Response.init_headers`` lowercases every key on the way to
    ``raw_headers`` (verified on the installed starlette 1.3.1 —
    ``JSONResponse(headers={"Retry-After": "30"})``,
    ``{"retry-after": ...}`` and ``{"RETRY-AFTER": ...}`` all emit the identical
    ``(b"retry-after", b"30")``). No client can tell them apart because no
    client is ever sent anything different, so no test can either.

    Narrow on the same two axes as the lookup rule:

    - The dict must be the ``headers=`` keyword of a call whose name ends in
      ``Response``. A bare ``headers={...}`` handed to an HTTP client is an
      outgoing request, where case IS preserved on the wire.
    - The change must be case-ONLY. mutmut also rewrites the key to
      ``"XXRetry-AfterXX"``, which sends a different header entirely and is as
      observable as any other wrong key.
    """
    try:
        tree = ast.parse(Path(path).read_text())
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(getattr(node.func, "id", None) or getattr(node.func, "attr", ""), str)
            and (getattr(node.func, "id", None) or getattr(node.func, "attr", "")).endswith(
                "Response"
            )
        ):
            continue
        for keyword in node.keywords:
            if keyword.arg != "headers" or not isinstance(keyword.value, ast.Dict):
                continue
            for key in keyword.value.keys:
                if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                    continue
                span = (
                    key.lineno,
                    key.col_offset,
                    key.end_lineno or key.lineno,
                    key.end_col_offset,
                )
                if not _within(span, line_no, col):
                    continue
                replacement = _mutated_token(span, line_no, orig_line, mut_line)
                if replacement is None:
                    return False
                try:
                    mutated = ast.literal_eval(replacement.strip())
                except (ValueError, SyntaxError):
                    return False
                return (
                    isinstance(mutated, str)
                    and mutated != key.value
                    and mutated.lower() == key.value.lower()
                )
    return False


def _unobservable_ensure_ascii(
    path: str, line_no: int, col: int, orig_line: str, mut_line: str
) -> bool:
    """Return True when the mutation only swapped json.dumps' ensure_ascii for another falsy value.

    A ONE-OFF, not a rule. A keyword argument's truthiness semantics belong to
    the callee and the AST cannot know them in general — substituting None for
    False in an arbitrary keyword is usually observable. `ensure_ascii` earns
    an exception because json documents it as a truth VALUE ("If ensure_ascii
    is true, the output is guaranteed to be str...") and CPython reads it that
    way: json/encoder.py picks the encoder on `if self.ensure_ascii:`. Every
    falsy value therefore produces byte-identical output — verified on 3.12
    with the C encoder active, across False/None/0/""/[]/{} on non-ASCII
    payloads, with True the only value that differs. No other keyword belongs
    here without that same proof.
    """
    try:
        tree = ast.parse(Path(path).read_text())
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "dumps"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "json"
        ):
            continue
        for keyword in node.keywords:
            if keyword.arg != "ensure_ascii" or not _falsy_literal(keyword.value):
                continue
            value = keyword.value
            span = (
                value.lineno,
                value.col_offset,
                value.end_lineno or value.lineno,
                value.end_col_offset,
            )
            if _within(span, line_no, col):
                # Dropping the keyword entirely restores json's own default of
                # True, which is the one value that DOES change the output.
                return _falsy_replacement(
                    _mutated_token(span, line_no, orig_line, mut_line),
                    removal_stays_falsy=False,
                )
    return False


def _unreachable_match_arm(path: str, line_no: int) -> bool:
    """Return True when line_no sits in a ``case _: assert_never(...)`` arm.

    That arm exists for mypy, which uses it to prove the match exhaustive over
    the enum or union it switches on; at runtime no input reaches it. Deleting
    the arm, or its argument, changes no execution, so no test can kill the
    mutant — and the arm must stay, since it is what turns a new enum member
    into a type error instead of a silent fall-through. Seven of these survived
    as "real" on the playbook lifecycle's three match statements.
    """
    try:
        tree = ast.parse(Path(path).read_text())
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Match):
            continue
        for case in node.cases:
            wildcard = (
                isinstance(case.pattern, ast.MatchAs)
                and case.pattern.pattern is None
                and case.pattern.name is None
            )
            if not wildcard or len(case.body) != 1 or not isinstance(case.body[0], ast.Expr):
                continue
            call = case.body[0].value
            if not (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "assert_never"
            ):
                continue
            if case.pattern.lineno <= line_no <= (case.body[0].end_lineno or line_no):
                return True
    return False


# The callee defaults compared against below, hard-coded rather than read off
# the real callable with inspect.signature. The classifier is pure-AST and
# imports nothing outside the stdlib on purpose: the lane runs it once per
# survivor, and importing the callee's module to read a default would mean
# importing crawl4ai (which pulls in playwright and litellm) on every
# invocation — seconds of startup each, and a whole new failure mode, since an
# ImportError here fails the classifier closed and reports an unobservable
# mutant as CHANGED. Every value below was verified against the constructed
# object, not read off documentation: two BrowserConfigs built with and without
# these arguments have identical vars().
_CALLEE_ARG_DEFAULTS: dict[tuple[str, str], object] = {
    ("BrowserConfig", "headless"): True,
    ("BrowserConfig", "browser_mode"): "dedicated",
    ("BrowserConfig", "cdp_cleanup_on_close"): False,
    # int.from_bytes(bytes, byteorder="big", *, signed=False) — the default has
    # been "big" since Python 3.11, and this repo runs 3.12.
    ("int.from_bytes", "byteorder"): "big",
}

# The same defaults for callees that take the argument positionally, by slot.
_CALLEE_POSITIONAL_NAMES: dict[tuple[str, int], str] = {
    ("int.from_bytes", 1): "byteorder",
}

_MISSING = object()


def _callee_name(func) -> str | None:
    """Dotted source name of a call's callee — ``BrowserConfig``, ``int.from_bytes``."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        prefix = _callee_name(func.value)
        return f"{prefix}.{func.attr}" if prefix else None
    return None


def _node_span(node):
    return (node.lineno, node.col_offset, node.end_lineno or node.lineno, node.end_col_offset)


def _literal_equals(node, expected: object) -> bool:
    """Return True when ``node`` is a literal equal to ``expected``, same type and all."""
    try:
        value = ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return False
    # `True == 1` in Python, and a headless=1 would NOT be the default it looks like.
    return type(value) is type(expected) and value == expected


def _argument_at(span, line_no: int, col: int, orig_line: str) -> bool:
    """Return True when the mutation's column, or its whole line, is the argument at ``span``.

    The column alone is not enough for an argument mutmut DELETED off its own
    line: the body then shifts up, so the "differing column" is computed against
    whatever followed, and a closing ``)`` differs from the argument's indent
    rather than from the argument itself. An argument that occupies its entire
    line is identified by the line, not the column.
    """
    if _within(span, line_no, col):
        return True
    start_line, start_col, end_line, end_col = span
    if start_line != line_no or end_line != line_no:
        return False
    return not orig_line[:start_col].strip() and orig_line[end_col:].strip() in ("", ",")


def _argument_deleted(orig_line: str, mut_line: str, span, keyword: str | None) -> bool:
    """Return True when the mutant DELETED the argument at ``span`` rather than re-valuing it.

    mutmut removes the argument's text and its separator, so what is left of the
    original line is exactly what the mutant line must be. The second branch is
    the argument that WAS the whole line: mutmut drops the line outright, so the
    "mutant line" at this index is whatever followed it. Requiring the keyword to
    be gone from that line is what separates a deleted line from a re-valued one
    — ``headless=None,`` still reads ``headless=``.
    """
    start_line, start_col, end_line, end_col = span
    if start_line != end_line:
        return False
    end = end_col
    while end < len(orig_line) and orig_line[end] in ", ":
        end += 1
    without = orig_line[:start_col] + orig_line[end:]
    if without.rstrip() == mut_line.rstrip():
        return True
    if keyword is None:
        return False
    return not without.strip() and f"{keyword}=" not in mut_line


def _unobservable_default_argument(
    path: str, line_no: int, col: int, orig_line: str, mut_line: str
) -> bool:
    """Return True when the mutation only deleted an argument whose value IS the callee's default.

    ``BrowserConfig(headless=True, ...)`` states a value the class already
    defaults to, so dropping it constructs a byte-identical object and no test
    can tell. The argument is stated deliberately — it documents the intent and
    survives the library changing its default — so the line must stay, and the
    mutant cannot be killed. Deliberately NOT a blanket "a dropped argument is
    fine": the (callee, argument) pair must be in the table above AND carry
    exactly the default value there, and the mutation must be a DELETION —
    ``headless=False`` is the same argument with a real behavioral change, and
    is reported.
    """
    try:
        tree = ast.parse(Path(path).read_text())
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _callee_name(node.func)
        if name is None:
            continue
        for kw in node.keywords:
            if kw.arg is None or not _argument_at(_node_span(kw), line_no, col, orig_line):
                continue
            expected = _CALLEE_ARG_DEFAULTS.get((name, kw.arg), _MISSING)
            if expected is _MISSING or not _literal_equals(kw.value, expected):
                return False
            return _argument_deleted(orig_line, mut_line, _node_span(kw), kw.arg)
        for index, arg in enumerate(node.args):
            if not _argument_at(_node_span(arg), line_no, col, orig_line):
                continue
            slot = _CALLEE_POSITIONAL_NAMES.get((name, index))
            expected = (
                _CALLEE_ARG_DEFAULTS.get((name, slot), _MISSING) if slot is not None else _MISSING
            )
            if expected is _MISSING or not _literal_equals(arg, expected):
                return False
            return _argument_deleted(orig_line, mut_line, _node_span(arg), None)
    return False


# The two cache writers that serialise through ``serialize_any(value, model)``
# -> ``TypeAdapter(model or Any).dump_json(value)`` (app/db/redis.py).
_SERIALISING_CACHE_SETTERS = {"redis_cache.set", "set_cache"}


def _value_argument(node):
    """Return the ``value`` argument of a cache set call — second positional, or the kwarg."""
    for kw in node.keywords:
        if kw.arg == "value":
            return kw.value
    return node.args[1] if len(node.args) > 1 else None


def _unobservable_serialised_model_argument(
    path: str, line_no: int, col: int, orig_line: str, mut_line: str
) -> bool:
    """Return True when a cache write's ``model=C`` is dropped/None'd while the value IS a ``C(...)``.

    ``redis_cache.set`` serialises with ``TypeAdapter(model or Any).dump_json``,
    so ``model=`` only changes the bytes written when it has to coerce the value.
    Handed an instance of that very class, both adapters emit the same JSON —
    measured, not reasoned: ``TypeAdapter(ImportTokenRecord)`` and
    ``TypeAdapter(Any)`` both dump ``ImportTokenRecord(user_id="u1")`` as
    ``{"user_id":"u1"}``, with no warning under ``-W error``. The argument is
    stated deliberately (it documents the stored shape and matches the ``model=``
    the read side validates with), so the line stays and the mutant cannot die.
    Narrow on purpose: the value at THAT call site must be a direct ``C(...)``
    construction of the same class named by ``model=``. A dict or a variable
    there really is coerced by the adapter, and stays reported — as does any
    mutation of the key or the TTL, which are different spans.
    """
    try:
        tree = ast.parse(Path(path).read_text())
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _callee_name(node.func) not in _SERIALISING_CACHE_SETTERS:
            continue
        for kw in node.keywords:
            if kw.arg != "model" or not isinstance(kw.value, ast.Name):
                continue
            span = _node_span(kw)
            if not _argument_at(span, line_no, col, orig_line):
                continue
            value = _value_argument(node)
            if not (isinstance(value, ast.Call) and _callee_name(value.func) == kw.value.id):
                return False
            if _argument_deleted(orig_line, mut_line, span, kw.arg):
                return True
            replacement = _mutated_token(_node_span(kw.value), line_no, orig_line, mut_line)
            return replacement is not None and replacement.strip() == "None"
    return False


def _hostname_is_none(value: object) -> bool:
    """Return True when the default names no host: it is None, or a string urlparse finds no host in.

    Any other literal (an int, bytes) is not something this rule can reason
    about, so it answers False and the mutant stays a survivor. Only ValueError
    is caught, which urlparse raises for a genuinely malformed URL (an
    unparseable IPv6 literal) — that is an answer, not a bug. Anything else
    propagates: a swallowed NameError here once made this rule silently answer
    False for every mutant, which reads exactly like a correct classifier that
    simply never fires.
    """
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    try:
        return urlparse(value).hostname is None
    except ValueError:
        return False


def _unobservable_urlparse_host_default(
    path: str, line_no: int, col: int, orig_line: str, mut_line: str
) -> bool:
    """Return True when the mutation changed a ``.get()`` default that urlparse reads as no host.

    ``urlparse(origin.get("origin", "")).hostname`` is None for every value that
    is not a URL — "", None (what the lookup returns once mutmut drops the
    default), and mutmut's "XXXX" alike — so on the missing-key path every
    mutant yields the identical None and nothing downstream can tell them apart.
    Narrow on purpose: the mutated literal must be the DEFAULT of a lookup that
    is the sole argument of a ``urlparse()`` read only through ``.hostname``, and
    both the original and the replacement must actually resolve to no host.
    Mutating the lookup's KEY is a different span and stays reported — asking for
    a key that is not there really does lose the origin.
    """
    try:
        tree = ast.parse(Path(path).read_text())
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _callee_name(node.func) == "urlparse"):
            continue
        parent = getattr(node, "parent", None)
        if not (isinstance(parent, ast.Attribute) and parent.attr == "hostname"):
            continue
        if len(node.args) != 1 or not _lookup_with_default(node.args[0]):
            continue
        default = node.args[0].args[-1]
        span = _node_span(default)
        if not _within(span, line_no, col):
            continue
        replacement = _mutated_token(span, line_no, orig_line, mut_line)
        if replacement is None:
            return False
        stripped = replacement.strip()
        try:
            # An emptied slot is mutmut dropping the default entirely, and
            # ``.get(k)`` then hands back None.
            mutated = None if not stripped else ast.literal_eval(stripped)
            original = ast.literal_eval(default)
        except (ValueError, SyntaxError):
            return False
        return _hostname_is_none(original) and _hostname_is_none(mutated)
    return False


def _within(span, line_no: int, col: int) -> bool:
    start_line, start_col, end_line, end_col = span
    if line_no < start_line or line_no > end_line:
        return False
    if line_no == start_line and col < start_col:
        return False
    if line_no == end_line and col >= end_col:
        return False
    return True


def _first_differing_col(before: str, after: str) -> int:
    for i, (x, y) in enumerate(zip(before, after)):
        if x != y:
            return i
    return min(len(before), len(after))


# Mirrors _SCOPE_SEGMENT in tools/lints/tool_dump_boundary.py, as a module path
# relative to the repo root (the lint matches on an absolute path).
_TOOL_DUMP_LINT_SCOPE = "app/agents/tools/"


def _rejected_by_tool_dump_boundary(
    module_rel: str, path: str, line_no: int, col: int, orig_line: str
) -> bool:
    """Return True when the mutation rewrote a ``mode="json"`` on a tools-tree ``model_dump``.

    Not an equivalence claim — whether the dumped bytes differ depends on the
    model's fields. It is a different guard: tools/lints/tool_dump_boundary.py
    requires that literal on every ``model_dump`` under app/agents/tools/
    (issue #917), and the lint lane runs in this same gate, so a mutant that
    deletes, blanks or respells it cannot reach master. Reported under its own
    verdict so the exclusion is never read as a proof that the value cannot
    matter. Any other argument of the same call is still reported.
    """
    if not module_rel.startswith(_TOOL_DUMP_LINT_SCOPE):
        return False
    try:
        tree = ast.parse(Path(path).read_text())
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "model_dump"
        ):
            continue
        for kw in node.keywords:
            if kw.arg == "mode" and _literal_equals(kw.value, "json"):
                if _argument_at(_node_span(kw), line_no, col, orig_line):
                    return True
    return False


# Find the first differing line in the ORIGINAL file. `_body` drops only the
# def line itself, so body index 0 is the line right after it.
for i, (a, b) in enumerate(zip(orig_lines, mut_lines)):
    if a != b:
        line_no = orig_line + 1 + i
        # Diff scope FIRST. A logging mutant on a line the PR never touched is
        # already out of scope, and classifying it LOGGING inflates the
        # exclusion column into looking far more load-bearing than it is.
        ranges = json.loads(changed_ranges) if changed_ranges else []
        if not any(start <= line_no <= end for start, end in ranges):
            print(f"UNCHANGED:{line_no}")
            sys.exit(1)
        # Raw (un-normalized) lines: the cast() rewrite above shifts columns.
        col = _first_differing_col(orig_raw[i], mut_raw[i])
        real_path = f"{workdir}/{module_path}"
        if (
            _unobservable_get_default(real_path, line_no, col, orig_raw[i], mut_raw[i])
            or _unobservable_falsy_assignment(real_path, line_no, col, orig_raw[i], mut_raw[i])
            or _unobservable_ensure_ascii(real_path, line_no, col, orig_raw[i], mut_raw[i])
            or _unobservable_header_case(real_path, line_no, col, orig_raw[i], mut_raw[i])
            or _unobservable_response_header_case(real_path, line_no, col, orig_raw[i], mut_raw[i])
            or _unreachable_match_arm(real_path, line_no)
            or _unobservable_default_argument(real_path, line_no, col, orig_raw[i], mut_raw[i])
            or _unobservable_urlparse_host_default(real_path, line_no, col, orig_raw[i], mut_raw[i])
            or _unobservable_serialised_model_argument(
                real_path, line_no, col, orig_raw[i], mut_raw[i]
            )
        ):
            print("EQUIV")
            sys.exit(0)
        if _rejected_by_tool_dump_boundary(module_path, real_path, line_no, col, orig_raw[i]):
            print(f"LINTED:{line_no}")
            sys.exit(1)
        span = _excluded_span(real_path, line_no)
        if span is not None and _within(span, line_no, col):
            print(f"LOGGING:{line_no}")
            sys.exit(1)
        print(f"CHANGED:{line_no}")
        sys.exit(1)
print("EQUIV")
sys.exit(0)
