## ADDED Requirements

### Requirement: The hook is free; the labor is metered

The daily briefing, weekly digest, Mission Control (timeline, heatmap, streak), proposals, and the todo list SHALL be available to free users without limits — the retention hook is never paywalled. What free users pay for is GAIA's **execution**: approving/queueing GAIA todo executions SHALL be metered through the existing tiered rate-limit system (`apps/api/app/config/rate_limits.py`) with a new `gaia_todo_executions` feature entry (free: **5 per month** launch default — monthly so each approve is felt; pro: generous). GAIA SHALL keep proposing at full quality regardless of tier — free users always see what GAIA *would* do.

#### Scenario: Free user feels the magic first
- **WHEN** a free user within quota taps Approve
- **THEN** the todo queues and executes exactly as for a pro user

#### Scenario: Proposals never stop at the cap
- **WHEN** a free user has exhausted their execution quota
- **THEN** the briefing still contains fully-formed proposals with previews (drafts visible), and their Approve buttons render the upgrade state

### Requirement: The Approve button is the conversion surface

When a free user at quota taps Approve, the system SHALL NOT silently fail: the tap SHALL open the upgrade flow with the specific staged work as the pitch ("GAIA has 12 investor DMs drafted and ready — upgrade to send them"), reusing the existing rate-limit upgrade-CTA notification pattern. The staged todo SHALL remain in `proposed` (not expired by the standard TTL while it is the active upgrade pitch, up to 7 days). Conversion events (`upgrade_prompt_shown`, `upgrade_from_approve`) SHALL be instrumented alongside the retention events.

#### Scenario: At-quota approve pitches with the actual work
- **WHEN** a free user at quota taps Approve on the investor-DM proposal
- **THEN** the upgrade prompt names that exact staged work, and after upgrading, one tap completes the original approve

#### Scenario: Quota resets restore normal approves
- **WHEN** the daily/monthly window resets
- **THEN** Approve works normally again without any residual upgrade state
