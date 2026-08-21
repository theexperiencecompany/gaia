"""Browser automation capability: gaia-browser-host + Browser-Use agent.

Layered so each concern is swappable and independently testable:

  * ``session``    — browser-host session lifecycle (create / live-view / release)
  * ``llm``        — the strong, vision-capable model that drives the agent
  * ``classify``   — LLM gate deciding which steps need human approval
  * ``handoff``    — Redis bridge a paused run blocks on
  * ``runner``     — Browser-Use execution, emitting progress + honouring the gate
  * ``bot_delivery`` — mirrors progress + screenshots to messaging bots

The agent tool (``app/agents/tools/browser_tool.py``) is the only place these
are wired together; the executor sees a single tool, not the host or Browser-Use.
"""
