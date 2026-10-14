"""Stop model_name from being concatenated with itself across merged AI message chunks.

langchain_core.utils._merge.merge_dicts treats id/output_version/model_provider
as idempotent when both sides match, but not model_name — so when
ChatOpenRouter legitimately stamps response_metadata["model_name"] on two
chunks of the same stream (e.g. deepseek's reasoning + content finish
events), AIMessageChunk.__add__ concatenates the equal strings instead of
collapsing them: "x" + "x" -> "xx". UsageMetadataCallbackHandler then reads
that doubled string as the pricing lookup key, silently billing every such
call at DEFAULT_PRICING instead of its real rate.

Copies merge_dicts verbatim and adds model_name to the idempotent set, then
rebinds the name in every module that imported it directly (patching
_merge.merge_dicts alone doesn't reach them). Unreported upstream as of
langchain-core 1.x; drop once model_name joins the upstream idempotent set.
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

# Modules that did `from ._merge import merge_dicts` hold their own reference,
# so patching _merge alone doesn't reach them. Typed Any: the rebind writes an
# attribute typeshed doesn't declare, which ModuleType would reject.
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
    """Merge dicts like upstream, but treat id/output_version/model_provider/model_name as idempotent strings."""
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
    """Rebind the module-level merge_dicts name everywhere it was imported."""
    _merge_module.merge_dicts = merge_dicts
    for module in _REBIND_TARGETS:
        module.merge_dicts = merge_dicts


apply()
