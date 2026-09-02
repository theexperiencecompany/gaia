---
name: stripe-link-purchase
description: Buy something on the user's behalf with Stripe Link — create a spend request, get the user's approval, then pay with the one-time credential. Covers test mode and the limits that bite.
target: stripe_link_agent
---

# Stripe Link: Paying For Something

## When to Activate
The user asks you to buy, order, pay for, or subscribe to something, or to pay an
API/endpoint that returns HTTP 402.

## The Shape of a Purchase

A purchase is four steps and the third one is not yours:

```
create  ->  request-approval  ->  [USER APPROVES IN LINK APP]  ->  retrieve + pay
```

You cannot approve for them. If approval is pending, tell the user and stop.

## Step 0: Know What You're Buying

Before touching the CLI, be able to state:

- **merchant name** and **merchant URL** — where the money goes
- **amount** and currency — exactly
- **why** — a real description; the CLI requires a substantial `context` string and
  the user reads it when approving

If you are missing any of these, ask. Do not invent a merchant or round an amount.

## Step 1: Check the Flags Before You Use Them

```
run_link_cli: link-cli spend-request create --help
```

Read it. Flags differ between versions, and a wrong guess costs a whole turn. For
the full command list: `link-cli --llms`.

## Step 2: Create the Spend Request

```
run_link_cli: link-cli spend-request create \
  --merchant-name "..." --merchant-url "..." \
  --amount <minor units or as --help specifies> \
  --context "..." --format json
```

Add `--test` when the user is trying things out. Say clearly afterwards that it was
test mode.

Keep the returned `id`.

## Step 3: Ask For Approval

```
run_link_cli: link-cli spend-request request-approval <id> --format json
```

This pushes a notification to the user's Link app. Then:

- Tell the user, in plain words, that a request for `<amount>` at `<merchant>` is
  waiting for approval in their Link app.
- If the response carries a `_next` object, prefer its command over composing one.
- Do NOT loop on retrieve waiting for them. One status check is fine; then report
  and stop.

## Step 4: Retrieve and Pay

Once approved:

```
run_link_cli: link-cli spend-request retrieve <id> --format json
```

**Never print a card number.** When you need the raw card, use the command's
`--output-file` flag so it lands in a file and stays out of the conversation, then
read from that file. Tell the user at most the last four digits.

For a 402-gated URL, `link-cli mpp pay <url>` does the whole flow; prefer its
`_next.pay_argv` over building a shell string yourself.

## Step 5: Report the Outcome

```
run_link_cli: link-cli report ...
```

Run this after every purchase attempt, success or failure. Stripe uses it to keep
checkout working; skipping it degrades the service for everyone.

## Limits That Will Bite You

- There are per-request and per-day spend caps. A rejection tells you the real
  number — surface that text to the user rather than paraphrasing.
- The approval window is minutes. An expired request cannot be revived: create a
  new one, and say why.
- Credentials are single-use and expire. Never reuse one for a second purchase.

## Failure Handling

- **Not authenticated** — tell the user to connect Stripe Link on the Integrations
  page. Do not run `auth login` yourself; the connect flow owns that and your
  invocation would strand a device code nobody sees.
- **Approval denied** — accept it. Do not create a near-identical request.
- **Anything else** — surface the CLI's own error text. It is written for a human
  and is almost always actionable.
