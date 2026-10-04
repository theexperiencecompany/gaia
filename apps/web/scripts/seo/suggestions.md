# SEO page suggestions — 2026-10-04

> **SAMPLE DATA** — generated with `--dry-run`. All queries/impressions/positions below are fixtures, not real GSC numbers.

## Inputs

- Queries scanned: **20** (impressions>50 + position 5–30: **6** uncovered, 12 already covered, 2 out of range)
- Existing pages: comparisons 100 · alternatives 53 · combos 214 · personas 34 · glossary 179 + 3 static landing pages
- Priority heuristic (GSC numbers only, no invented search volume): `score = impressions × (31 − position) / 26` → High ≥ 398.8, Medium ≥ 140.3, else Low

## Top 6 missing opportunities

| # | Query | Clicks | Impr | CTR | Pos | Suggested path | Template | Priority | Why |
| - | ----- | ------ | ---- | --- | --- | -------------- | -------- | -------- | --- |
| 1 | what is timeboxing | 17 | 1900 | 0.89% | 20.3 | `/learn/timeboxing` | `/learn/[term]` | High | informational query; score 781.9 |
| 2 | gaia vs routine | 21 | 880 | 2.39% | 11.5 | `/compare/routine` | `/compare/[slug]` | High | head-to-head 'vs' query; score 660.0 |
| 3 | timehero alternative | 9 | 640 | 1.41% | 14.8 | `/alternative-to/timehero` | `/alternative-to/[slug]` | High | replacement intent; score 398.8 |
| 4 | vibe coding setup guide | 7 | 720 | 0.97% | 23.7 | `/learn/vibe-coding-setup-guide` | `/learn/[term]` | Medium | informational query; score 202.2 |
| 5 | sync stripe with google drive automatically | 4 | 380 | 1.05% | 21.4 | `/automate/drive-stripe` | `/automate/[combo]` | Medium | integration/automation intent; score 140.3 |
| 6 | routine alternative ai | 4 | 310 | 1.29% | 19.4 | `/alternative-to/routine` | `/alternative-to/[slug]` | Low | replacement intent; score 138.3 |

## Next step

Pick the top High-priority rows and create the page under the suggested template (content already has per-slug JSON + getters). Re-run `seo:pull-gsc` weekly and diff this file to track coverage.
