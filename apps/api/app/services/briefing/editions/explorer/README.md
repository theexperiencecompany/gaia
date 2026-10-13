# Explorer templates — vendored, do not edit

The 10 `js/tpl-*.js` files and `assets/assets.json` + `assets/credits.json` are
copied verbatim from the founder's hand-vetted design-explorer session
(recovered session `547b140a`, `~/Downloads/gaia-daily-briefing-session/sources/`).

Together the 10 files register 20 approved template families via
`EXPLORER.register({id, name, axes, css, render(ed, skin)})` — see
`explorer-contract.md` from that session for the full authoring contract (the
`ed` shape, axis/skin rules, font/asset wiring). `app/services/briefing/editions/explorer_render.py`
is the only code that loads and executes these files; it treats them as an
opaque, pre-approved rendering engine.

## No-edit rule

**Do not modify anything under `js/` or `assets/` beyond the permitted
deviations below.** These are APPROVED
designs — zero design drift is the point of vendoring them. If a template
needs a real change, get an updated file from the founder's session and
replace it wholesale; do not hand-patch the CSS/JS in place.

`explorer_render.py` and `explorer_adapter.py` (the Python renderer + the
`BriefingPayload` → `ed` adapter) are the only files in this feature that are
ours to change.

## The permitted deviations

Four narrow classes of edit to `js/*.js` are allowed — each fixes a latent
correctness bug in the vendored files rather than touch the approved design.
**No layout, CSS or skin axis was touched by any of them.** The stamp art in
`assets/stamps/` is an asset swap for Air Mail's city skin, not a JS edit.

### 1. Null guards

The founder's session fixture always populated every item's clock field
(`t24`/`.time`) and note text, so the templates were never authored against a
missing one. `explorer_adapter.build_ed` only sets `t24`/`.time` when an
item's text carries a literal leading clock prefix — which real daily-brief
text never does — and it always sets `.note` to `None` (the payload has no
per-item note field at all). Rendering real `BriefingPayload` data through
the vendored templates therefore hits code paths the founder's fixture never
exercised: a bare `t24.split(":")` throws on `null`, and a bare
`${it.note}`/`esc(it.t24)` interpolation prints the literal string `"null"`
into the design.

The fix is minimal, surgical null guards at those exact call sites —
`if (!t24) return "";`, `it.t24 || ""`, `note ? ... : ""` — matching
whichever placeholder convention the same template already used elsewhere
for a missing value (`"EOD"`, `"&mdash;"`, or an empty string).

### 2. Content-slot hardcoding (SonarCloud S930)

A 2025 audit found that several families read a **literal string** into a
content slot instead of the matching `ed`/`c` field — e.g. `metromap`
rendering the literal `"Inbox zero"` as a station name instead of
`ov[0].label`. Our own visual QA had missed this because the test payload
mirrored the founder's fixture almost verbatim, so a hardcoded literal and a
correctly-derived field rendered identically. Every fixed literal was
swapped for its obvious `ed`/`c` counterpart, preserving the exact layout,
truncation, and variable names already in scope — never widening what a
family reads from `ed`. Touched: `metromap`/`boardingpass`
(tpl-novel-a.js), `playfair`/`postal` (tpl-brand.js — `playfair`'s section
counts were the literals `"Three"`/`"Three"`/`"Two"` instead of
`c.today.length`/`c.overnight.length`/`c.decisions.length`), `menu`
(tpl-novel-b.js — the entire three-course block was fixture text; now reads
`c.today[0..2].label`/`.t24`/`.note`, with the same conditional-render guard
`menu`'s own `overnight` block already used for a possibly-null note), and
`invoice` (tpl-novel-c.js — a hardcoded qty `"23"` and unit `"EOD"`/`"1 PR"`
that ignored `t[2].t24` entirely).

One SonarCloud finding in `metromap` was a real bug, not just hardcoded
content: `mmHollow(x, y, name, note, full)` is declared with 5 parameters
but was called with 6 args at both decision-station call sites (the extra
trailing arg was the real `full` boolean — JS silently drops it, so the
function's own `full` parameter was actually bound to a hardcoded string
literal, which is always truthy; the `notes: full/terse` skin axis therefore
never actually suppressed a decision station's note). The call sites now
pass exactly 5 args (`dec[n].label`, `dec[n].note`, `full`), so the call
matches the declared signature and the skin axis works as designed.

### 3. Identity fields with no `ed` counterpart

Three spots hardcode the founder's own name/surname as if it were the
recipient's: `postal`'s "TO" address block (`ARYAN RANDERIYA`),
`boardingpass`'s Passenger field + stub + boarding-pass barcode number
(`ARYAN RANDERIYA` / `RANDERIYA/A`), and `memo`'s `TO:` line (`Aryan`). `ed`
carries no user-identity field at all (`BriefingPayload` has none, and
threading one through would mean plumbing a new field across
`edition_email.py` → `render_explorer_edition` → `build_ed`, which is out of
scope for a vendored-template content fix). Since shipping a specific,
wrong, real person's name to every other user is not an acceptable
"furniture" literal, these three spots were changed to the generic,
universally-true address **"YOU"** — honest for every recipient, and not a
fabricated fact the way a wrong name is.

## 4. Real brief data the fixture never exercised

The founder fixture filled every slot with plausible demo content, so several
templates printed fixture text or invented figures for a real brief. These
edits make a template read the real value — or render nothing — and change no
layout, CSS or skin axis:

- **Missing figures render nothing** (all families). `ed.content.stats` holds
  `None` for a figure GAIA does not know (mail handled, focus time) or that is
  zero, and every stat slot is guarded: the slot, its label and its
  "you N, gaia N" split are omitted instead of printing `0` or `null`.
- **The headline has a title slot** (`memo` RE: line, `postal` envelope "Re:",
  `broadsheet` lead headline): `ed.headline`, a field the fixture lacked. Every
  other family's single text slot, `ed.deck`, carries the headline.
- **The week is real** (`weekly`): `weekFixture`'s demo week ("term sheet
  signed with Mehul", "217 emails handled") is replaced by `ed.week`, built by
  the adapter from the brief's real completions and calendar; bar heights scale
  to the week's own peak. Unknown counts (decisions made, meetings) are gone.
- **Untimed items are kept** (`dayline`): untimed overnight entries join the
  cluster and every untimed today item sits in the before-EOD slot, where the
  template used to drop them; decisions float into the first morning slots that
  clear the day's real events instead of fixed 09:30/11:20 positions.
- **Fixture literals read `ed`** (`flightplan`): the Detail A callout
  ("Ship approval-flow PR · CI green 05:40") shows the day's untimed item, the
  overnight section names the real time range, events print their start only
  (never an invented 30-minute end), and the sheet number drops "of 100".

`tests/integration/test_edition_families_render.py` renders every family in
Chromium with a real and a quiet brief and fails on a blank image, a dropped
item, a fixture string, a zero-filled figure, or a missing headline.

## Which families are sent

A daily brief draws its family from the user's shuffle bag
(`DAILY_FAMILY_WEIGHTS` in `editions/__init__.py`, Air Mail twice, every other
drawable family once; `app/services/briefing/shuffle_bag.py`). The weekly recap
is always `weekly`. Air Mail's city stamp comes from a second bag over the 85
cities in `assets/stamps/` (`editions/stamps.py`); the render harness hands the
drawn city to the template as its `city` skin, so the stamp art, the
"GAIA Post · CITY" line, the denomination and the postmark agree.

## Fixed item slots — padded by the adapter, not patched here

`boardingpass`, `metromap`, `menu`, `invoice` and `almanac` read fixed item
positions (`today[2]`, `decisions[1]`, ...) because the founder fixture always
held three today, three overnight and two decision items. Handed fewer, their
page script threw and the brief rendered as a blank strip. The adapter pads
exactly those buckets with an empty slot (`—`, `explorer_adapter._FIXED_SLOTS`).

## Known gap — registered, never drawn

- **`metromap`** (tpl-novel-a.js): its stations sit at fixed SVG coordinates
  sized for the founder fixture's two-word station names ("Linear upgrade").
  Real item text clips off the canvas edge and the decision station labels
  overprint each other (re-confirmed rendering a real brief, 2026-10-14). There
  is no truncation convention in the vendored set and inventing one would
  change the layout, so the family stays out of the bag (`_NOT_DRAWN`) until
  the founder's session supplies a content-aware layout.
