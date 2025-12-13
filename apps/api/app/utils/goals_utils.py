from datetime import datetime

STATIC_USER_ID = "user123"


def goal_helper(goal, has_roadmap=True) -> dict:
    created_at = goal["created_at"]
    if isinstance(created_at, datetime):
        created_at = created_at.isoformat()

    nodes = goal.get("roadmap", {}).get("nodes", [])
    completed_nodes = len(
        [node for node in nodes if node.get("data", {}).get("isComplete", False)]
    )
    total_nodes = len(nodes)
    progress = int((completed_nodes / total_nodes) * 100) if total_nodes > 0 else 0

    goal_data = {
        "id": str(goal["_id"]),
        "title": goal["title"],
        "description": goal.get("description", ""),
        "created_at": created_at,
        "progress": progress,
        "user_id": goal.get("user_id", STATIC_USER_ID),
        "todo_project_id": goal.get("todo_project_id"),
        "todo_id": goal.get("todo_id"),
    }

    if has_roadmap:
        goal_data["roadmap"] = {
            "title": goal.get("roadmap", {}).get("title", ""),
            "description": goal.get("roadmap", {}).get("description", ""),
            "nodes": goal.get("roadmap", {}).get("nodes", []),
            "edges": goal.get("roadmap", {}).get("edges", []),
        }
    else:
        goal_data["roadmap"] = {}

    return goal_data
