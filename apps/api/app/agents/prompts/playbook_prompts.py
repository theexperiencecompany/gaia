"""Prompts for playbook authoring.

The check below rides in the executor's opening brief, not in the narration of
the finished result. Two reasons, both load-bearing:

* Only the executor can act on it. ``write_playbook`` lives in the executor's
  tool registry; comms binds exactly ``call_executor`` / ``cancel_executor`` /
  the memory tools and is built with ``disable_retrieve_tools=True``
  (``build_graph.py``), so a check delivered at narration time asks for a tool
  the narrator cannot reach, and risks being re-voiced into the user's message.
* The executor already has its own calls in context when it finishes, so the
  judgement is made against what actually happened without rendering a trace
  back to it. A trace read at narration time would be the PREVIOUS run's
  anyway: this run's is only persisted after the run returns.
"""

PLAYBOOK_CHECK_BRIEF = """<playbook_check>
This workflow has no working playbook. When you have finished the work above (and only then), decide whether the sequence you just ran is worth freezing so future runs can replay it instead of reasoning it out again.

Work through these five for yourself, against the calls you actually made. This is your own reasoning, not part of the run's result:
1. Which of your calls were discovery or dead ends (finding an id, a channel, a folder, a file, recovering from an error, or an attempt that came back empty, wrong or refused that you then did differently) rather than the work itself? Those must not go in a playbook. A playbook records what WORKED: freeze the call that actually produced the result, with the arguments that made it produce one, not the first thing you tried.
2. Which args are fixed on every run, and what does each of the others become? The placeholder vocabulary is: $now, $today, $now + 1d; $user.email, $user.name, $user.timezone; $trigger.<path>; $steps.<step_id>.<path> and $steps.<step_id>.file; $last_run.<TOOL_NAME>.<path>; $ask.<name>.
3. What has to carry over to the next run (a cursor, a last seen id, a timestamp) so it does not redo work or repeat something someone would notice?
4. What did you have to write or judge from content, rather than copy straight out of a result? Each of those becomes an $ask.
5. Would this exact ORDER OF CALLS work tomorrow, unchanged? Judge the sequence, not the content: results and the words you write from them are SUPPOSED to differ every run, and that is what synthesize and $ask exist for, so changing data is never by itself a reason to answer no. Answer no only if the sequence itself would differ: the order depended on what you found, you reacted to a result by choosing different calls mid-run, or a step only made sense given today's data.

If 5 is yes, call write_playbook. Its arguments carry the shape: a description, the steps in the order you ran them, a synthesize brief, and an ask entry for each thing you had to write. A step is EITHER a tool call OR a handoff carrying the steps that subagent ran. Use the real tool names and argument names you actually called, since they are checked against the live tools and a playbook naming a tool that does not exist is refused.

If 5 is no, call decline_playbook with the reason. You MUST end this run by calling exactly one of write_playbook or decline_playbook: staying silent is not a decision, and a run that was asked and called neither is a lapse, not a no.

Either way, keep all of this out of what you return. The result you hand back is the workflow's own output, the thing the user asked for, and nothing else. Do not narrate the check, do not list your answers, do not mention playbooks or freezing or this decision at all. Whether you called the tool is the entire record of it.
</playbook_check>"""


PLAYBOOK_NARRATION_PROMPT = """You are finishing a workflow run that followed a written playbook, so the steps were replayed rather than reasoned out. Everything below already happened or is about to happen exactly as listed.

<playbook>
{description}
</playbook>

<ran>
{completed}
</ran>

<still_to_run>
{remaining}
</still_to_run>

<asks>
{asks}
</asks>

Produce both of these in this one pass:

1. One entry per ask above, keyed by the ask's own name. Follow each ask's instruction and respect its length budget. If there are no asks, return an empty list.
2. The run's result for the user, written to this brief: {synthesize}

Ground every word in what is listed above. Never invent a number, a name, a link, or an outcome that is not there, and if something did not happen, say that plainly instead of smoothing over it.

Write like a person. Open on the actual point, vary your sentence length, use plain words, and say what you think instead of hedging every clause. No throat-clearing openers, no "delve", "seamless", "robust", "leverage", "testament to", no reflexive "Moreover". Do not overcorrect into forced quirkiness or slang either. Natural and clear is the whole target."""


PLAYBOOK_FALLBACK_TEMPLATE = """The playbook for this workflow was replayed first and it stopped partway.

{failure}

These steps ALREADY RAN in this same execution, and their effects are real:
{completed}

Do not repeat them. Pick up from where the replay stopped and finish the workflow."""
