# Integration Tests — Agents

Tests that compile and execute real production LangGraph graphs. The actual `build_comms_graph` and `create_agent` factories are imported and run; only external I/O is replaced (LLM calls use a `FakeMessagesListChatModel`, memory persistence uses mocked service clients, the executor tool is stubbed out).

Key things verified here that unit tests cannot catch:

- Node wiring: required nodes (`agent`, `tools`, `end_graph_hooks`) are present in the compiled graph.
- Routing behaviour: `should_continue` correctly routes plain-text responses to end-graph hooks and tool-call responses to `DynamicToolNode`.
- Tool registration: tools like `add_memory` and `search_memory` are wired into the registry, proven by ToolMessages appearing in output state.
- Multi-turn state: `InMemorySaver` checkpointing accumulates messages correctly across consecutive `ainvoke` calls on the same thread.
- Thread isolation: separate thread IDs do not share checkpointed state.

The `helpers.py` module in `tests/` provides `BindableToolsFakeModel` and factory helpers for building fake LLMs with pre-programmed responses or tool calls.
