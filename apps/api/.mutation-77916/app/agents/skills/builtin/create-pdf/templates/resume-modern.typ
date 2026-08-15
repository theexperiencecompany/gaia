// =============================================================================
// RESUME / CV — "Modern": bold, design-forward, SINGLE main column.
// =============================================================================
// Few-shot reference template, intentionally DISTINCT from the two-column
// `resume.typ`. Demonstrates: a full-width colored HEADER BAND (name + title +
// contact), a single main column, strong accent section dividers, a horizontal
// row of drawn "skill chips" (rounded `box`es), and a subtle TIMELINE RAIL down
// the experience entries (a drawn vertical line + node dots via `place`).
//
// Everything is native Typst: filled `block`s, `line`, `circle`, `rect`, and
// `place` overlays. No images, no @preview imports, bundled fonts only.
//
// Compile:  typst compile resume-modern.typ out.pdf
// Build:    bash scripts/build.sh main.typ out.pdf
//
// HOW TO ADAPT: edit the `#let` data at the top and the section bodies. The
// helpers handle all styling. Uses ONLY the bundled New Computer Modern face;
// the modern feel comes from layout, color, weight, and tracking — not a
// custom font — so it compiles identically in any headless Typst container.
// =============================================================================

// ---- Theme tokens ----------------------------------------------------------
#let accent   = rgb("#0d9488")          // teal brand color
#let accentdk = rgb("#0f766e")          // darker teal for the header band
#let accentlt = rgb("#ccfbf1")          // pale teal tint for chips
#let ink      = rgb("#1f2937")          // slate body text
#let muted    = rgb("#6b7280")          // secondary detail
#let rail     = rgb("#cbd5e1")          // timeline rail color

// ---- Candidate data --------------------------------------------------------
#let profile = (
  name:  "Maya Okonkwo",
  title: "Staff Software Engineer — Platform & Infrastructure",
  email: "maya.okonkwo@buildmail.dev",
  phone: "+1 (415) 555-0142",
  city:  "San Francisco, CA",
  site:  "mayaok.dev",
)

// Skills rendered as a horizontal row of drawn chips that wrap naturally.
#let skill_chips = (
  "Go", "Rust", "TypeScript", "Kubernetes", "Terraform", "PostgreSQL",
  "gRPC", "Kafka", "AWS", "Observability", "Distributed Systems", "CI/CD",
)

// ---- Page + base typography ------------------------------------------------
// Full-bleed page (header band must reach the edges); inner padding added per
// block below.
#set page(paper: "us-letter", margin: (x: 0pt, y: 0pt))
#set text(font: "New Computer Modern", size: 10pt, fill: ink, lang: "en")
#set par(leading: 0.6em, justify: false)
#set list(marker: text(fill: accent)[•], indent: 1pt, body-indent: 7pt, spacing: 0.5em)

// Horizontal page padding used by every non-banner block, so the body aligns
// with the header band's text inset.
#let pad = 2cm

// =============================================================================
// HELPERS
// =============================================================================

// Section header: bold accent title with a short heavy accent tick to its left
// and a thin full-width divider beneath — a strong, modern separator.
#let section(title) = {
  v(0.9em)
  grid(
    columns: (auto, 1fr),
    column-gutter: 8pt,
    align: (left + horizon, left + horizon),
    // Short thick accent tick.
    box(width: 16pt, height: 3pt, fill: accent, radius: 1.5pt),
    text(size: 12.5pt, weight: "bold", fill: accentdk, tracking: 0.6pt)[#upper(title)],
  )
  v(3pt)
  line(length: 100%, stroke: 0.8pt + rail)
  v(6pt)
}

// A single drawn skill chip — pale tinted rounded box with accent text.
#let chip(label) = box(
  fill: accentlt,
  inset: (x: 7pt, y: 3.5pt),
  radius: 5pt,
  outset: (y: 2.5pt),
)[#text(size: 8.5pt, weight: "medium", fill: accentdk)[#label]]

// Timeline experience entry. A vertical rail + a node dot are drawn with
// `place` overlays inside a left-padded container; the role/dates/org/body sit
// to the right of the rail. The rail line spans the full block height so
// stacked entries read as one continuous timeline.
#let timeline_entry(role, org, dates, body) = {
  // 14pt-wide rail gutter on the left; content indented past it.
  block(width: 100%, inset: (left: 18pt))[
    // Rail: a full-height vertical line near the left edge.
    #place(left + top, dx: -18pt, line(
      start: (5pt, 2pt),
      end: (5pt, 100%),
      stroke: 1.2pt + rail,
    ))
    // Node dot: a filled accent circle ringed in white, on the rail.
    #place(left + top, dx: -18pt + 5pt - 4pt, dy: 1pt,
      circle(radius: 4pt, fill: accent, stroke: 1.5pt + white))
    // ---- Entry content -------------------------------------------------
    #grid(
      columns: (1fr, auto),
      align: (left, right),
      column-gutter: 8pt,
      text(weight: "bold", size: 11pt)[#role],
      text(size: 9pt, fill: muted)[#dates],
    )
    #v(-1pt)
    #text(size: 9.5pt, fill: accent, style: "italic")[#org]
    #v(3pt)
    #body
  ]
  v(0.6em)
}

// =============================================================================
// HEADER — full-width colored band with name, title, and a contact row.
// Drawn as a filled `block` spanning the full page width (page margin is 0).
// =============================================================================
#block(
  width: 100%,
  fill: accentdk,
  inset: (x: pad, top: 1.5cm, bottom: 1.2cm),
)[
  #text(fill: white, size: 27pt, weight: "bold", tracking: 0.4pt)[#profile.name]
  #v(-4pt)
  #text(fill: accentlt, size: 12pt, weight: "medium", tracking: 1pt)[#upper(profile.title)]
  #v(8pt)
  // Contact row — " · " separators are plain text spacing, not symbol glyphs.
  #text(fill: white.transparentize(8%), size: 9pt)[
    #profile.email #h(8pt) | #h(8pt) #profile.phone #h(8pt) | #h(8pt) #profile.city #h(8pt) | #h(8pt) #profile.site
  ]
]

// Thin accent underline directly beneath the band for a layered, modern edge.
#block(width: 100%, height: 4pt, fill: accent)

// =============================================================================
// BODY — single main column with all content, padded inside `pad`.
// =============================================================================
#block(inset: (x: pad, top: 1cm, bottom: 1cm))[
  #section("Profile")
  Staff engineer focused on platform reliability and developer velocity. I build
  the systems other teams build on — service meshes, deployment pipelines, and
  observability tooling — and I care as much about the on-call experience as the
  feature set. Comfortable leading cross-team initiatives, writing the design
  doc, and shipping the first version myself.

  #section("Skills")
  // Horizontal chip row; chips flow and wrap with a small gap between each.
  #for s in skill_chips { chip(s); h(5pt) }

  #section("Experience")
  #timeline_entry(
    "Staff Software Engineer",
    "Northwind Cloud · San Francisco, CA",
    "2021 — Present",
  )[
    - Led the migration of 180+ services onto a unified Kubernetes platform,
      cutting median deploy time from 22 minutes to under 4.
    - Designed and shipped the company-wide observability stack (metrics, traces,
      logs), reducing mean-time-to-resolution on Sev-1 incidents by 40%.
    - Founded the platform guild; authored the golden-path templates now used by
      every new backend service.
  ]
  #timeline_entry(
    "Senior Software Engineer",
    "Harborline · Remote",
    "2018 — 2021",
  )[
    - Rebuilt the event-ingestion pipeline on Kafka to handle 2M events/sec at
      p99 latency under 50ms.
    - Introduced infrastructure-as-code with Terraform, eliminating manual
      console changes and a class of production drift incidents.
  ]
  #timeline_entry(
    "Software Engineer",
    "Tessellate Labs · Oakland, CA",
    "2015 — 2018",
  )[
    - Built core gRPC service framework and shared client libraries adopted
      across the backend organization.
    - Owned the CI/CD system end to end, scaling it from 30 to 400 daily builds.
  ]

  #section("Education")
  #timeline_entry(
    "B.S. Computer Science",
    "University of California, Berkeley",
    "2011 — 2015",
  )[
    - Concentration in distributed systems. Undergraduate research assistant in
      the systems lab; co-authored one workshop paper on consensus protocols.
  ]

  #section("Certifications")
  - Certified Kubernetes Administrator (CKA) — 2022.
  - AWS Certified Solutions Architect, Professional — 2020.
  - HashiCorp Certified: Terraform Associate — 2021.
]
