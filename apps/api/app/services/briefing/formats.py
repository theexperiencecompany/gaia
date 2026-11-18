"""How the brief writes the things it says more than once: a text's opening line."""


def opening_line(text: str) -> str:
    """Return a text's first non-blank line, stripped; empty when it has none."""
    return next((line.strip() for line in text.splitlines() if line.strip()), "")
