"""
Monkey patch for Composio's json_schema_to_pydantic_type to handle $ref references.

Composio's json_schema_to_model/json_schema_to_pydantic_type doesn't resolve JSON Schema
$ref references (e.g. {"$ref": "#/$defs/ShareRecipient"}). When Pydantic generates schemas
for nested BaseModel classes, it uses $defs and $ref, causing Composio to fall back to
`type = "string"` for nested models.

This patch wraps the original functions to:
1. Store the root schema containing $defs
2. Resolve $ref references before processing

Usage:
    from app.patches import composio_schema_patch
    composio_schema_patch.apply()  # Call once during app initialization
"""

import typing as t
from functools import reduce

from composio.utils import shared as composio_shared
from pydantic import BaseModel, Field, create_model
from pydantic.fields import FieldInfo

# Thread-local storage for the root schema (contains $defs)
_root_schema_stack: t.List[t.Dict[str, t.Any]] = []


def _resolve_ref(ref: str, root_schema: t.Dict[str, t.Any]) -> t.Dict[str, t.Any]:
    """
    Resolve a JSON Schema $ref reference.

    Args:
        ref: Reference string like "#/$defs/ShareRecipient"
        root_schema: The root schema containing $defs

    Returns:
        The resolved schema definition
    """
    if not ref.startswith("#/"):
        raise ValueError(f"Only local $ref references are supported, got: {ref}")

    # Parse the reference path: "#/$defs/ShareRecipient" -> ["$defs", "ShareRecipient"]
    parts = ref[2:].split("/")

    result = root_schema
    for part in parts:
        if part not in result:
            raise ValueError(f"Could not resolve $ref '{ref}': key '{part}' not found")
        result = result[part]

    return result


def _patched_json_schema_to_pydantic_type(
    json_schema: t.Dict[str, t.Any],
) -> t.Union[t.Type, t.Optional[t.Any]]:
    """
    Patched version that resolves $ref references before processing.
    """
    # Resolve $ref if present
    if "$ref" in json_schema and _root_schema_stack:
        ref = json_schema["$ref"]
        root_schema = _root_schema_stack[-1]
        try:
            resolved = _resolve_ref(ref, root_schema)
            # Merge resolved schema with any additional properties (like description)
            merged = {**resolved}
            for key, value in json_schema.items():
                if key != "$ref":
                    merged[key] = value
            json_schema = merged
        except ValueError:
            pass  # Fall through to original behavior if resolution fails

    # Handle oneOf schemas first
    if "oneOf" in json_schema:
        one_of_options = json_schema["oneOf"]
        pydantic_types = [
            _patched_json_schema_to_pydantic_type(option) for option in one_of_options
        ]
        valid_types = [ptype for ptype in pydantic_types if ptype is not None]
        if len(valid_types) == 1:
            return valid_types[0]
        if len(valid_types) == 0:
            return str
        cast_types = [t.cast(t.Type, ptype) for ptype in valid_types]
        return reduce(lambda a, b: t.Union[a, b], cast_types)  # type: ignore

    # Add fallback type - string (only if no $ref and no type)
    if "type" not in json_schema:
        json_schema["type"] = "string"

    type_ = t.cast(str, json_schema.get("type"))

    if type_ == "array":
        items_schema = json_schema.get("items")
        if items_schema:
            ItemType = _patched_json_schema_to_pydantic_type(items_schema)
            return t.List[t.cast(t.Type, ItemType)]  # type: ignore
        return t.List

    if type_ == "object":
        properties = json_schema.get("properties")
        if properties:
            nested_model = _patched_json_schema_to_model(json_schema)
            return nested_model
        return t.Dict

    pytype = composio_shared.PYDANTIC_TYPE_TO_PYTHON_TYPE.get(type_)
    if pytype is not None:
        return pytype

    raise ValueError(f"Unsupported JSON schema type: {type_}")


def _patched_json_schema_to_pydantic_field(
    name: str,
    json_schema: t.Dict[str, t.Any],
    required: t.List[str],
    skip_default: bool = False,
) -> t.Tuple[str, t.Type, FieldInfo]:
    """
    Patched version that resolves $ref before processing fields.
    """
    # Resolve $ref if present
    if "$ref" in json_schema and _root_schema_stack:
        ref = json_schema["$ref"]
        root_schema = _root_schema_stack[-1]
        try:
            resolved = _resolve_ref(ref, root_schema)
            merged = {**resolved}
            for key, value in json_schema.items():
                if key != "$ref":
                    merged[key] = value
            json_schema = merged
        except ValueError:
            pass

    description = json_schema.get("description")
    if "oneOf" in json_schema:
        description = " | ".join(
            [option.get("description", "") for option in json_schema["oneOf"]]
        )
        description = f"Any of the following options(separated by |): {description}"

    examples = json_schema.get("examples", [])
    default = json_schema.get("default")

    if name in composio_shared.reserved_names:
        name = f"{name}_"
        alias = name
    else:
        alias = None

    field = {
        "description": description,
        "examples": examples,
        "alias": alias,
    }
    if not skip_default:
        field["default"] = ... if name in required else default

    return (
        name,
        t.cast(
            t.Type,
            _patched_json_schema_to_pydantic_type(json_schema=json_schema),
        ),
        Field(**field),  # type: ignore
    )


def _patched_json_schema_to_model(
    json_schema: t.Dict[str, t.Any],
    skip_default: bool = False,
) -> t.Type[BaseModel]:
    """
    Patched version that stores root schema for $ref resolution.
    """
    # Push this schema onto the stack if it contains $defs
    is_root = "$defs" in json_schema
    if is_root:
        _root_schema_stack.append(json_schema)

    try:
        model_name = json_schema.get("title", f"Model_{id(json_schema)}")
        field_definitions = {}
        for name, prop in json_schema.get("properties", {}).items():
            updated_name, pydantic_type, pydantic_field = (
                _patched_json_schema_to_pydantic_field(
                    name,
                    prop,
                    json_schema.get("required", []),
                    skip_default=skip_default,
                )
            )
            field_definitions[updated_name] = (pydantic_type, pydantic_field)
        return create_model(model_name, **field_definitions)  # type: ignore
    finally:
        if is_root:
            _root_schema_stack.pop()


_original_json_schema_to_pydantic_type = None
_original_json_schema_to_pydantic_field = None
_original_json_schema_to_model = None
_applied = False


def apply():
    """Apply the monkey patch to Composio's shared module and all modules that import it."""
    global _original_json_schema_to_pydantic_type
    global _original_json_schema_to_pydantic_field
    global _original_json_schema_to_model
    global _applied

    if _applied:
        return

    # Store originals
    _original_json_schema_to_pydantic_type = (
        composio_shared.json_schema_to_pydantic_type
    )
    _original_json_schema_to_pydantic_field = (
        composio_shared.json_schema_to_pydantic_field
    )
    _original_json_schema_to_model = composio_shared.json_schema_to_model

    # Apply patches to composio.utils.shared
    composio_shared.json_schema_to_pydantic_type = _patched_json_schema_to_pydantic_type
    composio_shared.json_schema_to_pydantic_field = (
        _patched_json_schema_to_pydantic_field
    )
    composio_shared.json_schema_to_model = _patched_json_schema_to_model

    # Also patch any modules that may have already imported these by value
    # This includes composio_langchain.provider and our own langchain_composio_service
    try:
        from composio_langchain import provider as composio_langchain_provider

        composio_langchain_provider.json_schema_to_model = _patched_json_schema_to_model
    except (ImportError, AttributeError):
        pass  # May not be loaded yet, which is fine

    try:
        from app.services.composio import langchain_composio_service

        langchain_composio_service.json_schema_to_model = _patched_json_schema_to_model
    except (ImportError, AttributeError):
        pass  # May not be loaded yet, which is fine

    _applied = True


def revert():
    """Revert the monkey patch."""
    global _applied

    if not _applied:
        return

    composio_shared.json_schema_to_pydantic_type = (
        _original_json_schema_to_pydantic_type
    )
    composio_shared.json_schema_to_pydantic_field = (
        _original_json_schema_to_pydantic_field
    )
    composio_shared.json_schema_to_model = _original_json_schema_to_model

    _applied = False
