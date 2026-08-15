"""Stop ``model_name`` from being concatenated with itself across merged AI message
chunks.

``langchain_core.utils._merge.merge_dicts`` already treats a handful of string keys
("id", "output_version", "model_provider") as idempotent when both sides carry the
same value — but not "model_name". ``ChatOpenRouter._astream``/``_stream``
(langchain_openrouter) can legitimately stamp ``response_metadata["model_name"]`` on
more than one chunk of the same stream (deepseek reasoning models emit a finish event
for the reasoning block and another for the final content block, both carrying the
same model name). ``AIMessageChunk.__add__`` (``langchain_core.messages.ai``) merges
those chunks' ``response_metadata`` via ``merge_dicts``, and since "model_name" isn't
in the idempotent set, two equal values get string-concatenated instead of collapsed:

    "deepseek/deepseek-v4-flash-0731" + "deepseek/deepseek-v4-flash-0731"
    -> "deepseek/deepseek-v4-flash-0731deepseek/deepseek-v4-flash-0731"

``UsageMetadataCallbackHandler`` reads that doubled string as the model id
(``langchain_core.callbacks.usage``), and ``_record_auxiliary_usage``
(``app/agents/llm/client.py``) uses it as the pricing lookup key. The doubled id
matches nothing in the pricing catalog, so every auxiliary call metered this way is
silently charged at ``DEFAULT_PRICING`` instead of its real (much cheaper) rate.

This copies ``merge_dicts`` verbatim from ``langchain_core.utils._merge`` and adds
"model_name" to the existing idempotent-string-key set, then rebinds the name in
every module that imported it directly (a module-level ``from x import merge_dicts``
holds its own reference — patching ``_merge.merge_dicts`` alone does not reach them).
Unreported upstream as of langchain-core 1.x. Drop this patch once "model_name" joins
the upstream idempotent set.
"""

from typing import Any

from langchain_core.messages import (
    ai as _ai_messages,
    base as _base_messages,
    chat as _chat_messages,
    function as _function_messages,
    tool as _tool_messages,
)
from langchain_core.outputs import chat_generation as _chat_generation, generation as _generation
from langchain_core.utils import _merge as _merge_module

_IDEMPOTENT_STRING_KEYS = frozenset({"id", "output_version", "model_provider", "model_name"})

# Modules that did `from ._merge import merge_dicts`, so each holds its own
# reference that patching `_merge` alone cannot reach. Typed as Any because the
# rebind below writes an attribute typeshed does not declare on them — the whole
# point of a monkeypatch — and `ModuleType` would reject the assignment.
_REBIND_TARGETS: tuple[Any, ...] = (
    _ai_messages,
    _base_messages,
    _chat_messages,
    _function_messages,
    _tool_messages,
    _chat_generation,
    _generation,
)


def merge_dicts(left: dict[str, Any], *others: dict[str, Any]) -> dict[str, Any]:
    r"""Merge dictionaries, treating equal-valued identity/metadata strings
    (id, output_version, model_provider, model_name) as idempotent instead of
    concatenating them. Otherwise identical to the upstream implementation."""
    merged = left.copy()
    for right in others:
        for right_k, right_v in right.items():
            if right_k not in merged or (right_v is not None and merged[right_k] is None):
                merged[right_k] = right_v
            elif right_v is None:
                continue
            elif type(merged[right_k]) is not type(right_v):
                msg = (
                    f'additional_kwargs["{right_k}"] already exists in this message,'
                    " but with a different type."
                )
                raise TypeError(msg)
            elif isinstance(merged[right_k], str):
                if (right_k == "index" and merged[right_k].startswith("lc_")) or (
                    right_k in _IDEMPOTENT_STRING_KEYS and merged[right_k] == right_v
                ):
                    continue
                merged[right_k] += right_v
            elif isinstance(merged[right_k], dict):
                merged[right_k] = merge_dicts(merged[right_k], right_v)
            elif isinstance(merged[right_k], list):
                merged[right_k] = _merge_module.merge_lists(merged[right_k], right_v)
            elif merged[right_k] == right_v:
                continue
            elif isinstance(merged[right_k], int):
                if right_k in {"index", "created", "timestamp"}:
                    merged[right_k] = right_v
                else:
                    merged[right_k] += right_v
            else:
                msg = (
                    f"Additional kwargs key {right_k} already exists in left dict and "
                    f"value has unsupported type {type(merged[right_k])}."
                )
                raise TypeError(msg)
    return merged


def apply() -> None:
    """Rebind the module-level `merge_dicts` name everywhere it was imported."""
    _merge_module.merge_dicts = merge_dicts
    for module in _REBIND_TARGETS:
        module.merge_dicts = merge_dicts


apply()
