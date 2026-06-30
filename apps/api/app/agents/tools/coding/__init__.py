"""Persistent coding tools: bash, read, write, edit, jq, grep.

`bash` runs inside the user's persistent E2B sandbox (`/workspace` backed by
Cloudflare R2 via JuiceFS). `read`/`write`/`edit`/`jq`/`grep` go straight to the
host JuiceFS mount (no sandbox spin-up); `jq`/`grep` are read-only file-mining
filters for offloaded JSON/JSONL/text. State survives across conversations.
"""

from app.agents.tools.coding.bash_tool import bash
from app.agents.tools.coding.edit_tool import edit
from app.agents.tools.coding.grep_tool import grep
from app.agents.tools.coding.jq_tool import jq
from app.agents.tools.coding.read_tool import read
from app.agents.tools.coding.write_tool import write

tools = [bash, read, write, edit, jq, grep]

__all__ = ["bash", "edit", "grep", "jq", "read", "tools", "write"]
