"""Shared helper for asserting ``$regex`` escaping in MongoDB aggregation pipelines."""


def collect_regex_values(node: object) -> list[str]:
    """Recursively pull every ``$regex`` value out of an aggregation pipeline."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$regex":
                found.append(value)
            else:
                found.extend(collect_regex_values(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(collect_regex_values(item))
    return found
