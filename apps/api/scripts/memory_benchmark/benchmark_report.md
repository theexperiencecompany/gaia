# GAIA Memory Engine — Accuracy Benchmark Report

**Overall accuracy: 32/46 probes passed (69.6%)**

## Per-category accuracy

| Category | Passed | Total | % |
|---|---|---|---|
| CONTRADICTION_UPDATE | 2 | 5 | 40% |
| DISTRACTOR_ROBUSTNESS | 0 | 7 | 0% |
| IDENTITY_MAPPINGS | 2 | 2 | 100% |
| INDIRECT_PARAPHRASE | 5 | 5 | 100% |
| MULTI_SESSION_CONSOLIDATION | 8 | 8 | 100% |
| NEGATIVE_ABSTENTION | 4 | 4 | 100% |
| PREFERENCE_PERSISTENCE | 4 | 5 | 80% |
| SINGLE_HOP | 5 | 5 | 100% |
| TEMPORAL_REASONING | 2 | 5 | 40% |

## Recall latency

- P50: **101 ms**
- P95: **128 ms**
- Min: 33 ms  |  Max: 137 ms

## Failing probes (14 of 46)

### `tr_02_recent_vs_old` — TEMPORAL_REASONING
- **Description:** Updated deadline must supersede old one
- **Probe:** When is my project deadline?
- **Expected to contain:** ['april', '15']
- **Must NOT contain:** ['march', 'march 1']
- **Missing terms:** ['april', '15']
- **Actually recalled:** ``

### `tr_04_subscription_expiry` — TEMPORAL_REASONING
- **Description:** Subscription expiry date recall
- **Probe:** When does my Adobe subscription expire?
- **Expected to contain:** ['february', '2026']
- **Must NOT contain:** ['march', 'january']
- **Missing terms:** ['february', '2026']
- **Actually recalled:** ``

### `tr_05_sequence_of_events` — TEMPORAL_REASONING
- **Description:** Current title is Staff, not Senior (most recent state)
- **Probe:** What is my current job title?
- **Expected to contain:** ['staff']
- **Must NOT contain:** ['senior']
- **Forbidden terms found:** ['senior']
- **Actually recalled:** `The user worked as a Senior Engineer for three years prior to their promotion to Staff Engineer on January 3, 2026. | The user was promoted to Staff Engineer on January 3, 2026.`

### `cu_01_moved_cities` — CONTRADICTION_UPDATE
- **Description:** Current city is Seattle; old SF fact must not surface
- **Probe:** Where do I live?
- **Expected to contain:** ['seattle']
- **Must NOT contain:** ['san francisco', 'sf']
- **Forbidden terms found:** ['san francisco']
- **Actually recalled:** `The user lives in San Francisco. | The user moved to Seattle in January 2026.`

### `cu_02_changed_jobs` — CONTRADICTION_UPDATE
- **Description:** Current employer is Databricks; Twilio is old
- **Probe:** Where do I work?
- **Expected to contain:** ['databricks']
- **Must NOT contain:** ['twilio']
- **Forbidden terms found:** ['twilio']
- **Actually recalled:** `The user works at Databricks. | The user no longer works at Twilio.`

### `cu_03_diet_change` — CONTRADICTION_UPDATE
- **Description:** Diet updated to vegan; old vegetarian must not dominate
- **Probe:** What is my diet?
- **Expected to contain:** ['vegan']
- **Must NOT contain:** ['vegetarian']
- **Forbidden terms found:** ['vegetarian']
- **Actually recalled:** `The user adopted a vegan diet on November 9, 2025. | The user is a vegetarian.`

### `pp_05_travel_style` — PREFERENCE_PERSISTENCE
- **Description:** Flight seating preference
- **Probe:** What seat do I prefer on flights?
- **Expected to contain:** ['window']
- **Must NOT contain:** ['middle', 'aisle']
- **Forbidden terms found:** ['middle', 'aisle']
- **Actually recalled:** `The user prefers window seats when traveling. | The user prefers aisle exit rows when traveling. | The user dislikes middle seats and avoids booking them.`

### `dr_01_three_siblings` — DISTRACTOR_ROBUSTNESS
- **Description:** Marcus's age, not Jake's (28) or Eli's (25)
- **Probe:** How old is Marcus?
- **Expected to contain:** ['32']
- **Must NOT contain:** ['28', '25']
- **Forbidden terms found:** ['28', '25']
- **Actually recalled:** `The user has a brother named Marcus who is 32 years old. | The user has a brother named Jake who is 28 years old. | The user has a brother named Eli who is 25 years old.`

### `dr_01_three_siblings` — DISTRACTOR_ROBUSTNESS
- **Description:** Youngest sibling identification
- **Probe:** Which of my brothers is youngest?
- **Expected to contain:** ['eli', '25']
- **Must NOT contain:** ['jake', 'marcus']
- **Forbidden terms found:** ['jake', 'marcus']
- **Actually recalled:** `The user has a brother named Jake who is 28 years old. | The user has a brother named Eli who is 25 years old. | The user has a brother named Marcus who is 32 years old.`

### `dr_02_three_projects` — DISTRACTOR_ROBUSTNESS
- **Description:** Paused project is Beacon, not Atlas or Comet
- **Probe:** Which project is paused?
- **Expected to contain:** ['beacon']
- **Must NOT contain:** ['atlas', 'comet']
- **Forbidden terms found:** ['comet']
- **Actually recalled:** `The user has paused work on the project named Beacon. | The user has started a new project named Comet.`

### `dr_02_three_projects` — DISTRACTOR_ROBUSTNESS
- **Description:** Urgent project is Atlas
- **Probe:** Which project has a deadline coming up soon?
- **Expected to contain:** ['atlas']
- **Must NOT contain:** ['beacon', 'comet']
- **Missing terms:** ['atlas']
- **Forbidden terms found:** ['beacon', 'comet']
- **Actually recalled:** `The user has started a new project named Comet. | The user has paused work on the project named Beacon.`

### `dr_03_three_colleagues` — DISTRACTOR_ROBUSTNESS
- **Description:** Manager is Sarah, not Tom or Alex
- **Probe:** Who is my manager at work?
- **Expected to contain:** ['sarah']
- **Must NOT contain:** ['tom', 'alex']
- **Forbidden terms found:** ['tom', 'alex']
- **Actually recalled:** `The user's manager is Sarah. | Tom is the product manager on the user's team. | The user mentors Alex, who is an engineer.`

### `dr_03_three_colleagues` — DISTRACTOR_ROBUSTNESS
- **Description:** Mentee is Alex
- **Probe:** Who do I mentor?
- **Expected to contain:** ['alex']
- **Must NOT contain:** ['sarah', 'tom']
- **Forbidden terms found:** ['sarah', 'tom']
- **Actually recalled:** `The user mentors Alex, who is an engineer. | Tom is the product manager on the user's team. | The user's manager is Sarah.`

### `dr_04_three_addresses` — DISTRACTOR_ROBUSTNESS
- **Description:** Home address, not office or parents'
- **Probe:** What is my home address?
- **Expected to contain:** ['14', 'oak']
- **Must NOT contain:** ['200', 'tech', 'maple']
- **Forbidden terms found:** ['200', 'tech', 'maple']
- **Actually recalled:** `The user lives at 14 Oak Street. | The user's parents live at 7 Maple Ave. | The user's office is at 200 Tech Blvd.`

## Ranked weaknesses (worst categories first)

### 1. DISTRACTOR_ROBUSTNESS — 0% (0/7)
- Example failure: **Marcus's age, not Jake's (28) or Eli's (25)**
  - Probe: `How old is Marcus?`
  - Recalled: `The user has a brother named Marcus who is 32 years old. | The user has a brother named Jake who is 28 years old. | The user has a brother named Eli who is 25 years old.`

### 2. CONTRADICTION_UPDATE — 40% (2/5)
- Example failure: **Current city is Seattle; old SF fact must not surface**
  - Probe: `Where do I live?`
  - Recalled: `The user lives in San Francisco. | The user moved to Seattle in January 2026.`

### 3. TEMPORAL_REASONING — 40% (2/5)
- Example failure: **Updated deadline must supersede old one**
  - Probe: `When is my project deadline?`
  - Recalled: ``

### 4. PREFERENCE_PERSISTENCE — 80% (4/5)
- Example failure: **Flight seating preference**
  - Probe: `What seat do I prefer on flights?`
  - Recalled: `The user prefers window seats when traveling. | The user prefers aisle exit rows when traveling. | The user dislikes middle seats and avoids booking them.`

### 5. IDENTITY_MAPPINGS — 100% (2/2)

### 6. INDIRECT_PARAPHRASE — 100% (5/5)

### 7. MULTI_SESSION_CONSOLIDATION — 100% (8/8)

### 8. NEGATIVE_ABSTENTION — 100% (4/4)

### 9. SINGLE_HOP — 100% (5/5)

## Engine seams used for temporal injection

- `ingestion.retain()` captures `datetime.now(UTC)` internally (line ~88 of ingestion.py).
- No `occurred_at` injection parameter exists on `retain()` — temporal simulation required monkeypatching `app.memory.ingestion.datetime` with a subclass whose `now()` classmethod returns the desired simulated date.
- The patch is scoped per-`retain()` call (context manager) so it does not leak into retrieval, consolidation, or other concurrent tasks.
- `recall()` also calls `datetime.now(UTC)` for recency boosting and `forget_after` enforcement — these were NOT patched so the recency decay scores reflect real wall time, which may suppress older simulated facts unfairly.
