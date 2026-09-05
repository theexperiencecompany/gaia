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

**Do not modify anything under `js/` or `assets/`.** These are APPROVED
designs — zero design drift is the point of vendoring them. If a template
needs a real change, get an updated file from the founder's session and
replace it wholesale; do not hand-patch the CSS/JS in place.

`explorer_render.py` and `explorer_adapter.py` (the Python renderer + the
`BriefingPayload` → `ed` adapter) are the only files in this feature that are
ours to change.

## The permitted deviations

Three narrow classes of edit to `js/*.js` are allowed — all three fix a
latent correctness bug in the vendored files rather than touch the approved
design. **No layout, CSS, copy, or skin axis was touched by any of them.**

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

## Known gaps — excluded from the rotation pool

`EXPLORER_EXCLUDED_FAMILIES` in `editions/__init__.py` excludes four
families whose gap is deeper than a null guard or a content swap can fix:

- **`weekly`** (tpl-novel-e.js): renders hardcoded demo aggregates, needs a
  real weekly-aggregate adapter.
- **`dayline`** (tpl-poster.js) and **`flightplan`** (tpl-tech.js): position
  events on a real proportional time axis and have no sensible fallback
  position for an item with no clock time. Guarding the crash
  (`.filter((it) => it.t24)` before mapping) keeps them rendering, but most
  `today`/`overnight` items still vanish from the page entirely rather than
  appearing untimed — that needs a real per-item time from the briefing
  pipeline, not a template patch.
- **`metromap`** (tpl-novel-a.js): a *different* real-content-shape gap from
  the two above. Its stations are positioned at fixed SVG coordinates sized
  for the founder fixture's short, 2-3-word station names
  (`"Linear upgrade"`, `"Investor sync"`). Real briefing item text is a
  "complete, self-sufficient sentence" per the briefing prompt contract
  (e.g. `"Design review with Dhruv"`, already close to what overflows) —
  confirmed by rendering the fixed `metromap` against a payload of
  realistic-length item text: the YOU-line term boxes clip off the left/right
  edge of the canvas, and the two decision hollow-station labels overlap
  into unreadable text. There is no existing truncation convention anywhere
  in the vendored set to reuse (checked: the only `.slice()` calls are
  weekday/month abbreviations), and inventing one would mean touching layout,
  which the no-edit rule forbids. `metromap`'s content-derivation fix (see
  above) stays in the code — it's strictly more correct than the literal it
  replaced — but the family needs a content-aware layout (dynamic station
  spacing, or truncation with an approved ellipsis convention from the
  founder) before it can re-join rotation.
