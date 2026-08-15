"""Docstrings for flowchart-related tools."""

CREATE_FLOWCHART = """
Creates a Mermaid.js flowchart based on a natural language description.

Use this tool when a user requests visualization of processes, workflows, decision trees,
or any sequential steps that would benefit from a diagram. The tool converts natural language
descriptions into properly formatted Mermaid.js flowchart code.

When to use:
- User asks to visualize a process or workflow
- User wants a diagram of steps or decision points
- Complex relationships need visual representation
- User mentions flowcharts, diagrams, or visual aids
- Sequential procedures would benefit from visual clarity

Input requirements:
- description: Provide a detailed description of what should be in the flowchart, including:
  * Main steps or components
  * Decision points and their outcomes
  * Relationships between elements
  * Start and end points
  * Any conditional paths or loops

- direction: Specify the orientation of the flowchart:
  * "TD" (Top-Down): Default, best for hierarchical processes
  * "LR" (Left-Right): Good for sequential or timeline-based flows
  * "BT" (Bottom-Top): Alternative vertical orientation
  * "RL" (Right-Left): Alternative horizontal orientation

The output is valid Mermaid syntax that can be embedded directly in markdown responses.
After generating the flowchart, explain briefly to the user what the diagram shows.

Examples of good descriptions:
- "A customer support process that starts with receiving a ticket, triaging its priority,
   and then following different paths based on severity until resolution"
- "An e-commerce checkout flow showing cart review, shipping options, payment method selection,
   order confirmation, and different paths for payment success or failure"
"""
