## ADDED Requirements

### Requirement: Onboarding asks what the user is working on — on every path

The onboarding flow SHALL ask "What are you working on right now?" (free text) on all paths, including the Gmail-connected happy path that today skips intent capture. The answer SHALL be written to the memory system so every future agent run sees it, and SHALL unify with the existing `onboarding.focus` handling (one write path; the dormant field is revived rather than duplicated).

#### Scenario: Gmail-path user states a goal
- **WHEN** a user connects Gmail during onboarding and answers "raising a pre-seed, growing Twitter, shipping v2"
- **THEN** the goals are retrievable from memory in any subsequent agent run

### Requirement: The first briefing proves the goal was heard

The user's first daily briefing SHALL contain at least one proposed or queued GAIA todo whose `serves` traces to the stated onboarding goal. Cold start is the highest-risk retention moment; a generic first briefing is a spec violation, not a degraded mode. When the user skipped the question, the first briefing SHALL derive its proposals from onboarding triage (existing intelligence pipeline) and ask the goal question as its closing line.

#### Scenario: First morning lands on the stated goal
- **WHEN** a user onboarded yesterday stating "raising a pre-seed"
- **THEN** the first briefing includes at least one item tracing to fundraising (e.g. proposed investor research) rather than only generic inbox items

### Requirement: Existing users are announced to and interviewed, not cold-started

When daily briefings are provisioned for the existing user base, each user SHALL receive a one-time announcement — delivered to all their connected channels (in-app, linked platforms, email) — introducing daily briefings. Before a user's first briefing, the run SHALL attempt to derive their goals from memory, integrations, and todo history. When it can derive enough, the first briefing proceeds normally and states what it inferred ("I've noticed you're working on X — correct me if not"). When it cannot, the announcement SHALL instead ask a short bootstrap interview (2–3 questions: what are you working on, what should GAIA take off your plate, preferred briefing hour) whose replies write to memory; briefings for that user begin the morning after answers arrive, or after 3 days with a triage-derived best-effort briefing that repeats the questions as its closing line.

#### Scenario: Rich-memory user gets an inferred first briefing
- **WHEN** an existing user with substantial memory and integrations is provisioned
- **THEN** their announcement is followed the next morning by a briefing whose items trace to inferred goals, with an explicit correct-me line

#### Scenario: Empty user gets interviewed first
- **WHEN** an existing user with no memory, no integrations beyond Gmail, and no todos is provisioned
- **THEN** they receive the announcement with the bootstrap questions and no briefing fires until answers arrive or the 3-day fallback

#### Scenario: Interview replies seed memory
- **WHEN** the user replies "raising a pre-seed and shipping v2" on any channel
- **THEN** both goals are retrievable from memory and the next morning's briefing traces to them
