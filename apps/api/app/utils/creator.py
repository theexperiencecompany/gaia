"""Shared helpers for hydrating workflow creator information from MongoDB.

Centralizes the `$lookup` pipeline stage that joins workflows.created_by to
users._id, plus the post-aggregation creator-dict shape (with the system →
"GAIA Team" convention). Keep this in sync with the frontend helper at
apps/web/src/features/workflows/utils/creator.ts.
"""

from typing import Any

SYSTEM_CREATOR_ID = "system"
SYSTEM_CREATOR_NAME = "GAIA Team"
UNKNOWN_CREATOR_NAME = "Unknown"


def creator_lookup_stage(
    creator_field: str = "created_by",
    output_field: str = "creator_info",
) -> dict[str, Any]:
    """Return a `$lookup` stage that joins `creator_field` (a user id string)
    against the `users` collection's ObjectId `_id`. Uses `$convert` with
    `onError: None` so non-OID values (like the literal "system") don't crash
    the aggregation — they simply yield no match.
    """
    return {
        "$lookup": {
            "from": "users",
            "let": {"creator_id": f"${creator_field}"},
            "pipeline": [
                {
                    "$match": {
                        "$expr": {
                            "$eq": [
                                "$_id",
                                {
                                    "$convert": {
                                        "input": "$$creator_id",
                                        "to": "objectId",
                                        "onError": None,
                                        "onNull": None,
                                    }
                                },
                            ]
                        }
                    }
                },
                {"$project": {"name": 1, "email": 1, "picture": 1, "_id": 0}},
            ],
            "as": output_field,
        }
    }


def format_creator(
    workflow: dict[str, Any],
    creator_field: str = "created_by",
    info_field: str = "creator_info",
    default_name: str | None = None,
) -> dict[str, Any]:
    """Build the public-facing `creator` dict for a workflow document, given
    the joined `creator_info` array. Falls back to `SYSTEM_CREATOR_NAME` when
    the creator id is "system" (or `default_name` is set), else
    `UNKNOWN_CREATOR_NAME`.
    """
    info_array = workflow.get(info_field) or []
    info = info_array[0] if info_array else {}
    creator_id = workflow.get(creator_field)

    if default_name is not None:
        fallback_name = default_name
    elif creator_id == SYSTEM_CREATOR_ID:
        fallback_name = SYSTEM_CREATOR_NAME
    else:
        fallback_name = UNKNOWN_CREATOR_NAME

    return {
        "id": creator_id,
        "name": info.get("name", fallback_name),
        "avatar": info.get("picture"),
    }
