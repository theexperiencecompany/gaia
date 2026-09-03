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
2. Which args are fixed on every run, and what does each of the others become? The placeholder vocabulary is: $now, $today, $now + 1d; $user.email, $user.name, $user.timezone; $trigger.<path>; $steps.<step_id>.<path> and $steps.<step_id>.file; $last_run.<TOOL_NAME>.<path>. If a value genuinely cannot be frozen or built from those, write {"$ask": "what to write"} as that value and a model writes it at replay, right before that step runs. This is rare: a search query usually freezes fine, and anything about the RESULT belongs in result_brief, not in a step.
3. What has to carry over to the next run (a cursor, a last seen id, a timestamp) so it does not redo work or repeat something someone would notice?
4. Would this exact ORDER OF CALLS work tomorrow, unchanged? Judge the sequence, not the content: results and the words you write from them are SUPPOSED to differ every run, and that is what result_brief and $ask exist for, so changing data is never by itself a reason to answer no. Answer no only if the sequence itself would differ: the order depended on what you found, you reacted to a result by choosing different calls mid-run, or a step only made sense given today's data.
5. Did every call you are freezing return the data the workflow needs, as it stands? If a step came back empty, with an error, or partial, and you compensated by reasoning around it, that call is not the work. A playbook replays the call, not your reasoning, so the next run would hand the user the gap you papered over. Fix its args before freezing, or decline.

If 4 and 5 are both yes, call write_playbook. Its arguments carry the shape: a description, the steps in the order you ran them, and a result_brief saying how to write the user's result from the steps' results (this is where classification, judgement and summarising go). A step is EITHER a tool call OR a handoff carrying the steps that subagent ran. Each handoff's result includes a record of the calls that subagent actually ran: the handoff step's nested steps are the calls in that record that did the work, with those exact names and args, minus the subagent's own discovery. Use the real tool names and argument names you actually called, since they are checked against the live tools and a playbook naming a tool that does not exist is refused. The shape, end to end:

steps:
  - id: unread
    handoff: gmail
    steps:
      - id: inbox
        tool: GMAIL_FETCH_MESSAGES
        args: {query: "is:unread newer_than:1d", max_results: 25}
  - id: background
    tool: web_search_tool
    args:
      query_text: {"$ask": "one web search that would give background on the most important mail listed above"}
result_brief: Lead with what the unread mail is about, then what the search added. Two short paragraphs.

If either 4 or 5 is no, call decline_playbook with the reason. You MUST end this run by calling exactly one of write_playbook or decline_playbook: staying silent is not a decision, and a run that was asked and called neither is a lapse, not a no.

Either way, keep all of this out of what you return. The result you hand back is the workflow's own output, the thing the user asked for, and nothing else. Do not narrate the check, do not list your answers, do not mention playbooks or freezing or this decision at all. Whether you called the tool is the entire record of it.
</playbook_check>"""


PLAYBOOK_HEAL_BRIEF = """<playbook_check>
This workflow has a stored playbook. On the last run it was replayed and {verdict}, for this reason:
{reason}
{already_ran}
Do not lean on the playbook this run. Call read_playbook first so you can see the frozen sequence, then do the work properly yourself, checking each step against that reason as you go. If a step comes back empty, with an error, or partial, the frozen call or its args are what is wrong, and the fix is the call that actually produces the result, with the arguments that make it produce one.

If the recorded reason is that a call returned nothing, do not accept that emptiness on the replay's terms. Before you call write_playbook with the same sequence, establish that the source genuinely has nothing by probing more broadly than the frozen call: a longer window, the filter dropped, a check that the integration actually answers at all. Put what you checked in the reason you give write_playbook or disable_playbook, never in the result. Only a broader probe that also comes back empty justifies rewriting the same sequence. If the broader probe finds items the frozen call missed, the args are wrong, and the rewrite must use the args that found them.

The decision is about the playbook only. Do not pause, deactivate, edit or delete the workflow itself, and do not change its schedule: a source that has nothing today is not a reason to stop a workflow the user set up, and that call is theirs to make.

When the work is finished (and only then), end this run by calling exactly one of write_playbook or disable_playbook. That holds even if you make no further calls because the steps that already ran answer the task: the decision is part of the work, not something that happens only after tool calls. Call write_playbook with the corrected sequence, or with the same sequence if it turns out to have been right after all and the recorded reason was a one-off. Call disable_playbook with the reason if the sequence cannot hold, because the order of calls depends on what each run finds. Staying silent is not a decision, and a run that was asked and called neither is a lapse, not a no.

Keep all of this out of what you return. The result you hand back is the workflow's own output, the thing the user asked for, and nothing else. Do not narrate the check, do not mention playbooks or this decision at all. Whether you called the tool is the entire record of it.
</playbook_check>"""

#: Merged into the heal brief when the replay that stopped was THIS fire's: the
#: heal brief on its own says "do the work properly yourself", and without this
#: block that reads as "repeat the steps that already ran".
PLAYBOOK_HEAL_ALREADY_RAN = """
That replay was in this same execution, not a previous one. Its record follows. The steps it lists as already run happened, so finish from where it stopped and do not repeat them:
{fallback_note}"""

#: What the heal brief says happened, keyed by the recorded run status value.
PLAYBOOK_HEAL_VERDICTS = {
    "failed": "stopped partway",
    "suspect": "finished, but its result was not trusted",
}
PLAYBOOK_HEAL_NO_REASON = "no reason was recorded"


#: The style guidance both replay prompts end on. One constant so the two calls
#: cannot drift apart on voice.
_PLAYBOOK_VOICE = """Write like a person. Open on the actual point, vary your sentence length, use plain words, and say what you think instead of hedging every clause. No throat-clearing openers, no "delve", "seamless", "robust", "leverage", "testament to", no reflexive "Moreover". Do not overcorrect into forced quirkiness or slang either. Natural and clear is the whole target."""

#: The mid-run call: fills the ``$ask`` slots the next step needs, and nothing
#: else. One call per step that carries slots, made immediately before that
#: step, so the slots are written from everything that has actually run. It runs
#: before the later steps, so it must not write the user's result or judge the
#: run: neither can be done before the run's outcome is known.
PLAYBOOK_ASK_PROMPT = (
    """You are writing the slots the next step of a workflow run needs before it can continue. The run follows a written playbook, so its steps are replayed rather than reasoned out. The steps listed as ran already happened exactly as listed. The steps still to run happen after you answer, and the first of them uses what you write.

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

Write one entry per slot above, keyed by the slot's key exactly as listed. Follow each slot's instruction and respect its length budget. Write nothing else: no result for the user and no judgement of the run. Both are written after the remaining steps have run, by a separate call that sees their results.

Ground every word in what is listed above. Never invent a number, a name, a link, or an outcome that is not there.

"""
    + _PLAYBOOK_VOICE
)

#: The end-of-run call: the user's result and a verdict, written once every
#: step has run. There is no still-to-run section because there is nothing
#: still to run; what is listed is the whole run.
PLAYBOOK_NARRATION_PROMPT = (
    """You are finishing a workflow run that followed a written playbook, so the steps were replayed rather than reasoned out. Every step below already ran, exactly as listed, and nothing else ran. The run is over.

<playbook>
{description}
</playbook>

<ran>
{completed}
</ran>

<asks>
{asks}
</asks>

The asks section holds the slots written earlier in this run, for context only. The steps that needed them already used them.

Produce both of these in this one pass:

1. The run's result for the user, written to this brief (result_brief): {result_brief}
   The result is the finished text the user reads, written once. Never a draft followed by a rewrite, never a note to yourself about the brief, never an aside about what you are doing: if you would change something, change it before you write, and hand back only the final version.
2. A verdict on the run. Judge only the steps listed under ran. Each line shows the arguments the call ran with and what it returned; judge both against the playbook's description and the brief above. Answer suspect when a result is empty where the task expects items, contains an error, or contradicts the description, and also when the arguments contradict it: a wider window than the task names, a filter it does not ask for, a source it does not mention. Plenty of results do not make a wrong call right. Otherwise answer ok. Never answer suspect because some step is missing from the list. The list is complete, and a step that is not on it was not part of this run. When it is suspect, give a one line reason. Write the result either way, exactly as the data reads.

Ground every word in what is listed above. Never invent a number, a name, a link, or an outcome that is not there, and if something did not happen, say that plainly instead of smoothing over it.

"""
    + _PLAYBOOK_VOICE
)


#: Delivered as the run's result when every step replayed but the narration
#: call did not return. The steps' effects are real and their results are on
#: the record, so the user gets what ran rather than a failed run, and the
#: playbook is not sent to heal over a call that was never its fault.
PLAYBOOK_NARRATION_FALLBACK_TEMPLATE = """The saved steps for this workflow ran, but the summary could not be written this time ({reason}).

What ran:
{completed}"""


PLAYBOOK_FALLBACK_TEMPLATE = """The playbook for this workflow was replayed first and it stopped partway.

{failure}

These steps ALREADY RAN in this same execution, and their effects are real:
{completed}

Do not repeat them. Pick up from where the replay stopped and finish the workflow."""


PLAYBOOK_SUSPECT_FALLBACK_TEMPLATE = """The playbook for this workflow was replayed first. It ran to the end, but its result was not trusted, for this reason:
{reason}

These steps ALREADY RAN in this same execution, with these results, and their effects are real:
{completed}

Do not repeat them. Do the work properly yourself, checking each step against that reason, and end this run by rewriting the playbook or disabling it, even if you make no further calls because these results already answer the task. Leave the workflow itself alone: do not pause, deactivate or edit it."""
