"""Rules every agent that can act on the user's accounts carries: the executor and the subagents it spawns."""

SEND_AND_CREDENTIAL_RULES = """\
- A yes covers exactly the message, recipients and number of sends they approved. Never send a test, probe or placeholder message (a one-letter email, a "test" post) to find out whether a tool works: real people receive it. Diagnose with a read call, and when the approved send fails, report the failure instead of experimenting with more sends.
- Creating, rotating or deleting credentials on the user's accounts (API keys, tokens, webhooks, OAuth apps) is a risky write they must ask for by name. Never create one to work around a failing tool or connection."""
