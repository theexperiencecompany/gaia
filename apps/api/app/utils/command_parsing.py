from __future__ import annotations

from typing import Optional


def extract_output_redirect(
    command_str: str,
) -> tuple[str, Optional[tuple[str, str]]]:
    """Extract a trailing output redirect.

    Supports:
    - > "path with spaces"
    - > 'path with spaces'
    - > path_no_spaces
    - >file.txt (no separating space)

    Returns:
        (command_without_redirect, (mode, filepath)) or (original, None)
    """
    s = command_str.rstrip()
    if not s:
        return command_str, None

    end = len(s)

    def _find_opening_double_quote(text: str, closing_quote_index: int) -> int | None:
        # Find matching opening quote for text[closing_quote_index] == '"',
        # respecting backslash escapes (\").
        i = closing_quote_index - 1
        while i >= 0:
            if text[i] != '"':
                i -= 1
                continue

            bs = 0
            j = i - 1
            while j >= 0 and text[j] == "\\":
                bs += 1
                j -= 1
            if bs % 2 == 0:
                return i
            i -= 1
        return None

    filepath: str
    prefix: str

    if s.endswith('"'):
        open_idx = _find_opening_double_quote(s, end - 1)
        if open_idx is None:
            return command_str, None
        filepath = s[open_idx + 1 : end - 1]
        prefix = s[:open_idx]
        if not filepath:
            return command_str, None
    elif s.endswith("'"):
        open_idx = s.rfind("'", 0, end - 1)
        if open_idx == -1:
            return command_str, None
        filepath = s[open_idx + 1 : end - 1]
        prefix = s[:open_idx]
        if not filepath:
            return command_str, None
    else:
        i = end
        while i > 0 and not s[i - 1].isspace():
            i -= 1
        filepath = s[i:end]
        prefix = s[:i]
        if not filepath:
            return command_str, None

        if filepath.startswith(">>") and len(filepath) > 2:
            return prefix.rstrip(), (">>", filepath[2:])
        if filepath.startswith(">") and len(filepath) > 1:
            return prefix.rstrip(), (">", filepath[1:])

    j = len(prefix)
    while j > 0 and prefix[j - 1].isspace():
        j -= 1
    prefix = prefix[:j]

    mode: str
    if prefix.endswith(">>"):
        mode = ">>"
        command_without_redirect = prefix[:-2].rstrip()
    elif prefix.endswith(">"):
        mode = ">"
        command_without_redirect = prefix[:-1].rstrip()
    else:
        return command_str, None

    return command_without_redirect, (mode, filepath)
