"""Browser automation capability: self-hosted Steel infra + Browser-Use agent.

Layered so each concern is swappable and independently testable:

  * ``session``    — Steel session lifecycle (create / connect-url / release)
  * ``llm``        — the strong, vision-capable model that drives the agent
  * ``classify``   — LLM gate deciding which steps need human approval
  * ``approvals``  — Redis bridge a paused run blocks on
  * ``runner``     — Browser-Use execution, emitting progress + honouring the gate
  * ``bot_delivery`` — mirrors progress + screenshots to messaging bots

The agent tool (``app/agents/tools/browser_tool.py``) is the only place these
are wired together; the executor sees a single tool, not Steel or Browser-Use.
"""
