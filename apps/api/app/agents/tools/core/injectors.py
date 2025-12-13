# def inject_web_search_tool_call(state: State):
#     tool_call = {
#         "name": "web_search_tool",  # Name of tool to call
#         "args": {"query_text": state.get("query", "")},  # Inject query from the state
#         "id": "forced_web_search_call",
#         "type": "tool_call",
#     }
#     ai_message = AIMessage(content="", tool_calls=[tool_call])
#     messages = state.get("messages", [])
#     messages.append(ai_message)
#     return {"messages": messages}


# def inject_deep_research_tool_call(state: State):
#     tool_call = {
#         "name": "deep_research_tool",  # Name of tool to call
#         "args": {"query_text": state.get("query", "")},  # Inject query from the state
#         "id": "forced_deep_research_call",
#         "type": "tool_call",
#     }
#     ai_message = AIMessage(content="", tool_calls=[tool_call])
#     messages = state.get("messages", [])
#     messages.append(ai_message)
#     return {"messages": messages}


# def should_call_tool(state: State):
#     """
#     Decides what to do next based on the flags in the state.

#     - If 'force_web_search' is True, go to the node that injects a web search tool call.
#     - If 'force_deep_research' is True, go to the node that injects a deep research tool call.
#     - If neither flag is set, just continue with the chatbot as usual.

#     This helps control whether we force specific tools before letting the chatbot respond.

#     """
#     if state.get("force_web_search", False):
#         return "call_1"
#     elif state.get("force_deep_research", False):
#         return "call_2"
#     else:
#         return "call_chatbot"
