"""Constants for the execute proxy — the single tool that runs integration tools.

EXECUTE_TOOL_NAME is read by the tool itself, the HIL unwrap, the streaming
formatter and the analytics dedupe — one constant so the five sites cannot
drift (root CLAUDE.md, Type Safety item 18).
"""

EXECUTE_TOOL_NAME = "execute"
RUN_CODE_TOOL_NAME = "run_code"

# A rendered schema doc becomes conversation context the model re-pays for on
# every later turn, and Composio response schemas alone can run to thousands of
# tokens — cap the doc, never inject a huge schema wholesale.
SCHEMA_DOC_MAX_CHARS = 6000

# Keys under which a tool's metadata may carry a provider-supplied response
# schema. Rendered only when present — most tools do not document their output
# shape, and the doc must not pretend otherwise.
RESPONSE_SCHEMA_METADATA_KEYS = ("output_parameters", "response_schema", "outputSchema")
