import typing as t


def apply():
    try:
        from composio.utils import shared
        from langchain_core.tools import base as lc_base
        from pydantic import ValidationError

        # Patch 1: Composio flattening anyOf items in arrays
        original_json_schema_to_pydantic_type = shared.json_schema_to_pydantic_type

        def patched_json_schema_to_pydantic_type(
            json_schema: t.Dict[str, t.Any],
        ) -> t.Union[t.Type, t.Optional[t.Any]]:
            if "anyOf" in json_schema:
                options = json_schema["anyOf"]
                pydantic_types = [
                    patched_json_schema_to_pydantic_type(o) for o in options
                ]
                valid_types = [
                    pt for pt in pydantic_types if pt is not None and pt is not dict
                ]
                if len(valid_types) == 1:
                    return valid_types[0]
                if len(valid_types) == 0:
                    return str
                from functools import reduce

                cast_types = [t.cast(t.Type, ptype) for ptype in valid_types]
                return reduce(lambda a, b: t.Union[a, b], cast_types)  # type: ignore

            return original_json_schema_to_pydantic_type(json_schema)

        shared.json_schema_to_pydantic_type = patched_json_schema_to_pydantic_type

        # Patch 2: Langchain swallowing Tool Validation Errors
        # If we just override _handle_validation_error, that gets called from inside BaseTool._run
        def patched_handle_validation_error(
            e: t.Union[ValidationError, Exception],
            *,
            flag: t.Union[bool, str, t.Callable[[t.Any], str]],
        ) -> str:
            if isinstance(flag, bool):
                # Return real exception message
                return f"Tool input validation error: {str(e)}"
            elif isinstance(flag, str):
                return flag
            elif callable(flag):
                return flag(e)
            else:
                return f"Tool input validation error: {str(e)}"

        lc_base._handle_validation_error = patched_handle_validation_error

        # Print success
        print(
            "[PATCH] Applied composio_langchain_patch for arrays and tool validation errors"
        )
    except Exception as e:
        print(f"[PATCH] Failed to apply composio langchain patch: {e}")


# Call it directly on importing
apply()
