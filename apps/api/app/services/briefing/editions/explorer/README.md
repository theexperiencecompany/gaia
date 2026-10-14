# Explorer templates — vendored, do not edit

**The founder-approved redesign of 2026-10-14 supersedes the previous set.** The
10 `js/tpl-*.js` files are copied from that session's `editions-v2/round2/` and
register 19 template families (Playbill was removed) on a 540px portrait canvas,
exported at 3x. The contract is unchanged:
`EXPLORER.register({id, name, axes, css, render(ed, skin)})`.

`assets/assets.json` (webfonts, the band wallpaper, the public-domain paintings)
and `assets/credits.json` are carried over. `assets/brand/tec_mark_black.webp` is
The Experience Company symbol, read by Air Mail as `TEC_MARK`. City stamps are not
committed: Air Mail's art is loaded by URL (`assets/stamps/cities.json`,
`editions/stamps.py`).

`app/services/briefing/editions/explorer_render.py` is the only code that loads and
executes these files; `explorer_adapter.py` builds the `ed` they read. Those two
files are ours to change.

## No-edit rule

Do not modify anything under `js/` or `assets/` beyond the permitted deviations
below. These are approved designs; zero design drift is the point of vendoring
them. A real design change comes from the founder's session as a whole-file
replacement, never a hand patch to the CSS.

## Permitted deviations

The founder's fixture filled every slot with plausible demo content, so the
templates print fixture text or invent figures for a real brief. Each edit below
makes a template read the real value, or print nothing. None touches layout, CSS
or a skin axis.

1. **Untimed items.** Real overnight work carries no clock time. `clock()` in
   tpl-brand.js and tpl-postal.js returns an empty string for a missing time
   instead of throwing, and `dayline` (tpl-poster.js) places untimed overnight
   entries in the last hour before now instead of dropping them.
2. **Unknown figures print nothing.** `ed.content.stats` is `null` when GAIA knows
   no figure, and each figure inside it is `null` when unknown (mail handled and
   focus time have no source yet). Every stats slot in every family is guarded:
   the slot, its label and its "you N, GAIA N" split are omitted rather than
   printing `null`. The receipt drops "ITEMS: 0".
3. **The recipient is the user.** `postal`, `memo`, `boardingpass` and `invoice`
   hardcoded the founder's own name. They read `ed.recipient` (the user's full or
   first name) and fall back to "You" (Air Mail's salutation to "Good morning,").
4. **Fixture data reads `ed`.** `weekly` printed a demo week (deck, shipped and
   handled lists, 42/217/31.5/9 figures, fixed chart bars). It now reads `ed.deck`
   and `ed.week`; sections with no data are omitted and only the task counts the
   week really holds are shown. `flightplan`'s "of 100" sheet count is gone.
5. **Empty sections.** `exhibition`'s "Programme for the day" heading is dropped
   when nothing is under it, and `boardingpass` prints "—" as the arrival of a
   day with nothing on it instead of "EOD". Every other family already omits an
   empty section.

The painting that `broadsheet`, `exhibition` and `almanac` hang rotates through
the public-domain paintings in `assets.json`, one step per edition
(`editions/artworks.py`); that is data, not a template edit.

`tests/integration/test_edition_families_render.py` renders every family in
Chromium and fails on a script error, a dropped item, a fixture string, a `null`
or zero-filled figure, a heading above an empty bucket, overprinted item rows, or
an image crop that lets the paper touch the edge or keeps more than 24px of desk.

## Which families are sent

A daily brief draws its family from the user's shuffle bag
(`DAILY_FAMILY_WEIGHTS` in `editions/__init__.py`: Air Mail twice, every other
daily family once; `app/services/briefing/shuffle_bag.py`). The weekly recap is
always `weekly`. Air Mail's city comes from a second bag over the cities in
`assets/stamps/` (`editions/stamps.py`); the render hands the drawn city to the
template as its `city` skin, so the stamp art, the postmark and the dateline
agree. A brief with nothing to report (no asks, no events, nothing overnight)
spends no draw from either bag.
