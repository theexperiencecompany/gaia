"""Persistent coding tools: bash, read, write, edit, query_json, grep.

`bash` runs inside the user's persistent E2B sandbox (`/workspace` backed by
Cloudflare R2 via JuiceFS). `read`/`write`/`edit`/`query_json`/`grep` go straight
to the host JuiceFS mount (no sandbox spin-up). `query_json` is an in-process
structured query over offloaded JSON/JSONL records; `grep` is read-only free-text
search. State survives across conversations.
"""

from app.agents.tools.coding.bash_tool import bash
from app.agents.tools.coding.edit_tool import edit
from app.agents.tools.coding.grep_tool import grep
from app.agents.tools.coding.query_json_tool import query_json
from app.agents.tools.coding.read_tool import read
from app.agents.tools.coding.write_tool import write

tools = [bash, read, write, edit, query_json, grep]

__all__ = ["bash", "edit", "grep", "query_json", "read", "tools", "write"]
