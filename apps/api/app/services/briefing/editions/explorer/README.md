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

## The one permitted deviation: null guards

The founder's session fixture always populated every item's clock field
(`t24`/`.time`) and note text, so the templates were never authored against a
missing one. `explorer_adapter.build_ed` only sets `t24`/`.time` when an
item's text carries a literal leading clock prefix — which real daily-brief
text never does — and it always sets `.note` to `None` (the payload has no
per-item note field at all). Rendering real `BriefingPayload` data through
the vendored templates therefore hits code paths the founder's fixture never
exercised: a bare `t24.split(":")` throws on `null`, and a bare
`${it.note}`/`esc(it.t24)` interpolation prints the literal string `"null"`
into the design. Both are latent bugs in the vendored files, not something
this adapter introduced.

The only edits made to `js/*.js` are minimal, surgical null guards at those
exact call sites — `if (!t24) return "";`, `it.t24 || ""`, `note ? ... : ""` —
matching whichever placeholder convention the same template already used
elsewhere for a missing value (`"EOD"`, `"&mdash;"`, or an empty string).
**No layout, CSS, copy, or skin axis was touched.** This is the single
permitted deviation from byte-identical vendoring: the founder's designs are
sacred, crashing or printing "null" on screen is not.

Two families surface a deeper, adapter-level gap that a null guard cannot
fix: `dayline` (tpl-poster.js) and `flightplan` (tpl-tech.js) position events
on a real proportional time axis and have no sensible fallback position for
an item with no clock time. Guarding the crash (`.filter((it) => it.t24)`
before mapping) keeps them rendering, but most `today`/`overnight` items
still vanish from the page entirely rather than appearing untimed — that
needs a real per-item time from the briefing pipeline, not a template patch,
and is left as a known gap rather than papered over with a layout change.
`weekly` (tpl-novel-e.js) is excluded from the rotation pool entirely
(`EXPLORER_EXCLUDED_FAMILIES` in `editions/__init__.py`) because it renders
against hardcoded demo data rather than `ed.content`.
