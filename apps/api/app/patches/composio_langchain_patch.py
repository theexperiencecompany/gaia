import typing as t

from app.constants.log_tags import LogTag
from shared.py.wide_events import log


def apply() -> None:
    try:
        from composio.utils import shared  # noqa: PLC0415 -- patched symbols resolve in apply()
        from langchain_core.tools import base as lc_base  # noqa: PLC0415 -- resolves in apply()
        from pydantic import ValidationError  # noqa: PLC0415 -- grouped with the patch body

        # Patch 1: Composio flattening anyOf items in arrays
        original_json_schema_to_pydantic_type = shared.json_schema_to_pydantic_type

        def patched_json_schema_to_pydantic_type(
            json_schema: dict[str, t.Any] | bool,
        ) -> t.Union[type, t.Any | None]:  # noqa: ANN401 -- framework contract
            # Boolean JSON Schemas (draft-06+, e.g. bare `true`/`false` sub-schemas)
            # have no "anyOf" to flatten — delegate straight to the original,
            # which already handles them (isinstance(json_schema, bool) branch).
            if isinstance(json_schema, dict) and "anyOf" in json_schema:
                options = json_schema["anyOf"]
                pydantic_types = [patched_json_schema_to_pydantic_type(o) for o in options]
                valid_types = [pt for pt in pydantic_types if pt is not None and pt is not dict]
                if len(valid_types) == 1:
                    return valid_types[0]
                if len(valid_types) == 0:
                    return str
                from functools import reduce  # noqa: PLC0415 -- used once, kept at call site

                cast_types = [t.cast(type, ptype) for ptype in valid_types]
                return reduce(lambda a, b: t.Union[a, b], cast_types)  # type: ignore[arg-type,return-value]  # Union constructed dynamically via reduce; typeshed can't express it

            return original_json_schema_to_pydantic_type(json_schema)

        shared.json_schema_to_pydantic_type = patched_json_schema_to_pydantic_type

        # Patch 2: Langchain swallowing Tool Validation Errors
        # If we just override _handle_validation_error, that gets called from inside BaseTool._run
        def patched_handle_validation_error(
            e: t.Union[ValidationError, Exception],
            *,
            flag: t.Union[bool, str, t.Callable[[t.Any], str]],
        ) -> str:
            if isinstance(flag, str):
                return flag
            # bool is not callable, but check it explicitly: `callable()` cannot
            # narrow a bool out on its own, and True must fall through to the
            # real message rather than be invoked.
            if not isinstance(flag, bool) and callable(flag):
                return flag(e)
            # flag is True (langchain's "handle it" signal) or something outside
            # the documented union — either way, surface the actual error, which
            # is the whole point of this patch.
            return f"Tool input validation error: {e!s}"

        lc_base._handle_validation_error = patched_handle_validation_error

        log.info(f"{LogTag.PATCH} Applied composio_langchain_patch", patch="composio_langchain")
    except Exception as e:
        log.error(
            f"{LogTag.PATCH} Failed to apply composio langchain patch",
            patch="composio_langchain",
            error=str(e),
            error_type=type(e).__name__,
        )


# Call it directly on importing
apply()
