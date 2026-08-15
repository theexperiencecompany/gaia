# Agent Prompts

This folder holds the system prompts for GAIA's agents (comms, executor, subagents,
onboarding, workflows, todo, openui). These two rules apply to **every** prompt authored or
edited here, and to anything you instruct a model to write.

## 1. Never write em dashes

- Do not use em dashes (`—`) or en dashes (`–`) in prompt prose, in examples, or in any
  output you tell a model to produce. Use commas, periods, colons, parentheses, or semicolons.
- Em dashes are the single clearest tell that text was machine-generated. They are off-limits
  regardless of how natural they feel.
- The one exception is a **section heading** that uses `—Heading—` purely as a visual marker,
  and literal examples of external data the model must reproduce verbatim (e.g. an article
  title that genuinely contains `" — Site Name"`). Never introduce one into running prose.

## 2. Always instruct the model to write like a human (without overdoing it)

Whenever a prompt asks a model to produce user-facing content (chat replies, emails, blog
posts, docs, social posts, summaries), it must also tell the model to write like a real
person, not an LLM. Fold in the patterns that matter, smartly, not as a giant checklist:

- Vary sentence length. Uniform, evenly-paced rhythm is the biggest AI tell.
- Open on the actual point. Cut throat-clearing ("In today's fast-paced world", "It's
  important to note that").
- Take a position instead of over-hedging and over-balancing everything.
- Plain words over inflated ones ("use" not "utilize", "help" not "facilitate").
- Avoid the giveaway vocabulary: "delve", "robust", "seamless", "leverage", "tapestry",
  "testament to", "navigate the landscape", reflexive "Moreover / Furthermore" openers.
- Concrete specifics over vague abstraction.

**The caveat is part of the instruction:** tell the model not to overcorrect into forced
quirkiness, fake slang, or gimmicks. The goal is natural, clear, and human, not performative.
Write the guidance smartly and proportionate to the prompt; do not bloat every prompt with the
full list when a tight version conveys the same intent.
