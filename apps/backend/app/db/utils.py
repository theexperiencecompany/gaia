from bson import ObjectId
from typing import Any, Dict


def serialize_document(document: dict) -> dict:
    """
    Serialize a MongoDB document by converting ObjectId fields to strings.

    This function handles:
    1. Converting the primary '_id' field to 'id'
    2. Converting any nested ObjectId values to strings

    Args:
        document (dict): The MongoDB document.

    Returns:
        dict: The serialized document with all ObjectId values converted to strings.
    """

    if not document:
        return document

    result: Dict[str, Any] = {}
    # Convert the primary _id to id and add to result
    if "_id" in document:
        result["id"] = str(document.pop("_id"))

    # Process all remaining fields
    for key, value in document.items():
        # Convert ObjectId to string
        if isinstance(value, ObjectId):
            result[key] = str(value)
        # Process lists
        elif isinstance(value, list):
            result[key] = [
                (
                    str(item)
                    if isinstance(item, ObjectId)
                    else serialize_document(item)
                    if isinstance(item, dict)
                    else item
                )
                for item in value
            ]
        # Process nested dictionaries
        elif isinstance(value, dict):
            result[key] = serialize_document(value)
        # Keep other values as-is
        else:
            result[key] = value

    return result
