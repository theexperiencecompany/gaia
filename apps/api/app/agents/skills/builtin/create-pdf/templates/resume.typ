// =============================================================================
// RESUME / CV — modern two-column professional resume, native Typst only.
// =============================================================================
// Few-shot reference template. Demonstrates: a `grid` two-column layout (wide
// main column + accent sidebar), a reusable `section()` helper with an accent
// rule, an `experience()` entry helper with right-aligned dates + bullets,
// categorized skill "chips" drawn with `box`, and a drawn proficiency bar
// chart (rect-based) — all with no images and no @preview imports.
//
// Compile:  typst compile resume.typ out.pdf
// Build:    bash scripts/build.sh main.typ out.pdf
//
// HOW TO ADAPT: edit the `#let` data at the top and the section bodies. The
// helpers handle all styling. Uses ONLY bundled fonts (New Computer Modern).
// =============================================================================

// ---- Theme tokens ----------------------------------------------------------
#let accent   = rgb("#5b21b6")   // violet brand color
#let accentlt = rgb("#ede9fe")   // light tint for chips
#let sidebar  = rgb("#f5f3ff")   // sidebar background
#let muted    = rgb("#6b7280")
#let ink      = rgb("#27272a")
#let hairline = 0.6pt + rgb("#d4d4d8")

// ---- Candidate data --------------------------------------------------------
#let profile = (
  name:  "Priya Anand",
  title: "Senior Product Designer",
  email: "priya.anand@designmail.com",
  phone: "+1 (646) 555-0173",
  city:  "Brooklyn, NY",
  site:  "priyaanand.design",
  links: "linkedin.com/in/priyaanand · github.com/p-anand",
)

// Skills as (label, proficiency 0-1) — feeds the drawn bar chart in the sidebar.
#let skill_levels = (
  ("Product Design",     0.95),
  ("Design Systems",     0.90),
  ("Prototyping",        0.85),
  ("User Research",      0.75),
  ("Front-end (CSS/TS)", 0.65),
)

// Categorized skills rendered as chips.
#let skill_chips = (
  ("Tools",     ("Figma", "Framer", "Sketch", "Principle", "Storybook")),
  ("Methods",   ("Design Systems", "Journey Mapping", "A/B Testing", "Accessibility")),
  ("Technical", ("HTML", "CSS", "TypeScript", "React", "Tokens Studio")),
)

// ---- Page + base typography ------------------------------------------------
#set page(paper: "us-letter", margin: (x: 0pt, y: 0pt))  // full-bleed; inner pad below
#set text(font: "New Computer Modern", size: 10pt, fill: ink)
#set par(leading: 0.6em, justify: false)
// Tighten the default bullet list and recolor markers to the accent.
#set list(marker: text(fill: accent)[#sym.bullet], indent: 2pt, body-indent: 6pt, spacing: 0.55em)

// =============================================================================
// HELPERS
// =============================================================================

// Section header for the MAIN column: uppercase title + an accent underline.
#let section(title) = {
  v(0.7em)
  text(size: 11.5pt, weight: "bold", fill: accent, tracking: 0.8pt)[#upper(title)]
  v(2pt)
  line(length: 100%, stroke: 1pt + accent)
  v(4pt)
}

// Section header for the SIDEBAR (narrower, no full-width rule needed).
#let side_section(title) = {
  v(0.6em)
  text(size: 9.5pt, weight: "bold", fill: accent, tracking: 0.8pt)[#upper(title)]
  v(2pt)
  line(length: 100%, stroke: 0.8pt + accent.lighten(20%))
  v(4pt)
}

// Experience / education entry: role + right-aligned dates, italic org line,
// then a content block (typically a bullet list).
#let entry(role, org, dates, body) = {
  grid(
    columns: (1fr, auto),
    align: (left, right),
    text(weight: "bold", size: 10.5pt)[#role],
    text(size: 9pt, fill: muted)[#dates],
  )
  v(-2pt)
  text(size: 9.5pt, fill: accent, style: "italic")[#org]
  v(2pt)
  body
  v(0.5em)
}

// A single skill chip — rounded tinted box. Used inline within a category.
#let chip(label) = box(
  fill: accentlt,
  inset: (x: 6pt, y: 3pt),
  radius: 4pt,
  outset: (y: 2pt),
)[#text(size: 8.5pt, fill: accent)[#label]]

// A drawn proficiency bar: track (gray) + fill (accent) sized by `level`.
// `place` overlays the fill on top of the track inside a fixed-size box.
#let prof_bar(label, level) = {
  text(size: 8.5pt)[#label]
  v(1pt)
  box(width: 100%, height: 6pt)[
    #place(rect(width: 100%, height: 6pt, radius: 3pt, fill: rgb("#e4e4e7")))
    #place(rect(width: level * 100%, height: 6pt, radius: 3pt, fill: accent))
  ]
  v(5pt)
}

// =============================================================================
// SIDEBAR CONTENT (right column) — contact, skills chart, education, certs.
// Defined as a `#let` block so the grid below stays readable.
// =============================================================================
#let sidebar_content = [
  #side_section("Contact")
  #set text(size: 9pt)
  #stack(
    spacing: 5pt,
    [#text(fill: muted)[Email] \ #profile.email],
    [#text(fill: muted)[Phone] \ #profile.phone],
    [#text(fill: muted)[Location] \ #profile.city],
    [#text(fill: muted)[Portfolio] \ #profile.site],
    [#text(fill: muted)[Profiles] \ #profile.links],
  )

  #side_section("Proficiency")
  // Drawn bar chart — one bar per skill level.
  #for (label, level) in skill_levels {
    prof_bar(label, level)
  }

  #side_section("Education")
  #text(weight: "bold", size: 9.5pt)[M.S. Human-Computer Interaction] \
  #text(size: 9pt, fill: accent, style: "italic")[Carnegie Mellon University] \
  #text(size: 8.5pt, fill: muted)[2014 — 2016]
  #v(6pt)
  #text(weight: "bold", size: 9.5pt)[B.F.A. Graphic Design] \
  #text(size: 9pt, fill: accent, style: "italic")[Rhode Island School of Design] \
  #text(size: 8.5pt, fill: muted)[2010 — 2014]

  #side_section("Certifications")
  #set text(size: 9pt)
  #stack(
    spacing: 5pt,
    [Nielsen Norman UX Certification — 2023],
    [Google UX Design Professional — 2021],
    [WCAG 2.2 Accessibility Specialist — 2024],
  )
]

// =============================================================================
// HEADER — full-width accent band with name, title, and contact row.
// Drawn as a filled `block` spanning the page width.
// =============================================================================
#block(
  width: 100%,
  fill: accent,
  inset: (x: 2cm, top: 1.4cm, bottom: 1.1cm),
)[
  #text(fill: white, size: 26pt, weight: "bold", tracking: 0.5pt)[#profile.name]
  #v(-6pt)
  #text(fill: accentlt, size: 12.5pt, tracking: 1pt)[#upper(profile.title)]
  #v(6pt)
  #text(fill: white.transparentize(10%), size: 9pt)[
    #profile.email #h(10pt) #sym.bullet #h(10pt) #profile.phone #h(10pt) #sym.bullet #h(10pt) #profile.city #h(10pt) #sym.bullet #h(10pt) #profile.site
  ]
]

// =============================================================================
// BODY — two-column grid. Left = main content, right = tinted sidebar.
// The sidebar gets a background via a filled cell inset; the main column
// carries its own horizontal padding through the grid inset.
// =============================================================================
#grid(
  columns: (1fr, 6.2cm),
  // ---- MAIN COLUMN -------------------------------------------------------
  block(inset: (left: 2cm, right: 1cm, top: 1cm, bottom: 1cm))[
    #section("Summary")
    Senior product designer with over a decade of experience shaping consumer
    and enterprise products end to end — from research and information
    architecture through high-fidelity interaction design and design-system
    governance. I pair rigorous user research with a strong systems mindset,
    and I am happiest closing the gap between design intent and shipped code.

    #section("Experience")
    #entry(
      "Senior Product Designer",
      "Lyra Health · New York, NY",
      "2021 — Present",
    )[
      - Owned the redesign of the patient-onboarding flow, lifting completion
        from 61% to 84% and cutting support tickets by a third.
      - Established and now maintain the company-wide design system (120+
        components), adopted by six product squads and the marketing site.
      - Mentor three designers; introduced weekly critique and a research
        repository that shortened the discovery cycle by roughly two weeks.
    ]
    #entry(
      "Product Designer",
      "Brightwheel · Remote",
      "2017 — 2021",
    )[
      - Designed the parent-facing messaging product from zero to one, reaching
        400k monthly active users within the first year.
      - Ran a quarterly usability-testing program and translated findings into
        a prioritized, shared backlog with engineering and product.
    ]
    #entry(
      "UX Designer",
      "Tonal Studio (agency) · Brooklyn, NY",
      "2016 — 2017",
    )[
      - Delivered end-to-end design for eight client engagements across
        fintech, health, and e-commerce on tight agency timelines.
      - Built the studio's first shared component library, cutting handoff
        rework across projects by an estimated 25%.
    ]

    #section("Skills")
    // Categorized chips. For each category, lay the chips out inline with
    // small horizontal gaps; the paragraph wraps them naturally.
    #for (cat, skills) in skill_chips {
      text(size: 9pt, weight: "bold", fill: muted)[#cat]
      v(2pt)
      // Join chips with a thin space so they flow and wrap.
      for s in skills { chip(s); h(4pt) }
      v(7pt)
    }

    #section("Selected Projects")
    #entry(
      "Open-source Design Tokens Toolkit",
      "Maintainer · 2.1k GitHub stars",
      "2022 — Present",
    )[
      - Authored a token pipeline that syncs Figma variables to CSS, iOS, and
        Android outputs; used by several mid-size product teams.
    ]
    #entry(
      "Accessible Charting Components",
      "Contributor",
      "2023",
    )[
      - Built screen-reader-friendly chart primitives meeting WCAG 2.2 AA,
        contributed upstream to a popular React visualization library.
    ]
  ],
  // ---- SIDEBAR -----------------------------------------------------------
  // Tinted background spans the full column; content padded inside.
  block(
    fill: sidebar,
    width: 100%,
    height: 100%,
    inset: (x: 1cm, top: 1cm, bottom: 1cm),
  )[#sidebar_content],
)
