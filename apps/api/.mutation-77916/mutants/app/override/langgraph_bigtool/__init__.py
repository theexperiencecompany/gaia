"""
LangGraph BigTool Override Package.

This package overrides `create_agent` from langgraph_bigtool to support:
- Dynamic model configuration at runtime
- LangChain AgentMiddleware integration (before_model, after_model, wrap_model_call, wrap_tool_call)
- Dynamic tool registration after graph compilation

Usage:
    from app.override.langgraph_bigtool.create_agent import create_agent
"""

# Submodules are imported directly by consumers to avoid circular imports.
# e.g.: from app.override.langgraph_bigtool.create_agent import create_agent
