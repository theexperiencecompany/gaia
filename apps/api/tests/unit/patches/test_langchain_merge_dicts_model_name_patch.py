"""Tests for the merge_dicts model_name idempotency patch.

``AIMessageChunk.__add__`` merges chunk ``response_metadata`` via
``langchain_core.utils._merge.merge_dicts``, which concatenates equal string
values for any key outside its small idempotent set (id/output_version/
model_provider). ChatOpenRouter can stamp ``model_name`` on more than one
chunk of the same stream, so two equal model names get concatenated into a
name matching no pricing entry ("modelmodel"). The patch adds "model_name" to
the idempotent set.
"""

from __future__ import annotations

from langchain_core.messages import AIMessageChunk

# Importing the patch module rebinds merge_dicts at import time.
import app.patches.langchain_merge_dicts_model_name_patch as patch_module


class TestMergeDicts:
    def test_equal_model_name_values_are_not_concatenated(self) -> None:
        merged = patch_module.merge_dicts(
            {"model_name": "deepseek/deepseek-v4-flash-0731"},
            {"model_name": "deepseek/deepseek-v4-flash-0731"},
        )
        assert merged["model_name"] == "deepseek/deepseek-v4-flash-0731"

    def test_differing_model_name_values_still_concatenate(self) -> None:
        # Unchanged from upstream: idempotency only applies when both sides agree.
        merged = patch_module.merge_dicts({"model_name": "a"}, {"model_name": "b"})
        assert merged["model_name"] == "ab"

    def test_id_output_version_model_provider_stay_idempotent(self) -> None:
        merged = patch_module.merge_dicts(
            {"id": "run-1", "output_version": "v0", "model_provider": "openrouter"},
            {"id": "run-1", "output_version": "v0", "model_provider": "openrouter"},
        )
        assert merged == {"id": "run-1", "output_version": "v0", "model_provider": "openrouter"}

    def test_other_string_keys_still_concatenate(self) -> None:
        # finish_reason (and any other ordinary string field) keeps the original
        # concatenation behavior -- only the named identity fields are idempotent.
        merged = patch_module.merge_dicts({"finish_reason": "stop"}, {"finish_reason": "stop"})
        assert merged["finish_reason"] == "stopstop"


class TestAIMessageChunkMerge:
    def test_two_chunks_stamping_the_same_model_name_merge_to_one_name(self) -> None:
        # The real bug shape: ChatOpenRouter stamps response_metadata["model_name"]
        # on more than one chunk of a stream; AIMessageChunk.__add__ must not turn
        # that into a doubled pricing key.
        first = AIMessageChunk(
            content="",
            response_metadata={"model_name": "deepseek/deepseek-v4-flash-0731"},
        )
        second = AIMessageChunk(
            content="",
            response_metadata={"model_name": "deepseek/deepseek-v4-flash-0731"},
        )
        merged = first + second
        assert merged.response_metadata["model_name"] == "deepseek/deepseek-v4-flash-0731"


class TestApply:
    def test_merge_module_is_rebound_to_the_wrapper(self) -> None:
        from langchain_core.utils import _merge

        assert _merge.merge_dicts is patch_module.merge_dicts

    def test_messages_ai_module_is_rebound_to_the_wrapper(self) -> None:
        from langchain_core.messages import ai

        assert ai.merge_dicts is patch_module.merge_dicts

    def test_apply_keeps_the_rebinding(self) -> None:
        patch_module.apply()

        from langchain_core.messages import ai

        assert ai.merge_dicts is patch_module.merge_dicts
