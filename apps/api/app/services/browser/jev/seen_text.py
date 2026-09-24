"""What the run has read, page by page, across screens.

The closing summary is written from the current screen, so a list scrolled past
its first screenful, or a task that reads several pages, would otherwise be
answered from whatever happens to be showing at the end. This keeps every line
read on each page, in the order it was read and without repeats, and keeps the
pages in the order the run opened them.

The closing answer's budget is shared between the pages rather than spent in
reading order: a research run's first pages once used all of it, and the page
the task's last part was answered on reached the answer empty.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from app.constants.browser import JEV_SEEN_TEXT_MAX_CHARS


class ReadPage(TypedDict):
    """One page the run read: its url, title and how far down it was read."""

    url: str
    title: str
    read: Literal["to the end", "top part only"]


class SeenText:
    """Every distinct line read on each page the run has opened, oldest first."""

    def __init__(self) -> None:
        self._page = ""  # pragma: no mutate — no page is stored under any start value
        self._lines: dict[str, list[str]] = {}
        self._titles: dict[str, str] = {}
        self._seen: dict[str, set[str]] = {}
        self._to_the_end: set[str] = set()
        self._lengths: dict[str, int] = {}

    def record(self, url: str, text: str, title: str = "", *, at_bottom: bool = False) -> None:
        """Add this screen's lines to its page's memory; a page returned to keeps what it had."""
        self._page = url.partition("#")[0]
        if self._page.startswith("about:"):
            # The blank tab before the first navigate is no page read: judging it
            # spent a writer call on nothing, and a blocked run "reported" it.
            return
        if title and self._titles.get(self._page, title) != title:
            # A new document on the same url (a "Just a moment..." wall that cleared
            # into the list): the wall's bottom is not the list's.
            self._to_the_end.discard(self._page)
        if title:
            self._titles[self._page] = title
        if at_bottom:
            self._to_the_end.add(self._page)
        lines = self._lines.setdefault(self._page, [])
        seen = self._seen.setdefault(self._page, set())
        length = self._lengths.get(self._page, 0)
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped in seen:
                continue
            if length + len(stripped) + 1 > JEV_SEEN_TEXT_MAX_CHARS:
                break
            seen.add(stripped)
            lines.append(stripped)
            length += len(stripped) + 1
        self._lengths[self._page] = length

    @property
    def text(self) -> str:
        """What was read on the current page."""
        return "\n".join(self._lines.get(self._page, []))

    @property
    def pages(self) -> list[ReadPage]:
        """The pages read, oldest first, each as its url, title and how far down it was read.

        A page counts as read to the end once a screen of it showed its bottom;
        until then only its top part has been read, which a judgement of "every
        item counted" or "the whole list seen" has to know.
        """
        return [
            ReadPage(
                url=page,
                title=self._titles.get(page, ""),
                read="to the end" if page in self._to_the_end else "top part only",
            )
            for page in self._lines
        ]

    @property
    def all_text(self) -> str:
        """What was read on every page, each under its URL, within the one budget for them all.

        A page shorter than an equal share keeps all of it; the longer pages split
        what is left equally, each cut to its first lines.
        """
        pages = [page for page, lines in self._lines.items() if lines]
        shares = _fair_shares([self._lengths[page] for page in pages], JEV_SEEN_TEXT_MAX_CHARS)
        return "\n\n".join(
            f"## {page}\n" + "\n".join(_first_lines(self._lines[page], share))
            for page, share in zip(pages, shares, strict=True)
        )


def _fair_shares(sizes: list[int], budget: int) -> list[int]:
    """Split budget so no size gets more than it needs and the rest share alike."""
    shares = [0] * len(sizes)  # pragma: no mutate — the loop assigns every share
    left = budget
    by_size = sorted(range(len(sizes)), key=sizes.__getitem__)
    for taken, index in enumerate(by_size):
        shares[index] = min(sizes[index], left // (len(sizes) - taken))
        left -= shares[index]
    return shares


def _first_lines(lines: list[str], chars: int) -> list[str]:
    """Return the leading lines that fit in chars, a newline counted after each."""
    kept: list[str] = []
    used = 0
    for line in lines:
        used += len(line) + 1
        if used > chars:
            break
        kept.append(line)
    return kept


__all__ = ["SeenText"]
