"""Reduce a response key a provider repeats across streamed chunks to its first value."""

from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk


def keep_first_response_key(chunk: ChatGenerationChunk, key: str, kept_so_far: int) -> int:
    """Drop key from every chunk after the first; return 1 if this one kept it.

    merge_dicts concatenates repeated string keys, so provider and finish_reason double
    ("BaiduBaidu", "stopstop"); a live 8-chunk answer carried two finish events, so
    first-one-wins reports the earlier one if they disagree. generation_info is stripped
    too: BaseChatModel.stream _gen_info_and_msg_metadata (chat_models.py:781/914) re-merges it.
    """
    if not isinstance(chunk.message, AIMessageChunk):
        return 0
    if key not in chunk.message.response_metadata and key not in (chunk.generation_info or {}):
        return 0
    if kept_so_far > 0:
        chunk.message.response_metadata.pop(key, None)
        if chunk.generation_info is not None:
            chunk.generation_info.pop(key, None)
        return 0
    return 1
