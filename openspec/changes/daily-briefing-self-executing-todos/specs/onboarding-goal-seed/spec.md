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
