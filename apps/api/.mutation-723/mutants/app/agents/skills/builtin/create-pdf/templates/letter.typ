// =============================================================================
// BUSINESS LETTER — professional formal letter, built with native Typst only.
// =============================================================================
// Few-shot reference template. Demonstrates: drawn letterhead (no images),
// accent rules with `line`, structured `#let` metadata, recipient/sender
// blocks, subject line, multi-paragraph body, signature space, enclosures + cc.
//
// Compile:  typst compile letter.typ out.pdf
// Build:    bash scripts/build.sh main.typ out.pdf
//
// HOW TO ADAPT: edit the `#let` metadata blocks below and replace the body
// paragraphs. Everything else (layout, letterhead, spacing) is reusable as-is.
// Uses ONLY bundled fonts (New Computer Modern) — no @preview imports, no
// external images. Graphics are drawn with `line` / `place` / `rect`.
// =============================================================================

// ---- Theme tokens ----------------------------------------------------------
// Single source of truth for the brand color and the page accent. Change once.
#let accent = rgb("#1a3c6e")     // deep corporate blue
#let muted  = rgb("#6b7280")     // secondary / metadata gray
#let hairline = 0.5pt + rgb("#d1d5db")

// ---- Metadata --------------------------------------------------------------
// The sending company (drives the letterhead).
#let company = (
  name:    "Northbridge Capital Partners",
  tagline: "Strategic Advisory · Private Markets",
  address: "44 Wall Street, Suite 1900, New York, NY 10005",
  phone:   "+1 (212) 555-0142",
  email:   "advisory@northbridge.com",
  web:     "northbridge.com",
)

// The individual signing the letter.
#let sender = (
  name:  "Eleanor M. Whitfield",
  title: "Managing Director, Corporate Advisory",
)

// Who the letter is addressed to.
#let recipient = (
  name:    "Mr. Daniel R. Castellano",
  title:   "Chief Financial Officer",
  org:     "Meridian Logistics Group",
  address: "1200 Harbor Boulevard, Long Beach, CA 90802",
)

#let subject = "Engagement Proposal — Sell-Side Advisory for the Pacific Freight Division"
#let salutation = "Dear Mr. Castellano"
#let closing = "Sincerely"

// Date is generated at compile time. Replace with a string literal if you need
// a fixed date, e.g.  #let letter_date = "April 14, 2026".
#let letter_date = datetime.today().display("[month repr:long] [day], [year]")

// ---- Page + base typography ------------------------------------------------
#set page(
  paper: "us-letter",
  margin: (top: 2.2cm, bottom: 2cm, x: 2.4cm),
  // Drawn footer rule + company web address — appears on every page.
  footer: context [
    #line(length: 100%, stroke: hairline)
    #v(2pt)
    #set text(size: 8pt, fill: muted)
    #grid(
      columns: (1fr, auto),
      align: (left, right),
      [#company.name],
      [#company.web],
    )
  ],
)
#set text(font: "New Computer Modern", size: 11pt, fill: rgb("#1f2937"))
#set par(leading: 0.72em, justify: true, spacing: 1.1em)

// =============================================================================
// LETTERHEAD — drawn entirely with native primitives (no logo image).
// A left accent bar (rect) sits beside the company name; a full-width accent
// rule (line) closes the masthead.
// =============================================================================
#grid(
  columns: (auto, 1fr),
  gutter: 12pt,
  // Vertical accent bar standing in for a logo mark.
  rect(width: 5pt, height: 38pt, fill: accent, radius: 1pt),
  [
    #text(size: 19pt, weight: "bold", fill: accent, tracking: 0.3pt)[#company.name]
    #v(-6pt)
    #text(size: 9.5pt, fill: muted, style: "italic")[#company.tagline]
  ],
)
#v(4pt)
// Two-tone rule: a thick accent line with a thin hairline beneath it.
#line(length: 100%, stroke: 1.4pt + accent)
#v(-7pt)
#line(length: 100%, stroke: hairline)
#v(2pt)
// Contact strip under the masthead. `box` keeps each item on one logical unit.
#text(size: 8.5pt, fill: muted)[
  #box[#company.address] #h(1fr) #box[#company.phone] #h(8pt) #box[#company.email]
]

#v(1.6em)

// =============================================================================
// DATE — right-aligned, standard for formal business correspondence.
// =============================================================================
#align(right)[#text(fill: muted)[#letter_date]]

#v(1.2em)

// =============================================================================
// RECIPIENT (inside address) — block left-aligned.
// =============================================================================
#text(weight: "bold")[#recipient.name] \
#recipient.title \
#recipient.org \
#recipient.address

#v(1.4em)

// =============================================================================
// SUBJECT LINE — bold, set apart from the body for quick scanning.
// =============================================================================
#text(weight: "bold")[Re: #subject]

#v(1em)

// Salutation
#salutation,

#v(0.3em)

// =============================================================================
// BODY — three well-formed paragraphs. Justified, with paragraph spacing
// handled by `#set par(spacing: ...)` above (no manual #v between paragraphs).
// =============================================================================
Thank you for the productive discussion last week regarding the strategic
direction of Meridian Logistics Group. Following our conversation, I am
pleased to set out Northbridge Capital Partners' proposal to act as your
exclusive financial advisor on a potential divestiture of the Pacific Freight
Division. We believe the current market for asset-light logistics platforms is
exceptionally favorable, and that a well-orchestrated process could attract
both strategic acquirers and infrastructure-focused financial sponsors.

Our proposed engagement would proceed in three phases: a preparation phase to
assemble marketing materials and a data room, a marketing phase to approach a
curated list of qualified buyers under confidentiality, and a negotiation phase
to drive competitive tension toward the most favorable terms. Throughout, our
senior team — not junior staff — will lead every buyer interaction. We estimate
a total timeline of four to six months from mandate to signing, subject to
diligence findings and prevailing market conditions.

We would welcome the opportunity to present our credentials and a preliminary
valuation perspective to your board at its earliest convenience. I have enclosed
our standard engagement terms together with a summary of comparable transactions
we have led in the freight and logistics sector over the past thirty-six months.
Please do not hesitate to contact me directly should you have any questions in
the interim.

#v(0.6em)

// =============================================================================
// CLOSING + SIGNATURE — the blank vertical space is the wet-ink signature area.
// =============================================================================
#closing,

#v(2.6em)  // signature space — leave room for a handwritten signature

#text(weight: "bold")[#sender.name] \
#text(fill: muted)[#sender.title] \
#text(fill: muted)[#company.name]

#v(1.6em)
#line(length: 38%, stroke: hairline)
#v(0.4em)

// =============================================================================
// ENCLOSURES + CC — standard formal-letter notations.
// =============================================================================
#set par(spacing: 0.5em)
#text(size: 9.5pt)[
  *Enclosures:* Engagement Letter (draft); Comparable Transactions Summary \
  *cc:* Ms. Patricia Lao, General Counsel, Meridian Logistics Group
]
