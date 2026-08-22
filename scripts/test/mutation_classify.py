"""Classify one surviving mutant: CHANGED / UNCHANGED / LOGGING / EQUIV.

Extracted from mutation.sh, where it lived twice verbatim — once for the
survivor loop and once for the no-covering-test loop. Two copies of 356 lines
is a fix applied twice and a divergence waiting to happen, so it is one file
invoked from both.

Argv: <survivor-line> <workdir> <changed-ranges-json> <module-path>

Prints exactly one verdict and exits 1 for a verdict the lane must act on
(CHANGED/UNCHANGED/LOGGING) or 0 for EQUIV. Any other exit is a classifier
failure, and the caller fails closed on it rather than dropping the mutant —
an unclassified survivor silently leaving every bucket is the same
silence-read-as-success this gate exists to stop.
"""

import ast
import json
from pathlib import Path
import re
import sys

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
        # Scan the FIRST argument with bracket/quote balancing: a type arg
        # like ``dict[str, object] | None`` (or a quoted forward ref) holds
        # commas a regex stops at, and a half-blanked cast then reads as a
        # real change.
        i = start + len("cast(")
        depth = 0
        quote: str | None = None
        while i < len(joined):
            ch = joined[i]
            if quote:
                if ch == quote and joined[i - 1] != "\\":
                    quote = None
            elif ch in "\"'":
                quote = ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                if depth == 0:
                    break  # cast with one argument — not ours to touch
                depth -= 1
            elif ch == "," and depth == 0:
                break
            i += 1
        if i < len(joined) and joined[i] == ",":
            arg = joined[start + len("cast(") : i]
            out.append(joined[pos:start] + "cast(" + "\n" * arg.count("\n") + "_")
        else:
            out.append(joined[pos:i])
        pos = i
    out.append(joined[pos:])
    return "".join(out).split("\n")


orig_raw = _body(orig_name)
mut_raw = _body(mutant_name)
orig_lines = _normalized(orig_raw)
mut_lines = _normalized(mut_raw)
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
    """True for a literal that is falsy — None/False/0/"" and empty containers."""
    if isinstance(node, ast.Constant):
        return not node.value
    if isinstance(node, ast.List | ast.Tuple | ast.Set):
        return not node.elts
    if isinstance(node, ast.Dict):
        return not node.keys
    return False


def _mutated_token(span, line_no: int, orig_line: str, mut_line: str) -> str | None:
    """The text the mutation put where the literal at ``span`` was, or None.

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


def _falsy_replacement(replacement: str | None) -> bool:
    """True when the mutation put another falsy literal where the original was."""
    if replacement is None:
        return False
    stripped = replacement.strip()
    if not stripped:
        return True  # the argument was removed; the default becomes None
    try:
        return not ast.literal_eval(stripped)
    except (ValueError, SyntaxError):
        return False


def _boolean_consumer(node) -> bool:
    """True when node's own value reaches only a test every falsy value answers alike."""
    parent = getattr(node, "parent", None)
    if isinstance(parent, ast.BoolOp) and isinstance(parent.op, ast.Or):
        # `x or y` evaluates to y for EVERY falsy x, so which falsy x it was is lost.
        return parent.values[-1] is not node
    if isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not):
        # `not x` is True for every falsy x — the distinction dies here no
        # matter where the result then flows.
        return True
    return isinstance(parent, ast.If | ast.IfExp) and parent.test is node


def _early_exit_on_falsy(stmt, name: str) -> bool:
    """True for ``if not name: <exit>`` — everything after runs only on truthy."""
    return (
        isinstance(stmt, ast.If)
        and not stmt.orelse
        and isinstance(stmt.test, ast.UnaryOp)
        and isinstance(stmt.test.op, ast.Not)
        and isinstance(stmt.test.operand, ast.Name)
        and stmt.test.operand.id == name
        and all(isinstance(s, ast.Return | ast.Raise | ast.Continue | ast.Break) for s in stmt.body)
    )


def _guarded_by(node, name: str) -> bool:
    """True when node sits in code that runs only while `name` is truthy."""
    child = node
    parent = getattr(node, "parent", None)
    while parent is not None:
        test = getattr(parent, "test", None)
        if (
            isinstance(parent, ast.If | ast.IfExp)
            and isinstance(test, ast.Name)
            and test.id == name
        ):
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


def _only_boolean_uses(call) -> bool:
    """True when nothing downstream of `call` can tell one falsy value from another."""
    call = _through_casts(call)
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
    """True for ``x.get(k, d)``, ``x.pop(k, d)`` or ``getattr(o, n, d)``.

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
    """True when the mutation only changed a .get() default nothing can observe.

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
        return _falsy_replacement(
            _mutated_token(span, line_no, orig_line, mut_line)
        ) and _only_boolean_uses(_outermost_lookup(node))
    return False


def _unobservable_ensure_ascii(
    path: str, line_no: int, col: int, orig_line: str, mut_line: str
) -> bool:
    """True when the mutation only swapped json.dumps' ensure_ascii for another falsy value.

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
                return _falsy_replacement(_mutated_token(span, line_no, orig_line, mut_line))
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
        if _unobservable_get_default(
            real_path, line_no, col, orig_raw[i], mut_raw[i]
        ) or _unobservable_ensure_ascii(real_path, line_no, col, orig_raw[i], mut_raw[i]):
            print("EQUIV")
            sys.exit(0)
        span = _excluded_span(real_path, line_no)
        if span is not None and _within(span, line_no, col):
            print(f"LOGGING:{line_no}")
            sys.exit(1)
        print(f"CHANGED:{line_no}")
        sys.exit(1)
print("EQUIV")
sys.exit(0)
