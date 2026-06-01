// =============================================================================
// BENCHMARK REPORT TEMPLATE — built-in Typst features ONLY (no @preview imports).
// Compiles offline with: typst compile report.typ out.pdf
// This file doubles as few-shot reference material: every feature is commented.
// Adapt the #let metadata block and the body content. Keep the structure.
// =============================================================================

// ---- 1. METADATA --------------------------------------------------------------
// `#let` binds a value to a name. Group all document metadata here so the body
// stays clean and a user (or LLM) edits one block instead of hunting through prose.
#let title = "The Resilience of Distributed Systems"
#let subtitle = "A Practical Survey of Fault-Tolerance Patterns"
#let authors = (
  // An array of dictionaries — each author has a name and an affiliation.
  (name: "Dr. Ada Lovelace", affiliation: "Institute for Reliable Computing"),
  (name: "Grace Hopper, PhD", affiliation: "Institute for Reliable Computing"),
)
#let date = datetime.today() // built-in datetime; formatted later via .display()
#let accent = rgb("#1f4e79") // a single accent colour reused throughout the doc

// ---- 2. GLOBAL SET RULES ------------------------------------------------------
// `#set` configures the default behaviour of an element for the rest of the scope.
#set document(title: title, author: authors.map(a => a.name)) // PDF metadata.
#set page(
  paper: "a4",
  margin: (top: 2.6cm, bottom: 2.6cm, x: 2.2cm),
  // Running header + footer are added later via a `#set page(...)` AFTER the
  // title page, so the title page itself stays clean (see section 4).
)
#set text(font: "New Computer Modern", size: 11pt, lang: "en") // bundled font.
#set par(justify: true, leading: 0.68em, first-line-indent: 1.2em) // justified body.
#set heading(numbering: "1.1") // multi-level numbering: 1, 1.1, 1.1.1 ...
#set list(marker: ([•], [◦], [‣])) // nested bullet markers per depth level.
#set enum(numbering: "1.a.i.") // nested ordered-list numbering scheme.
#set math.equation(numbering: "(1)") // auto-number block equations as (1), (2)...

// ---- 3. SHOW RULES (custom styling) -------------------------------------------
// `#show selector: it => ...` rewrites how matching elements render.
// Level-1 headings: accent colour, larger, with vertical breathing room.
#show heading.where(level: 1): it => block(above: 1.6em, below: 0.9em)[
  #text(size: 16pt, weight: "bold", fill: accent)[#it]
]
// Level-2 headings: smaller, dark, slightly muted accent.
#show heading.where(level: 2): it => block(above: 1.1em, below: 0.55em)[
  #text(size: 13pt, weight: "bold", fill: accent.darken(15%))[#it]
]
// Inline `raw` (code) gets a subtle tinted background and monospace font.
#show raw.where(block: false): it => box(
  fill: luma(240), inset: (x: 3pt, y: 0pt), outset: (y: 3pt), radius: 2pt,
)[#it]
// Links render in the accent colour so cross-references stand out.
#show link: it => text(fill: accent)[#it]

// ---- 4. TITLE PAGE ------------------------------------------------------------
// Everything below is content (no leading `#` needed for markup at the top level,
// but `#align`, `#text`, etc. are function calls so they keep the hash).
#align(center)[
  #v(3cm)
  #text(size: 26pt, weight: "bold", fill: accent)[#title]
  #v(6pt)
  #text(size: 14pt, style: "italic", fill: luma(90))[#subtitle]
  #v(1.4cm)

  // Loop over the authors array and print each name + affiliation.
  #for a in authors [
    #text(size: 12pt, weight: "medium")[#a.name] \
    #text(size: 10pt, fill: luma(110))[#a.affiliation] \
    #v(4pt)
  ]

  #v(0.6cm)
  // datetime.display() formats with a custom pattern string.
  #text(size: 11pt, fill: luma(110))[#date.display("[month repr:long] [day], [year]")]
]

#v(1.6cm)

// Abstract block: a bordered, padded box that visually separates the summary.
#block(
  width: 100%,
  inset: 14pt,
  radius: 4pt,
  fill: luma(245),
  stroke: 0.5pt + luma(200),
)[
  #align(center)[#text(weight: "bold", size: 11pt)[Abstract]]
  #v(4pt)
  // Justified abstract text. `par(justify:...)` already applies globally.
  Distributed systems trade the simplicity of a single machine for scale and
  availability, but inherit a hostile failure model: partial outages, network
  partitions, and clock skew. This report surveys the patterns practitioners use
  to keep such systems correct under failure — replication, consensus, retries
  with backoff, and circuit breaking — and quantifies their effect on observed
  availability across three representative workloads.
]

#pagebreak() // start the table of contents on a fresh page.

// ---- 5. RUNNING HEADER & FOOTER ----------------------------------------------
// Re-set the page AFTER the title page so headers/footers only appear from here on.
// The header shows the current section title via the heading state; the footer
// shows "Page N of M" using the page counter.
#set page(
  header: context {
    // `context` lets us read document state (here: the nearest level-1 heading).
    let elems = query(heading.where(level: 1).before(here()))
    let section = if elems.len() > 0 { elems.last().body } else { [Front Matter] }
    set text(size: 9pt, fill: luma(120))
    // grid splits the header into left (title) and right (section) cells.
    grid(columns: (1fr, auto), align: (left, right),
      emph(title),
      section,
    )
    v(-6pt)
    line(length: 100%, stroke: 0.4pt + luma(200)) // thin rule under the header.
  },
  footer: context {
    set text(size: 9pt, fill: luma(120))
    line(length: 100%, stroke: 0.4pt + luma(200))
    v(2pt)
    align(center)[
      // counter(page) reads current page; .final() reads the last page number.
      // We are already inside `context`, so state is directly readable here.
      Page #counter(page).display() of #counter(page).final().first()
    ]
  },
)
#counter(page).update(1) // restart numbering at the first body/TOC page.

// ---- 6. TABLE OF CONTENTS -----------------------------------------------------
#outline(title: [Table of Contents], indent: auto, depth: 2)

#pagebreak()

// ===============================  BODY  =======================================

= Introduction
A distributed system is one in which the failure of a computer you did not even
know existed can render your own computer unusable.#footnote[Attributed to Leslie
Lamport; widely quoted in the systems community.] The defining challenge is
*partial failure*: unlike a single process that either runs or crashes, a fleet
of nodes can be simultaneously alive, dead, slow, and lying.

This report is organised as follows. @sec-patterns surveys the core fault-tolerance
patterns. @sec-measurements presents measured availability across three workloads.
@sec-recommendations distills the findings into actionable guidance.

== Scope and Assumptions
We assume a *crash-recovery* failure model with an asynchronous network. We do
_not_ treat Byzantine faults, which require a fundamentally different and more
expensive class of protocol.

= Fault-Tolerance Patterns <sec-patterns>
The patterns below compose: a production system typically layers several of them.

== Replication
Replication keeps multiple copies of state so that the loss of any single copy is
survivable. The two dominant strategies are:

+ *Primary–backup* — one node accepts writes and streams them to followers.
  + Simple to reason about.
  + Failover requires leader election.
+ *Quorum-based* — reads and writes touch overlapping subsets of replicas.
  + No single point of failure for writes.
  + Requires $R + W > N$ for strong consistency (see @eq-quorum).

The quorum overlap condition guarantees that any read set intersects the most
recent write set:

$ R + W > N $ <eq-quorum>

where $N$ is the replica count, $W$ the write quorum, and $R$ the read quorum.
Inline math such as $R = N - W + 1$ sets the minimum read quorum for a given $W$.

== Consensus
Consensus protocols let a set of nodes agree on a single value despite failures.
The safety property is that no two correct nodes decide differently; the liveness
property is that some value is eventually decided. A common throughput model is:

$ T_"max" = (N) / (2 dot.c delta + epsilon) $

where $delta$ is the one-way network delay and $epsilon$ is per-message processing
overhead. Note the equation above is numbered automatically.

== Retries, Backoff, and Circuit Breaking
Naive retries amplify load during an outage — a phenomenon called a *retry storm*.
Exponential backoff with jitter spreads retries out:

```python
# Exponential backoff with full jitter. A fenced code block: monospace,
# preserved whitespace, no justification. The `show raw` rule does not touch
# block-level raw, so this renders with Typst's default code styling.
import random

def backoff_delay(attempt: int, base: float = 0.1, cap: float = 30.0) -> float:
    """Return a randomized delay (seconds) for the given retry attempt."""
    ceiling = min(cap, base * (2 ** attempt))
    return random.uniform(0, ceiling)  # full jitter over [0, ceiling]
```

A *circuit breaker* trips after a threshold of consecutive failures, short-circuiting
calls to a failing dependency so it can recover. The states are summarised below.

// ---- FIGURE 1: natively-drawn bar chart (rects + line, no packages) ----------
#figure(
  // We draw the chart by hand with primitives so it compiles with zero deps.
  // `box` gives a fixed canvas; `place` positions children with absolute coords;
  // `rect` draws each bar; `line` draws the baseline axis.
  box(width: 100%, height: 5.6cm)[
    // A small helper #let, scoped to this figure, computes bar geometry.
    #let data = (("svc-A", 0.92), ("svc-B", 0.74), ("svc-C", 0.99), ("svc-D", 0.61))
    #let chart-h = 4.2cm // drawable height above the baseline
    #let n = data.len()
    // Baseline axis drawn near the bottom of the canvas.
    #place(bottom + left, dx: 0pt, dy: -0.8cm,
      line(length: 100%, stroke: 0.8pt + luma(120)))
    // Each bar: width is a fraction of the canvas, height scales with the value.
    #for (i, entry) in data.enumerate() {
      let (label, value) = entry
      let bar-w = 14%
      let gap = (100% - n * bar-w) / (n + 1)
      let x = gap + i * (bar-w + gap)
      place(bottom + left, dx: x, dy: -0.8cm,
        rect(
          width: bar-w,
          height: chart-h * value,
          fill: accent.lighten((1 - value) * 55%), // taller bars = more saturated
          radius: (top: 2pt),
        ))
      // Value label above each bar.
      place(bottom + left, dx: x, dy: -0.8cm - chart-h * value - 12pt,
        box(width: bar-w)[#align(center)[#text(size: 8pt)[#calc.round(value * 100)%]]])
      // Category label below the baseline.
      place(bottom + left, dx: x, dy: 2pt,
        box(width: bar-w)[#align(center)[#text(size: 8pt, fill: luma(90))[#label]]])
    }
  ],
  caption: [Measured availability by service over the trailing 90-day window. Bars
    are drawn natively with `rect` primitives — no plotting package required.],
) <fig-bars>

The variation in @fig-bars motivates the per-service tuning discussed in
@sec-recommendations.

= Measurements <sec-measurements>
We instrumented three workloads and recorded request-level outcomes over 90 days.

== Raw Results
The first table uses a *striped* fill: a `fill` function returns a colour based on
the row index, producing alternating background bands for readability.

// ---- FIGURE 2: a table wrapped in a figure (so it gets a numbered caption) ----
#figure(
  table(
    columns: (auto, 1fr, 1fr, 1fr),
    align: (left, right, right, right),
    stroke: none, // no cell borders; the stripes provide visual separation.
    // `fill` is a function (col, row) -> color. Row 0 is the header.
    fill: (col, row) => if row == 0 { accent } else if calc.odd(row) { luma(244) },
    // Header cells: white bold text on the accent fill.
    table.header(
      text(fill: white, weight: "bold")[Workload],
      text(fill: white, weight: "bold")[Requests],
      text(fill: white, weight: "bold")[Errors],
      text(fill: white, weight: "bold")[Availability],
    ),
    [Checkout API], [4.2 M], [3,180], [99.92%],
    [Search],       [11.7 M], [9,940], [99.91%],
    [Recommendations], [2.1 M], [21,400], [98.98%],
    [Notifications], [880 k], [12,300], [98.60%],
  ),
  caption: [Request volume and observed availability per workload (striped rows).],
) <tab-results>

== Summary by Region
The second table demonstrates *merged header cells* via `table.cell(colspan: ...)`,
grouping two metrics under a single spanning header.

#figure(
  table(
    columns: 5,
    align: center + horizon,
    stroke: 0.6pt + luma(180),
    inset: 7pt,
    // First header row: a label column + two spanning group headers.
    table.cell(rowspan: 2, fill: luma(235))[*Region*],
    table.cell(colspan: 2, fill: luma(235))[*Latency (ms)*],
    table.cell(colspan: 2, fill: luma(235))[*Errors (per 10k)*],
    // Second header row: the sub-columns under each group.
    [*p50*], [*p99*], [*4xx*], [*5xx*],
    [us-east], [42], [180], [3.1], [0.8],
    [eu-west], [55], [240], [4.0], [1.2],
    [ap-south], [88], [410], [6.7], [2.9],
  ),
  caption: [Latency and error breakdown by region (merged group headers).],
) <tab-region>

= Discussion
Two qualitative observations stand out from @tab-results and @tab-region.

#quote(block: true, attribution: [Site Reliability Engineering, Google])[
  Hope is not a strategy. Reliability is the most fundamental feature of any
  system, because a system that is unavailable cannot perform its function.
]

The notifications workload — the least replicated — shows both the lowest
availability and the widest regional error spread. This is the expected signature
of insufficient redundancy.

// ---- CALLOUT / ADMONITION BOX -------------------------------------------------
// A reusable highlighted box drawn with `block`: a coloured left border (via a
// directional stroke), a tinted fill, and a bold lead-in label.
#block(
  width: 100%,
  fill: rgb("#fff7e6"),
  stroke: (left: 3pt + rgb("#e0a000")),
  inset: 12pt,
  radius: (right: 4pt),
)[
  #text(weight: "bold", fill: rgb("#9a6a00"))[⚠ Key takeaway] \
  #v(2pt)
  Redundancy is necessary but not sufficient: under-replicated tiers degrade first
  and loudest. Budget replication by *blast radius*, not by traffic volume.
]

= Recommendations <sec-recommendations>
Based on the measured data, we recommend the following, in priority order:

+ Raise the replication factor of the notifications tier to match checkout.
+ Add circuit breakers around the recommendations dependency to contain
  retry storms.
+ Introduce regional failover for `ap-south`, which carries the highest p99.

= Conclusion
Fault tolerance is a budget, not a binary. The patterns surveyed here let
engineers spend that budget deliberately — placing redundancy where partial
failure is most costly, and accepting graceful degradation everywhere else.

// ---- REFERENCES (manual numbered list — no bibliography package) -------------
= References
// A tight enumerated list styled as a numbered reference list. We override the
// enum numbering locally to bracketed form and remove the body indent.
#set enum(numbering: "[1]", indent: 0pt, body-indent: 0.6em)
#set par(first-line-indent: 0pt) // references read better without the indent.
+ Lamport, L. "Time, Clocks, and the Ordering of Events in a Distributed
  System." _Communications of the ACM_, 21(7), 1978.
+ Brewer, E. "Towards Robust Distributed Systems." _Proc. PODC_, 2000.
+ Ongaro, D. and Ousterhout, J. "In Search of an Understandable Consensus
  Algorithm (Raft)." _USENIX ATC_, 2014.
+ Beyer, B. et al. _Site Reliability Engineering_. O'Reilly Media, 2016.
