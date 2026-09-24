"""Browser automation capability: gaia-browser-host plus an agent loop.

The agent tool app/agents/tools/browser_tool.py is the only entry point.
It calls runner.BrowserTaskRunner, which owns progress, handoff, budgets and
metering for one task, then hands the steps to agent_run.BrowserAgentRun:
Browser-Use's Agent on the reasoning model, with Jev (jev/) as its first
action and fast page operator.
"""
