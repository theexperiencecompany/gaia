"""User prompts for goals and roadmap functionality."""

# JSON structure reference for roadmap generation
ROADMAP_JSON_STRUCTURE = {
    "title": "Title of the goal",
    "description": "A short description",
    "nodes": [
        {
            "id": "node1",
            "data": {
                "label": "Child 1",
                "details": ["detail1", "detail2"],
                "estimatedTime": "...",
                "resources": ["resource1", "resource2"],
            },
        },
        {
            "id": "node2",
            "data": {
                "label": "Child 2",
                "details": ["detail1", "detail2"],
                "estimatedTime": "...",
                "resources": ["resource1", "resource2"],
            },
        },
    ],
    "edges": [
        {
            "id": "e1-2",
            "source": "node1",
            "target": "node2",
        }
    ],
}

# Text instructions for roadmap generation
ROADMAP_INSTRUCTIONS = """
    The roadmap must include **10-15 nodes** representing key milestones.

    ### Node Structure:
    1. **Label**: A concise title summarizing the milestone.
    2. **Details**: A list of 3-5 actionable, specific tasks required to complete the milestone. Keep the length short and concise.
    4. **Estimated Time**: A time estimate for completing the milestone (e.g., "2 weeks", "1 month").
    5. **Resources**: A list of at least 2-4 high-quality resources (books, courses, tools, or tutorials) to assist with the milestone.


    ### Requirements:
    1. The roadmap must cover a progression from beginner to expert levels, with logically ordered steps.
    2. The Roadmap should be in a vertical tree like structure.
    3. Only add resources or details where applicable and necessary.
    4. Make sure that the estimated time makes sense for the node. Estimated times should be realistic.
    5. Include dependencies between nodes in the form of edges.
    6. Ensure the JSON is valid and follows this structure:
    """

# Prompt template for roadmap generation
ROADMAP_GENERATOR = """
    You are an expert roadmap planner. Your task is to generate a highly detailed roadmap in the form of a JSON object.

    The roadmap is for the following title: **{title}**.

    {instructions}

    {{ {json_structure} }}

    Respond **only** with the JSON object, with no extra text or explanations.
    """
