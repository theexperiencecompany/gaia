// =============================================================================
// RESUME / CV — "Classic": clean, conservative, ATS-friendly SINGLE column.
// =============================================================================
// Few-shot reference template. Demonstrates a maximally compatible, printable
// resume: a centered name + a single contact line, plain horizontal rules under
// each section heading, traditional serif typography, right-aligned dates, and
// bullet achievements. No color blocks, no sidebar, no columns — the layout a
// law firm, bank, or applicant-tracking system parses without trouble.
//
// Compile:  typst compile resume-classic.typ out.pdf
// Build:    bash scripts/build.sh main.typ out.pdf
//
// HOW TO ADAPT: edit the `#let` data at the top and the section bodies. The
// `section()` / `entry()` helpers handle all styling. Uses ONLY bundled fonts
// (New Computer Modern, a serif face) and native primitives — no @preview
// imports, no external images.
// =============================================================================

// ---- Theme tokens ----------------------------------------------------------
// Deliberately monochrome: black ink + one neutral gray for de-emphasis. No
// accent color keeps it printer-safe and ATS-neutral.
#let ink      = rgb("#1a1a1a")         // near-black body text
#let muted    = rgb("#595959")         // dates, org lines, secondary detail
#let rule     = 0.6pt + rgb("#000000") // solid hairline under section heads

// ---- Candidate data --------------------------------------------------------
#let profile = (
  name:  "Jonathan R. Whitfield",
  title: "Corporate Counsel — Mergers & Acquisitions",
  // Single contact line keeps parsers happy; joined with " | " below.
  email: "j.whitfield@lexmail.com",
  phone: "+1 (212) 555-0188",
  city:  "New York, NY",
  bar:   "Admitted: NY & NJ",
)

// ---- Page + base typography ------------------------------------------------
// Generous, symmetric margins and a serif face for a traditional document feel.
#set page(paper: "us-letter", margin: (x: 1.9cm, top: 1.6cm, bottom: 1.6cm))
#set text(font: "New Computer Modern", size: 10.5pt, fill: ink, lang: "en")
#set par(leading: 0.62em, justify: true)
// Plain, square bullet markers in ink — no decorative color.
#set list(marker: text(fill: ink)[•], indent: 1pt, body-indent: 7pt, spacing: 0.5em)

// =============================================================================
// HELPERS
// =============================================================================

// Section header: small-caps-style uppercase title with letter spacing, then a
// full-width hairline rule. The rule is the only "graphic" in the document.
#let section(title) = {
  v(0.85em)
  text(size: 11pt, weight: "bold", tracking: 1.2pt)[#upper(title)]
  v(2.5pt)
  line(length: 100%, stroke: rule)
  v(5pt)
}

// Experience / education entry. Role (bold) sits opposite right-aligned dates;
// the organization + location line follows in muted italic, then the body
// (typically a bullet list of achievements).
#let entry(role, org, dates, body) = {
  grid(
    columns: (1fr, auto),
    align: (left, right),
    column-gutter: 8pt,
    text(weight: "bold", size: 10.5pt)[#role],
    text(size: 9.5pt, fill: muted)[#dates],
  )
  v(-1pt)
  text(size: 9.5pt, fill: muted, style: "italic")[#org]
  v(2.5pt)
  body
  v(0.55em)
}

// Compact two-column skill row: a bold category label, then a comma-joined list
// of skills. Kept text-only so applicant-tracking systems read every keyword.
#let skill_row(label, items) = {
  grid(
    columns: (3.4cm, 1fr),
    column-gutter: 6pt,
    text(weight: "bold", size: 10pt)[#label],
    text(size: 10pt)[#items.join(", ")],
  )
  v(3.5pt)
}

// =============================================================================
// HEADER — centered name, title, and a single contact line.
// =============================================================================
#align(center)[
  #text(size: 22pt, weight: "bold", tracking: 0.4pt)[#profile.name]
  #v(2pt)
  #text(size: 11pt, fill: muted, style: "italic")[#profile.title]
  #v(4pt)
  // One contact line; " | " separators are plain text (no Unicode symbols).
  #text(size: 9.5pt, fill: muted)[
    #profile.email #h(6pt) | #h(6pt) #profile.phone #h(6pt) | #h(6pt) #profile.city #h(6pt) | #h(6pt) #profile.bar
  ]
]
#v(2pt)

// =============================================================================
// BODY — one flowing column of standard resume sections.
// =============================================================================

#section("Professional Summary")
Corporate attorney with over twelve years advising public and private companies
on mergers, acquisitions, and corporate governance. Lead counsel on transactions
exceeding \$4 billion in aggregate value, with a practice spanning negotiation,
due diligence, regulatory clearance, and post-closing integration. Known for
clear written work product, disciplined deal management, and steady judgment
under deadline pressure.

#section("Experience")
#entry(
  "Corporate Counsel, M&A",
  "Hartwell & Crane LLP — New York, NY",
  "2018 — Present",
)[
  - Served as lead counsel on twenty-three public- and private-company
    acquisitions, including a \$1.2 billion cross-border merger cleared by both
    U.S. and EU antitrust regulators.
  - Drafted and negotiated stock and asset purchase agreements, shareholder
    arrangements, and disclosure schedules across technology and healthcare.
  - Managed diligence teams of up to nine associates, standardizing the firm's
    diligence checklist and cutting average review time by roughly 20%.
]
#entry(
  "Associate, Corporate Group",
  "Merrick, Stone & Doyle — New York, NY",
  "2013 — 2018",
)[
  - Supported deal teams on financings, joint ventures, and securities
    filings, preparing board materials and closing documentation.
  - Authored memoranda on fiduciary-duty and disclosure questions relied upon
    by partners in active negotiations.
]
#entry(
  "Judicial Clerk",
  "Hon. Eleanor V. Pace, U.S. District Court, S.D.N.Y.",
  "2012 — 2013",
)[
  - Researched and drafted opinions on commercial and contract disputes;
    managed the chambers motion calendar.
]

#section("Education")
#entry(
  "Juris Doctor, cum laude",
  "Columbia Law School — New York, NY",
  "2012",
)[
  - Notes Editor, Columbia Business Law Review. Harlan Fiske Stone Scholar.
]
#entry(
  "Bachelor of Arts, Economics",
  "Georgetown University — Washington, DC",
  "2009",
)[
  - Graduated magna cum laude; Phi Beta Kappa.
]

#section("Skills")
#skill_row("Practice Areas", ("Mergers & Acquisitions", "Corporate Governance", "Securities", "Joint Ventures"))
#skill_row("Transactional", ("Due Diligence", "Contract Drafting", "Negotiation", "Disclosure Schedules"))
#skill_row("Languages", ("English (native)", "French (professional)", "Spanish (conversational)"))

#section("Certifications & Admissions")
- Admitted to the Bar of the State of New York (2012) and New Jersey (2013).
- Certified Information Privacy Professional (CIPP/US), IAPP — 2021.
- Member, American Bar Association, Business Law Section.
