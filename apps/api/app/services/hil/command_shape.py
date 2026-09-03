"""Reduce a CLI tool call's shell string to the key its risk is classified under.

A CLI integration exposes exactly ONE tool (``run_gh``), so the tool name carries no
risk information: ``gh pr list`` and ``gh repo delete acme/api`` arrive under it alike.
What carries the risk is the command, and what makes a command cacheable is its
*shape* — the leading command words of every program the string would run, with flags,
arguments and redirection targets dropped::

    gh pr list --json number | jq .          ->  gh pr list ; jq
    LOG=1 link-cli spend-request create -x   ->  link-cli spend-request create

Derived structurally, never from a per-vendor table of dangerous verbs: a table only
knows the CLIs somebody thought to enumerate, and the long tail nobody enumerated is
precisely why running a real CLI is worth doing (see ``agents/tools/cli/cli_tool``).

Two rules carry the safety weight:

* **Every chained command is in the shape.** Keeping only the first would let
  ``gh pr list && gh repo delete acme/api`` cache under a verdict earned by
  ``gh pr list`` — one harmless prefix and the gate is off for everything behind it.
  Command substitution counts as chaining for the same reason.
* **Unshapeable is empty.** ``""`` comes back for anything this cannot reduce (an
  unbalanced quote, a segment that is only flags, an empty string), and the caller
  gates on it rather than guessing what an unparseable command does.
"""

from collections.abc import Mapping
import re
import shlex
from typing import Any, Final

from langchain_core.tools import BaseTool

from app.agents.tools.cli.cli_tool import CLI_INTEGRATION_METADATA_KEY
from app.constants.hil import HIL_CLI_SHAPE_MAX_WORDS

# The argument the shell string arrives in — ``CliToolInput.command``.
CLI_COMMAND_ARG: Final = "command"

# Metacharacters that end one command and begin another. ``(``, ``)`` and the backtick
# are in here because command substitution RUNS what it wraps: without them
# ``echo $(gh repo delete acme/api)`` would shape as a harmless bare ``echo``.
_SEPARATOR_CHARS: Final = frozenset(";&|()`\n")

# Everything the lexer must hand back as its own token instead of gluing onto a word.
# The redirection operators are not separators (they take a target, not a command) but
# must still break the run of command words.
_PUNCTUATION_CHARS: Final = "".join(sorted(_SEPARATOR_CHARS | {"<", ">"}))

# Newline separates commands here, so it must not be eaten as whitespace first.
_WHITESPACE: Final = " \t\r"

# A shape word: a plain command or subcommand name. Anything carrying an argument's
# shape — a flag, a path, a URL, a number, a quoted phrase — fails this and ends the
# run, which is what keeps one shape stable across calls that differ only in target.
_SHAPE_WORD: Final = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")

# ``FOO=bar cmd ...`` — an environment prefix, not the command being run.
_ENV_ASSIGNMENT: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# How the shapes of chained commands are joined. One joiner for every separator kind:
# what the classifier needs to know is that all of them run, not how they are wired.
_JOINER: Final = " ; "


def cli_command_shape(tool: BaseTool | None, args: Mapping[str, Any] | None) -> str | None:
    """The shape of the command a CLI-backed call would run.

    ``None`` — and only ``None`` — means "not a CLI tool", which leaves the caller
    classifying by tool name exactly as before. A CLI tool whose ``command`` argument
    is missing or not a string yields ``""``, which gates.
    """
    metadata = getattr(tool, "metadata", None)
    if not isinstance(metadata, dict) or CLI_INTEGRATION_METADATA_KEY not in metadata:
        return None
    command = args.get(CLI_COMMAND_ARG) if args else None
    return derive_command_shape(command) if isinstance(command, str) else ""


# Commands that take another command as an argument. The shape of the wrapper
# says nothing about the shape of what it runs, so these fail closed rather than
# resolve to a reassuring head word.
_SHELL_EXEC_WRAPPERS = frozenset(
    {
        "sh",
        "bash",
        "zsh",
        "dash",
        "ksh",
        "eval",
        "exec",
        "env",
        "xargs",
        "nohup",
        "timeout",
        "sudo",
        "doas",
        "nice",
        "setsid",
        "watch",
        "command",
    }
)


def derive_command_shape(command: str) -> str:
    """The classification key for one shell string, or ``""`` when it has none."""
    try:
        tokens = _tokenize(command)
    except ValueError:
        # An unterminated quote: where it was meant to close decides what runs, and
        # guessing is exactly the wrong call for a gate.
        return ""
    shapes: list[str] = []
    for segment in _segments(tokens):
        head = _leading_words(segment)
        if not head:
            return ""
        shapes.append(head)
    return _JOINER.join(shapes)


def _tokenize(command: str) -> list[str]:
    """Split like a shell would: quotes honoured, metacharacters as their own tokens.

    Raises ``ValueError`` on an unterminated quote.
    """
    lexer = shlex.shlex(command, posix=True, punctuation_chars=_PUNCTUATION_CHARS)
    lexer.whitespace = _WHITESPACE
    lexer.whitespace_split = True
    # shlex honours `#` as a comment even in the MIDDLE of a word and discards
    # the rest of the line; a POSIX shell only starts a comment at the start of
    # a word. Left on, `gh api /user#x && gh repo delete acme/api` tokenizes to
    # `gh api` and the delete disappears from the shape entirely, so the gate
    # judges a prefix and runs the whole string. Nothing here needs comment
    # handling: only the shape words matter.
    lexer.commenters = ""
    return list(lexer)


def _segments(tokens: list[str]) -> list[list[str]]:
    """The token runs between separators — one per command the string would run."""
    segments: list[list[str]] = [[]]
    for token in tokens:
        if _is_separator(token):
            segments.append([])
        else:
            segments[-1].append(token)
    return [segment for segment in segments if segment]


def _is_separator(token: str) -> bool:
    return bool(token) and all(char in _SEPARATOR_CHARS for char in token)


def _leading_words(segment: list[str]) -> str:
    """One command's leading words, or ``""`` when it has none to take.

    A segment with no words is not "harmless": ``--force`` alone, a bare redirection,
    a path-qualified executable — none of them shape, so all of them gate.

    Neither does a segment whose head hands the real command to another shell.
    ``sh -c 'gh repo delete acme/api'`` would otherwise shape as a bare ``sh``:
    the payload is a quoted argument, not a separator, so it never becomes its
    own segment, and the classifier would judge a command name that says nothing
    about what runs.
    """
    if segment and segment[0] in _SHELL_EXEC_WRAPPERS:
        return ""
    words: list[str] = []
    for token in segment:
        if not words and _ENV_ASSIGNMENT.match(token):
            continue
        if not _SHAPE_WORD.match(token):
            break
        words.append(token)
        if len(words) == HIL_CLI_SHAPE_MAX_WORDS:
            break
    return " ".join(words)
