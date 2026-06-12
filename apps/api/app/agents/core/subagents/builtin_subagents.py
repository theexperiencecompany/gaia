"""Built-in subagents that are not OAuth integrations.

These provide subagent capabilities without requiring user OAuth. They are
intentionally NOT in `OAUTH_INTEGRATIONS` so they don't leak into the
marketplace, public integrations API, ChromaDB integration indexing, the
Composio toolkit map, OAuth status checks, trigger search, or workflow
generation.

Lookups go through `agents/core/subagents/registry.py`, which combines
these with OAuth-derived subagents into a single canonical view.

If this list grows past ~3 entries, consider whether `Subagent` should
acquire its own category/icon system instead of borrowing OAuth's.

The `provider` field assumes no future OAuth integration claims the same
provider string. Pick a unique value for each builtin.
"""

from typing import Final

from app.agents.prompts.subagent_prompts import (
    DOCGEN_AGENT_SYSTEM_PROMPT,
    GAIA_AGENT_SYSTEM_PROMPT,
)
from app.models.mcp_config import SubAgentConfig
from app.models.subagent_models import Subagent

BUILTIN_SUBAGENTS: Final[tuple[Subagent, ...]] = (
    Subagent(
        id="docgen",
        name="Document Generator",
        provider="docgen",
        managed_by="internal",
        config=SubAgentConfig(
            has_subagent=True,
            agent_name="docgen_agent",
            tool_space="docgen",
            handoff_tool_name="call_docgen",
            domain="creating downloadable documents — PDF, Word (docx), PowerPoint (pptx), Excel (xlsx), and CSV — from a request and its source data",
            capabilities=(
                "writing document source in the sandbox and compiling it with "
                "the right toolchain (Typst/tectonic for PDF, docx-js, pptxgenjs, "
                "openpyxl), driven by the create-pdf / create-docx / create-pptx / "
                "create-spreadsheet skills, then delivering the finished file"
            ),
            use_cases=(
                "any request to produce or export a document file — 'make a PDF "
                "report', 'export this as a Word doc', 'build a slide deck', "
                "'create a spreadsheet', 'generate an invoice'. Use this whenever "
                "the deliverable is a downloadable file rather than a chat answer. "
                "Do NOT use it for editing third-party docs in connected apps "
                "(Google Docs/Sheets) — those belong to their integration subagents."
            ),
            system_prompt=DOCGEN_AGENT_SYSTEM_PROMPT,
            use_direct_tools=True,
            disable_retrieve_tools=True,
            include_finish_task=True,
        ),
    ),
    Subagent(
        id="gaia_knowledge_guide",
        name="GAIA Knowledge Guide",
        provider="gaia_knowledge_guide",
        managed_by="internal",
        config=SubAgentConfig(
            has_subagent=True,
            agent_name="gaia_knowledge_guide_agent",
            tool_space="gaia_knowledge_guide",
            handoff_tool_name="call_gaia_knowledge_guide",
            domain="any question about GAIA itself — the product, company, agent system, integrations, pricing, architecture, philosophy, or anything else",
            capabilities=(
                "exploring GAIA's own documentation to answer any question "
                "about GAIA, grounding every claim in fetched content rather "
                "than training-data knowledge"
            ),
            use_cases=(
                "any meta question about GAIA the product — what it is, "
                "what it does, what it supports, how it works, why it was "
                "built, who built it, what it costs, how it compares to "
                "alternatives, what it does NOT do, troubleshooting, "
                "onboarding, account questions. Use this whenever the user "
                "asks ABOUT GAIA. Do NOT use this for action requests "
                "(send email, schedule, build a workflow) — those belong "
                "to other subagents."
            ),
            system_prompt=GAIA_AGENT_SYSTEM_PROMPT,
            use_direct_tools=True,
            disable_retrieve_tools=True,
            auto_bind_tools=["fetch_webpages"],
            include_finish_task=False,
        ),
    ),
)
