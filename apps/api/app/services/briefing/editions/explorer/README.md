# Explorer templates — vendored, do not edit

**The founder-approved redesign of 2026-10-14 supersedes the previous set.** The
10 `js/tpl-*.js` files are copied from that session's `editions-v2/round2/` and
register 19 template families (Playbill was removed) on a 540px portrait canvas,
exported at 3x. The contract is unchanged:
`EXPLORER.register({id, name, axes, css, render(ed, skin)})`.

**2026-10-21: the audited Round 6 edition replaces all 10 files.** Every family
was re-scored on a 12-criterion audit and polished (no one-word widows, content
type at 15px or more, furniture at 13px or more, Air Mail's P.S. as a sentence,
Day Line's three-hour axis, Line Guide's ringed decision stops, Library Card's
ditto marks, "Plat du jour" for a lone course, weekend bars dimmed in the
weekly). The deviations below were re-applied by a three-way merge against the
pre-audit source, so each new stats line keeps its null guards, the recipient
slots keep `ed.recipient`, and the weekly keeps reading the real `ed.week`. The
founder's weekly relabelled today's items as "Next up, today"; ours still shows
the real week ahead, and only the "Weekend shown lighter" legend and the
"still open this morning" note were taken from it.

**2026-10-23: Air Mail's envelope is re-drawn (tpl-postal.js only).** The kraft
sheet, chevron border, embossed back-flap seams and worn edges are one inline SVG
with seeded noise; the PAR AVION etiquette is a die-cut, off-register SVG label; a
small engraved definitive sits beside the city stamp; and the duplex cancellation is
a hand-struck datestamp with a wavy-line killer (the edition number on the killer is
gone). Every seed and tilt comes from the edition date. The same deviations 1, 2, 3
and 7 were re-applied by a three-way merge.

**2026-10-23: the founder's curation (tpl-poster, tpl-postal, tpl-tech, tpl-brand,
tpl-transit, tpl-image).** The Day Line family is cut, so 18 families remain. Air
Mail drops its red postmark, and its city axis is every hosted city: the template
reads `EXPLORER.cities`, which `explorer_render.py` fills from `stamps.city_axis()`,
and each city's art is the asset `CITY_<SLUG>`. The Blueprint drops vandyke and
re-tones Prussian blue; the Instrument drops olive; the Band adds violet, pink, red,
teal and lime; the Boarding Pass liveries are now midnight + sunflower, sky blue,
signal red and graphite + champagne; the Horizon adds meadow, ember, rosewater and
aurora. Applied by a three-way merge, so every deviation below is kept.

`assets/assets.json` holds the band wallpaper. The webfonts live in
`editions/fonts/` (deviation 10).
`assets/brand/tec_mark_black.webp` is The Experience Company symbol, read by Air
Mail as `TEC_MARK`. City stamps and paintings are not committed: both are loaded
by URL (`assets/stamps/cities.json` with `editions/stamps.py`,
`assets/artworks/artworks.json` with `editions/artworks.py`).

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
or a skin axis, except where an entry says it is a founder-approved layout change
(6), a real code cannot be drawn any smaller (8), or the founder-approved type
(10 to 12).

1. **Untimed items.** Real overnight work carries no clock time. `clock()` in
   tpl-brand.js and tpl-postal.js returns an empty string for a missing time
   instead of throwing.
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
   day with nothing on it instead of "EOD" (a day whose only item is at
   departure time still arrives at "EOD"). Every other family already omits an
   empty section.
6. **The invoice bills only what is real (founder-approved layout change,
   2026-10-21).** It printed "1 Wednesday" as the amount due, balance and
   remittance, "1 slot"/"1 ship" on today's rows and "0.00" on every overnight
   row. A brief has no amounts, so the Amount column is gone (`.li` and `.cols`
   are two columns, the unused `.f.zero` rule is removed), and the amount box,
   the balance line and the slip read "Awaiting you" with `ed.content.awaiting`
   (every todo waiting on the reader, a grouped ask counting each), or
   "Nothing" when none waits.
7. **Running work is not filed as done.** `ed.content.overnight` holds only what
   finished; GAIA's still-running work is `ed.content.running`, and every family
   prints it as its own block after the overnight one, reusing that block's row
   markup under a "still in progress" heading in the family's voice (Air Mail
   printed running work under "Done while you slept").
8. **No invented passenger or total.** The boarding pass's barcode line printed the
   founder's passenger code "RANDERIYA/A"; it now prints the user's own
   (`SURNAME/I` from `ed.recipient.name`, the single name when there is one, and
   nothing without a recipient). The receipt totalled "1 <weekday>" under its
   figures; that line and its now-unused `.total` rule are gone, and the double
   rule still closes the figures.
9. **Every code scans to the brief's link (2026-11-10).** The Invoice's QR, the
   Receipt's barcode and the Boarding Pass's barcode were pixels seeded by the
   edition number, and encoded nothing. `qr()` (tpl-paper.js) and both `barcode()`
   functions (tpl-receipt.js, tpl-transit.js) are deleted. `editions/codes.py`
   encodes `payload.link` (its heygaia.link, or its page URL when minting failed)
   and passes the geometry as `ed.codes`. Each template draws it with
   `EXPLORER.code`, which `explorer_render.py` defines. The Invoice draws a QR
   (segno) in the same 108px box. The Receipt draws a Code 128 (python-barcode) at
   1px per module, up to the tape's width. The Boarding Pass's `code` axis now
   names a symbology instead of a row count. `linear` is a Code 128 at 1px per
   module, and `stacked` is a real PDF417 (pdf417gen) at 2px per module, 64px tall
   as before. Two founder-approved shapes change, because a real code cannot be
   smaller. The Receipt's barcode is about 387px wide instead of about 145px. The
   Boarding Pass's linear code is about 387px wide instead of 360px. The stacked
   code has no 2px gaps between its rows, because a PDF417 with gaps does not
   scan. If the page URL is too long for the width, it is squeezed below 1px per
   module, and the Code 128 then reads only at render size, not at the delivered
   1080px. `tests/integration/test_edition_codes_scan.py` decodes each code from
   the rendered PNG.
10. **Every family is set in embedded type (2026-11-11).** The templates named
   macOS system faces (Helvetica Neue, Didot, Iowan Old Style, Menlo, American
   Typewriter, ...), so a Linux render fell back to whatever the host had. Each
   family's stacks now name the open-licensed faces the founder approved in the
   type gallery, one face per stack plus its generic, and nothing else changed in
   those declarations. `editions/fonts/` holds the subset WOFF2 files, their
   licences and `fonts.json`, built by `scripts/build_edition_fonts.py` from pinned
   sources. `explorer_render.py` embeds, as data URIs, only the families the drawn
   family is set in (`edition_fonts.EDITION_FAMILIES`). Playfair Display and Aeonik
   Extended moved out of `assets.json` into that directory. A type axis whose
   options now draw the same face is one option: broadsheet's masthead, gradient's
   and exhibition's heads, librarycard's, menu's, memo's, almanac's, flightplan's,
   instrument's and metromap's faces. The invoice keeps only its Heros figures, so a
   row is never set in two families. Memo keeps the Courier option's 18px. Swiss
   keeps both its faces, which are different approved faces. Librarycard's date
   stamps are set in Special Elite with the rest of their row, not Courier.
11. **The type rules hold in every family (2026-11-11).** A row is one family, a
   section has one label, and a heading is never lighter than its items. Air
   Mail's times, tags and P.S. leave the typewriter face for the letter's serif
   (the P.S. figures are bold instead of larger), and its "To" is upright, as
   Cutive has no italic. Exhibition's tags take the row's sans, upright, and the
   "Programme for the day" label over the first section is gone. The weekly's day
   and numeral labels take the row's sans. Playfair's section count is set in the
   heading's italic. Swiss's times take the row face, so an Aeonik skin never
   mixes faces in a row. Broadsheet drops the kicker above each section heading
   and keeps its rule as the section's top border. Librarycard's and the
   receipt's section headings are bold, and the Instrument's lamps are 700, the
   weight of its headings. Librarycard's signature asks for Pinyon Script's one
   weight, so it is not synthesised bold.
12. **Layout fixes the new faces exposed (2026-11-11).** Swiss's weekday and its
   "No N" are in flow in their column, so a long weekday no longer overprints
   the number (the page grows instead). The receipt's ruled lines are cut to whole
   characters, so no partial "=" shows at the edge. Almanac's dateline and plate
   caption are balanced, and "No. N" never breaks across a line in the almanac,
   the memo and the weekly's footer. Librarycard's record avoids a one-word last
   line. Broadsheet's lead keeps its item's capital ("At 11:00 a.m., Sequoia
   partner meeting", not "sequoia").

13. **Every family draws GAIA's composed blocks in its own idiom (2026-11-11,
   founder-reviewed gallery `brief-gallery/v2` and its reading system).** The fixed
   today / overnight / running / decisions sections are gone: `ed.content` and
   `ed.week` are replaced by `ed.blocks` (lead, items, calendar, chart, quote,
   progress, note, in reading order), `ed.awaiting` and `ed.stats`. Each family's
   `render` maps every block kind to its own renderer through
   `EXPLORER.blocks.layout(ed, R)`; the furniture (masthead, stats, codes, stamp,
   painting) is unchanged. Items follow the reading system (`shell/reading.css`):
   verb or outcome first, then the app's mark, the title and one detail; a label
   column only for calendar times; one label per section; headings outrank items;
   three rows and "+N more in the full brief". Charts are plotted from the series
   points (`shell/blocks.js`), never from model numbers, each with its title,
   takeaway, range, unit, labelled values and a legend. `shell/` is ours, not
   vendored: it holds the shared anatomy, the app marks
   (`editions/logos/logos.json`, built from the integration-logos registry by
   `scripts/build_edition_logos.py`) and the plots, and decides nothing about a
   family's look. What each family leaves out is `editions/capabilities.py`:
   the Menu draws no chart and no goal, Air Mail no chart, the Memo no line or
   spark, the weekly no lead and no quote. Per family:
   - `band`, `playfair` (tpl-brand.js): each block is a band section under a
     hairline / continues the book's roman numbering under one heading; charts
     in white and the accent / gilt; the `clock` helper is gone. Playfair's
     right-hand section count is dropped, and its titles are 400 (Literata has
     no bold cut), the verb set apart by colour.
   - `broadsheet`: groups that all ask go in the boxed notice, the rest are
     stories; the plate hangs under the calendar's heading; charts are boxed
     graphics with a halftone second series and a source line; quotes are pull
     quotes (Caslon's historical ligatures off); notes run under "From GAIA's
     desk". The front-page summary counts the blocks.
   - `swiss` (tpl-poster.js): every block is a numbered section ("00" the lead);
     the verb takes whichever of the skin's two marker colours shows on its
     background; the spine's "No N" counts the rows printed.
   - `gradient`, `exhibition`, `weekly` (tpl-image.js): the Horizon sets charts
     in ink with a thinned second series and quotes large against the sky; the
     Exhibition pins the lead as a museum label, hangs charts with a caption and
     sets quotes as wall text, its titles at 400 so the 400-only Bodoni heading
     outranks them; the weekly's fixed shape-of-the-week chart, shipped and
     handled lists and its `chart` skin axis are gone (composed blocks replace
     them, and the "weekend shown lighter" dimming with them), "The numbers"
     reads `ed.stats`, and its calendar is the week ahead.
   - `postal`: blocks are letter paragraphs; a quote is an indented italic
     passage; the goal joins the P.S. as a sentence; `clock()` is gone.
   - `librarycard`, `menu`, `invoice` (tpl-paper.js): the card's date stamps
     and ditto marks give way to the anatomy, and charts and goals go on a
     second "verso" card; the menu's courses are GAIA's groups under foil rules
     with "The day's courses", its spelled-out times gone; the invoice prints
     charts as line-item tables or a usage plot, goals under "Plans", quotes
     under "Correspondence", notes in a "Notes" box. Librarycard and menu titles
     are 400 (Special Elite and EB Garamond have no bold cut).
   - `memo`, `almanac` (tpl-print.js): the memo's charts are typed
     "Attachment" tables with typed-cell bars, the goal a typed `[XXX---]` bar,
     the note "N.B."; the almanac's charts are engraved figures with a hatched
     second series and "Fig. N." captions, the quote an epigraph, the goal and
     note rubric pilcrow paragraphs, its titles at 400.
   - `flightplan`, `instrument` (tpl-tech.js): blocks are lettered details on
     the drafting sheet / screwed-in modules whose heading is their only label;
     the elevation and the gauge plot timed events only, labelled with their
     times (the 18:00 stand-in for untimed events is gone).
   - `metromap`, `boardingpass` (tpl-transit.js): runs of groups and the
     calendar become line segments (decision, day and night lines) joined by
     interchanges and closed by a terminus, data blocks are panels or notice
     bars, and the line guide lists only the lines drawn; the boarding pass
     carries reading blocks on its body, a closing done group on the stub, and
     charts and goals on a "Flight log" card, and departs and arrives at the
     day's first and last timed starts.
   - Every family closes on a line naming the apps the brief read, with their
     marks (`ed.sources`), in its idiom: the receipt's "MADE FROM YOUR …" under
     the colophon, the invoice's "Prepared from your …" at the sheet's foot,
     the weekly's line under its folio, the menu's "With produce from your …",
     the memo's typed "VIA:", the line guide's "Connecting services" chips and
     so on.
   - Item titles are bold in a real cut: Libre Baskerville 700, Literata 700,
     EB Garamond 600, Playfair Display 700 italic, Bodoni Moda 700 italic and
     Cormorant 600 italic are added to the font build. Special Elite has one
     weight, so the library card's titles stay 400 and its verbs carry the
     stamp ink; no weight is ever synthesised.
   - A figures box holds only the figures a brief has: the instrument's
     readout, the band's and playfair's figures, and the boarding pass's box
     take as many columns as there are figures, never a lone third. Air Mail,
     the weekly and the almanac say "1 thing" and "1 task".

The painting that `broadsheet`, `exhibition` and `almanac` hang is drawn from the
user's artwork shuffle bag, over the Met Open Access works whose image fits that
family's frame (`editions/artworks.py`), and recorded on the payload as
`artwork_id`; that is data, not a template edit.

`tests/integration/test_edition_families_render.py` renders every family in
Chromium and fails on a script error, a dropped item, a fixture string, a `null`
or zero-filled figure, a block drawn for an empty brief, overprinted item rows, or
an image crop that lets the paper touch the edge or keeps more than 24px of desk.
`tests/integration/test_edition_reading_system.py` renders every family over four
compositions and measures the reading system's rules on the page.

## Which families are sent

A daily brief draws its family from the user's shuffle bag
(`DAILY_FAMILY_WEIGHTS` in `editions/__init__.py`: Air Mail twice, every other
daily family once; `app/services/briefing/shuffle_bag.py`), after composition:
only a family that can draw every composed block is eligible
(`edition_draws.draw_edition`), and one that cannot keeps its turn for a later
day. When no daily family can draw them all, the bag's next family draws and the
rest are stored as `payload.undrawn` for the brief's page. The weekly recap is
always `weekly`; a block it cannot draw goes to `undrawn` too. Air Mail's city comes from a second bag over the cities in
`assets/stamps/` (`editions/stamps.py`); the render hands the drawn city to the
template as its `city` skin, so the stamp art, the postmark and the dateline
agree. A brief with nothing to report (no asks, no events, nothing overnight)
spends no draw from either bag.
