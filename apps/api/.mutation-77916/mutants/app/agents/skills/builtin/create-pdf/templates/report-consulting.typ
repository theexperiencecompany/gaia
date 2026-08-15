// =============================================================================
// BENCHMARK CONSULTING REPORT TEMPLATE — built-in Typst features ONLY.
// NO @preview package imports. Bundled fonts only. NO external image/font files.
// All graphics are drawn with native primitives (rect / line / grid / table / place).
// Compiles offline with: typst compile report-consulting.typ out.pdf
//
// AESTHETIC: a sleek management-consulting / strategy deliverable. Distinct from
// the academic `report.typ` (no abstract, no footnotes, no references). Instead:
// bold colour-band cover, executive-summary callout, KPI metric cards, modern
// numbered section kickers, a drawn column chart, two-column findings, a styled
// data table, recommendation cards, and a next-steps box.
//
// This file doubles as few-shot reference material — every feature is commented.
// To reuse: edit the #let metadata + the body content; keep the structure.
// =============================================================================

// ---- 1. METADATA --------------------------------------------------------------
// Group all document metadata in one #let block so the body stays clean and an
// LLM (or user) edits one place instead of hunting through prose.
#let title = "Operational Efficiency Review"
#let subtitle = "Cost-to-Serve Optimization & Growth Levers"
#let client = "Northwind Logistics, Inc."
#let engagement = "Strategy Engagement \u{2014} Phase II"
#let date = datetime.today() // built-in datetime; formatted later via .display()

// A small brand palette reused everywhere. Keeping colours named (not inline) is
// the single source of truth — change the brand here and the whole doc updates.
#let brand = rgb("#0b3d5c") // deep slate-teal — primary band + headings
#let brand-accent = rgb("#16a8a3") // bright teal — kickers, bars, highlights
#let ink = rgb("#1a2230") // near-black body text
#let muted = rgb("#6b7480") // secondary / caption grey
#let hairline = rgb("#d9dee4") // light rule colour
#let soft = rgb("#f2f5f8") // soft fill for cards / zebra rows

// ---- 2. GLOBAL SET RULES ------------------------------------------------------
// `#set` configures the default behaviour of an element for the rest of the scope.
#set document(title: title, author: client)
#set page(paper: "a4", margin: (top: 2.4cm, bottom: 2.4cm, x: 2cm))
#set text(font: "Libertinus Sans", size: 10.5pt, fill: ink, lang: "en")
// Consulting decks read as left-aligned (ragged-right), not justified academic prose.
#set par(justify: false, leading: 0.72em, spacing: 1.0em)
#set heading(numbering: none) // we render our own modern numbered kickers instead.

// ---- 3. REUSABLE COMPONENT HELPERS --------------------------------------------
// Components are #let functions returning content. Defining them once keeps the
// body declarative — the body says WHAT, these helpers say HOW.

// A modern section heading: a coloured "kicker" number chip + the title text,
// underlined by a thin brand rule. `counter` auto-increments across calls.
#let section-counter = counter("section")
#let section(title) = {
  section-counter.step()
  block(above: 1.6em, below: 0.8em)[
    #grid(
      columns: (auto, 1fr),
      column-gutter: 10pt,
      align: (horizon, horizon),
      // The number chip: a filled rect with the section index centred inside.
      box(fill: brand-accent, radius: 4pt, inset: (x: 7pt, y: 4pt))[
        #text(fill: white, weight: "bold", size: 11pt)[
          #context section-counter.display("01")
        ]
      ],
      text(fill: brand, weight: "bold", size: 15pt)[#title],
    )
    #v(4pt)
    #line(length: 100%, stroke: 0.8pt + hairline)
  ]
}

// A KPI / metric card: big number on top, small label below, on a soft fill.
// `delta` is an optional up/down change rendered as a coloured chip (drawn, not
// a Unicode arrow — we use a tiny triangle polygon so it works in any viewer).
#let kpi-card(value, label, delta: none, up: true) = {
  box(width: 100%, fill: soft, radius: 8pt, inset: 12pt)[
    #text(size: 22pt, weight: "bold", fill: brand)[#value]
    #if delta != none [
      #h(5pt)
      #let dc = if up { rgb("#1c8c4a") } else { rgb("#c23b3b") }
      // Tiny triangle drawn with polygon — direction flips with `up`.
      // Vertices are spread (`..`) into positional args; each is a 2D point.
      #let pts = if up { ((0pt, 5pt), (5pt, 5pt), (2.5pt, 0pt)) } else { ((0pt, 0pt), (5pt, 0pt), (2.5pt, 5pt)) }
      #box(baseline: 1pt)[#polygon(fill: dc, ..pts)]
      #text(size: 9pt, weight: "bold", fill: dc)[#delta]
    ]
    #v(2pt)
    #text(size: 9pt, fill: muted)[#label]
  ]
}

// A generic callout box with a coloured left border, tinted fill, and a label.
#let callout(label, body, accent: brand-accent, tint: soft) = {
  block(
    width: 100%,
    fill: tint,
    stroke: (left: 3pt + accent),
    inset: 14pt,
    radius: (right: 6pt),
  )[
    #text(weight: "bold", fill: accent, size: 10pt, tracking: 0.5pt)[#upper(label)]
    #v(4pt)
    #body
  ]
}

// A numbered recommendation card: a big index numeral beside a titled body.
#let rec-card(index, head, body) = {
  block(width: 100%, fill: soft, radius: 8pt, inset: 13pt, below: 8pt)[
    #grid(
      columns: (auto, 1fr),
      column-gutter: 12pt,
      align: (top, top),
      text(size: 26pt, weight: "bold", fill: brand-accent)[#index],
      [
        #text(weight: "bold", size: 11pt, fill: brand)[#head] \
        #v(2pt)
        #text(fill: ink)[#body]
      ],
    )
  ]
}

// ---- 4. COVER -----------------------------------------------------------------
// A full-bleed coloured band at the top. We pull it to the page edges with a
// negative-margin `place` trick: place at top-left, offset by the page margin,
// and size it to the full paper width so the band ignores the text margins.
#place(
  top + left,
  dx: -2cm, dy: -2.4cm, // cancel the page margins to reach the physical edges
  rect(width: 100% + 4cm, height: 9.5cm, fill: brand),
)
// A thin accent stripe sitting just under the band for a layered, branded look.
#place(top + left, dx: -2cm, dy: -2.4cm + 9.5cm, rect(width: 100% + 4cm, height: 5mm, fill: brand-accent))

// Cover text, PINNED inside the band with `place` so it can NEVER depend on
// flowed v()-stack height. (A flowed stack can spill the white-on-teal text
// just below the band edge, where white text becomes invisible on the white
// page.) `place` is floating — it doesn't consume layout space — so we reserve
// the band's height with a single #v() afterwards.
// Headline block, pinned near the TOP of the band.
#place(top + left, dy: 1.5cm, block(width: 100%)[
  #text(size: 9pt, fill: brand-accent, weight: "bold", tracking: 2pt)[#upper(engagement)]
  #v(10pt)
  #text(size: 30pt, weight: "bold", fill: white)[#title]
  #v(6pt)
  #text(size: 14pt, fill: rgb("#cfe6e6"))[#subtitle]
])

// Client + date row, pinned at a FIXED dy near the band BOTTOM — independent of
// the headline's height, so the white-on-teal text always lands inside the 9.5cm
// band (the band bottom is at text-area dy 7.1cm = 9.5cm - 2.4cm top margin).
#place(top + left, dy: 5.7cm, grid(
  columns: (auto, auto, auto),
  column-gutter: 16pt,
  align: (bottom, bottom, bottom),
  [
    #text(size: 8pt, fill: brand-accent, tracking: 1pt)[#upper("Prepared for")] \
    #text(size: 12pt, fill: white, weight: "medium")[#client]
  ],
  line(start: (0pt, 0pt), end: (0pt, 26pt), stroke: 0.6pt + rgb("#3f6f86")),
  [
    #text(size: 8pt, fill: brand-accent, tracking: 1pt)[#upper("Date")] \
    #text(size: 12pt, fill: white, weight: "medium")[#date.display("[month repr:long] [day], [year]")]
  ],
))

// Reserve the band (9.5cm) + accent strip (5mm) + a gap, so the body starts below.
#v(9.5cm + 5mm + 8mm)

// ---- 5. EXECUTIVE SUMMARY -----------------------------------------------------
// First thing after the cover, as in a real deliverable: the one-paragraph
// "what you need to know". Uses the callout helper with a brand tint.
#callout("Executive Summary")[
  Northwind's cost-to-serve has risen 14% over four quarters while volume grew only
  6%, compressing operating margin. The drivers are concentrated: last-mile routing
  inefficiency, an over-provisioned warehouse footprint in the Midwest, and manual
  exception handling that scales linearly with order volume. Addressing the top
  three levers below recovers an estimated 320 bps of margin within two quarters,
  with no reduction in service-level commitments.
]

#v(8pt)

// ---- 6. KPI / METRIC CARD ROW -------------------------------------------------
// A row of drawn metric cards via `grid`. Each cell is a kpi-card component.
#grid(
  columns: (1fr, 1fr, 1fr, 1fr),
  column-gutter: 10pt,
  // NOTE: inside a STRING literal a "$" is just a character — do NOT write "\$"
  // (backslash-dollar is not a string escape and renders the backslash). The
  // "\$" escape is only for markup/content (see the body prose below).
  kpi-card("$48.2M", "Annual cost-to-serve", delta: "14%", up: false),
  kpi-card("320 bps", "Recoverable margin", delta: "Target", up: true),
  kpi-card("17.4%", "Empty-mile ratio", delta: "5.1 pts", up: false),
  kpi-card("2 Q", "Time to value", delta: "On track", up: true),
)

#v(4pt)
#align(center)[#text(size: 8pt, fill: muted)[Figures reflect trailing-twelve-month actuals; deltas are year-over-year unless noted.]]

#pagebreak()

// ---- 7. RUNNING FOOTER --------------------------------------------------------
// Re-set the page AFTER the cover so the footer only appears on body pages. The
// footer carries the brand, a confidentiality note, and "Page N / M".
#set page(
  footer: context {
    line(length: 100%, stroke: 0.6pt + hairline)
    v(3pt)
    set text(size: 8pt, fill: muted)
    grid(
      columns: (1fr, auto, 1fr),
      align: (left, center, right),
      text(weight: "bold", fill: brand)[#client],
      [Confidential],
      // counter(page) reads the current page; .final() reads the last page.
      [Page #counter(page).display() / #counter(page).final().first()],
    )
  },
)
#counter(page).update(1) // restart numbering on the first body page.

// ===============================  BODY  =======================================

#section[Situation & Context]
The logistics network has scaled faster than its operating model. What worked at
\$60,000 daily orders now strains at \$95,000: routing heuristics were tuned for a
denser urban mix, the warehouse network was sized for a pre-expansion demand map,
and exception handling remains a manual desk. The result is margin erosion that is
*structural, not cyclical* — it will not self-correct as volume normalizes.

Three questions framed this engagement:

+ Where is cost-to-serve concentrated, and is it volume-driven or process-driven?
+ Which levers move margin fastest without degrading the service promise?
+ What sequencing minimizes disruption to live operations?

#section[Key Findings]
The diagnostic surfaced a clear hierarchy of cost drivers. The chart below ranks
the incremental cost contribution of each driver over the review period.

// ---- FIGURE 1: natively-drawn column chart (rects + baseline, no packages) ----
#figure(
  box(width: 100%, height: 6.0cm)[
    // Per-figure scoped data + geometry helpers. Each tuple is (label, value 0..1).
    #let data = (
      ("Last-mile", 1.00),
      ("Warehouse", 0.72),
      ("Exceptions", 0.58),
      ("Returns", 0.41),
      ("Packaging", 0.23),
    )
    #let chart-h = 4.4cm // drawable bar height above the baseline
    #let base = 1.0cm // baseline distance from the canvas bottom
    #let n = data.len()
    // Light horizontal gridlines at 25 / 50 / 75 / 100% for a charted feel.
    #for frac in (0.25, 0.5, 0.75, 1.0) {
      place(bottom + left, dy: -base - chart-h * frac,
        line(length: 100%, stroke: 0.4pt + hairline))
    }
    // The baseline axis.
    #place(bottom + left, dy: -base, line(length: 100%, stroke: 1pt + brand))
    // Draw each column, its value label above, and its category label below.
    #for (i, entry) in data.enumerate() {
      let (label, value) = entry
      let bar-w = 12%
      let gap = (100% - n * bar-w) / (n + 1)
      let x = gap + i * (bar-w + gap)
      // Tallest driver gets the bright accent; the rest the brand colour.
      let fill-col = if value == 1.0 { brand-accent } else { brand }
      place(bottom + left, dx: x, dy: -base,
        rect(width: bar-w, height: chart-h * value, fill: fill-col, radius: (top: 3pt)))
      // Value label (relative index, 100 = top driver) above each column.
      place(bottom + left, dx: x, dy: -base - chart-h * value - 14pt,
        box(width: bar-w)[#align(center)[#text(size: 8.5pt, weight: "bold", fill: ink)[#calc.round(value * 100)]]])
      // Category label below the baseline (allows the "\n" line break).
      place(bottom + left, dx: x, dy: -base + 4pt,
        box(width: bar-w)[#align(center)[#text(size: 7.5pt, fill: muted)[#label]]])
    }
  ],
  caption: [Relative cost-driver contribution (top driver indexed to 100). Columns
    are drawn natively with `rect` primitives — no plotting package required.],
)

#v(6pt)

// ---- 8. TWO-COLUMN FINDINGS / IMPLICATIONS via grid ---------------------------
// A classic consulting "so-what" split: the observation on the left, the business
// implication on the right. `grid` gives two equal columns with a divider line.
#grid(
  columns: (1fr, 1fr),
  column-gutter: 18pt,
  [
    #text(weight: "bold", fill: brand, size: 11pt)[Findings]
    #v(4pt)
    - Empty-mile ratio of *17.4%* is 6 points above the sector benchmark.
    - Midwest warehouse utilization sits at *54%* against a *78%* target.
    - *31%* of orders touch the manual exception desk at least once.
    - Returns are processed an average of *4.2 days* after receipt.
  ],
  [
    #text(weight: "bold", fill: brand-accent, size: 11pt)[Implications]
    #v(4pt)
    - Dynamic routing alone recovers ~140 bps with existing fleet capacity.
    - Consolidating two Midwest sites avoids a planned *\$3.1M* lease renewal.
    - Automating the top five exception types frees *9 FTE* of desk effort.
    - Same-day returns triage lifts resale recovery value by an estimated *11%*.
  ],
)

#section[Quantified Opportunity]
The table below sizes each lever by margin impact, implementation effort, and
time-to-value. It uses a brand header fill and zebra striping for readability.

// ---- FIGURE 2: styled data table — header fill + zebra rows -------------------
#figure(
  table(
    columns: (2.2fr, 1fr, 1fr, 1fr),
    align: (left, center, center, center),
    inset: 8pt,
    stroke: none, // borderless; the header fill + zebra bands carry structure.
    // `fill` is a function (col, row) -> color. Row 0 is the header row.
    fill: (col, row) => if row == 0 { brand } else if calc.odd(row) { soft } else { white },
    table.header(
      text(fill: white, weight: "bold")[Lever],
      text(fill: white, weight: "bold")[Margin (bps)],
      text(fill: white, weight: "bold")[Effort],
      text(fill: white, weight: "bold")[Time],
    ),
    [Dynamic last-mile routing], [140], [Medium], [1 Q],
    [Midwest warehouse consolidation], [95], [High], [2 Q],
    [Exception automation], [55], [Medium], [1 Q],
    [Returns triage redesign], [30], [Low], [1 Q],
    // A bold "total" row, distinguished by a stronger fill via a full-row cell set.
    table.cell(fill: brand-accent)[#text(fill: white, weight: "bold")[Total]],
    table.cell(fill: brand-accent)[#text(fill: white, weight: "bold")[320]],
    table.cell(fill: brand-accent)[#text(fill: white, weight: "bold")[\u{2014}]],
    table.cell(fill: brand-accent)[#text(fill: white, weight: "bold")[2 Q]],
  ),
  caption: [Margin opportunity by lever, with relative effort and time-to-value.],
)

#section[Recommendations]
We recommend executing the levers in the sequence below — front-loading the
high-confidence, low-disruption wins to fund the structural changes that follow.

#rec-card("1", "Deploy dynamic last-mile routing")[
  Replace the static zone heuristic with a daily re-optimization run against live
  demand and traffic. Highest margin-per-effort lever; no capital required and no
  change to the customer-facing promise.
]
#rec-card("2", "Consolidate the Midwest warehouse footprint")[
  Collapse two under-utilized sites into one before the lease renewal window.
  Sequenced second so routing gains are realized before network changes land.
]
#rec-card("3", "Automate the top exception types")[
  Build deterministic handlers for the five exception categories that account for
  72% of desk volume, redeploying freed capacity to proactive service recovery.
]

// ---- 9. CLOSING / NEXT-STEPS BOX ----------------------------------------------
// A distinct closing callout in the deep brand fill (inverted: white text) to
// visually signal "this is the action ask", not just another body paragraph.
#v(6pt)
#block(
  width: 100%,
  fill: brand,
  radius: 8pt,
  inset: 16pt,
)[
  #text(weight: "bold", fill: brand-accent, size: 10pt, tracking: 1pt)[#upper("Next Steps")]
  #v(6pt)
  #set text(fill: white)
  #grid(
    columns: (auto, 1fr),
    row-gutter: 7pt,
    column-gutter: 12pt,
    align: (horizon, horizon),
    box(fill: brand-accent, radius: 3pt, inset: (x: 6pt, y: 2pt))[#text(fill: white, weight: "bold", size: 9pt)[WK 1\u{2013}2]],
    [Stand up the routing pilot on two metro lanes; baseline empty-mile metrics.],
    box(fill: brand-accent, radius: 3pt, inset: (x: 6pt, y: 2pt))[#text(fill: white, weight: "bold", size: 9pt)[WK 3\u{2013}6]],
    [Confirm Midwest consolidation business case; begin exception-handler build.],
    box(fill: brand-accent, radius: 3pt, inset: (x: 6pt, y: 2pt))[#text(fill: white, weight: "bold", size: 9pt)[WK 7+]],
    [Scale routing network-wide; execute consolidation ahead of the lease window.],
  )
]
