import typing as t

from app.constants.log_tags import LogTag
from shared.py.wide_events import log


def apply() -> None:
    try:
        from composio.utils import shared

        # Composio collapses anyOf items in arrays; flatten them into a real union
        original_json_schema_to_pydantic_type = shared.json_schema_to_pydantic_type

        def patched_json_schema_to_pydantic_type(
            json_schema: dict[str, t.Any] | bool,
        ) -> t.Union[type, t.Any | None]:
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
                from functools import reduce

                cast_types = [t.cast(type, ptype) for ptype in valid_types]
                return reduce(lambda a, b: t.Union[a, b], cast_types)  # type: ignore[arg-type,return-value]  # composio/langchain boundary typed Any upstream

            return original_json_schema_to_pydantic_type(json_schema)

        shared.json_schema_to_pydantic_type = patched_json_schema_to_pydantic_type

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
