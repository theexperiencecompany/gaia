"""What the user said while a run went, as a model reads it: a replacement of the request named as one only when they made it one."""


def what_the_user_said(
    user_notes: list[str], redirects: list[str], *, replaced: str, said: str
) -> str:
    """Fill replaced with the notes that replaced the request and said with the rest, quoted in order; empty when the user said nothing."""
    sections = []
    if redirects:
        sections.append(replaced.format(notes=_in_order(redirects)))
    others = [note for note in user_notes if note not in redirects]
    if others:
        sections.append(said.format(notes=_in_order(others)))
    return "\n\n".join(sections)


def _in_order(notes: list[str]) -> str:
    return ", then ".join(f'"{note}"' for note in notes)
