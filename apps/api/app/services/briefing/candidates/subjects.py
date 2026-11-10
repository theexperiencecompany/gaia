"""When several tracked todos are one thing to the user, so the brief says it once."""

from app.models.todo_models import TodoDocument


def same_text_key(text: str) -> str:
    """Fold whitespace and case, so two spellings of one title compare equal."""
    return " ".join(text.split()).casefold()  # pragma: no mutate — spaced joins stay injective


def subject_key(doc: TodoDocument) -> str:
    """Return what makes todos one thing to the user: the outside thing it owns, a shared parent, else the same title.

    The inbox desk's threads share the desk as parent yet are one subject each.
    """
    if doc.external_ref is not None:
        return f"ref:{doc.external_ref.source.value}:{doc.external_ref.id}"
    return f"parent:{doc.parent_todo_id}" if doc.parent_todo_id else same_text_key(doc.title)
