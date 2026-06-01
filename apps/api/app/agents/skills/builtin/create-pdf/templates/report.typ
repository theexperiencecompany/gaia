// REPORT TEMPLATE — adapt the #let values and the body. Keep the structure.
// Compile: bash scripts/build.sh main.typ out.pdf

#let title = "Quarterly Business Review"
#let subtitle = "Q3 2026"
#let author = "Prepared by GAIA"

#set document(title: title, author: author)
#set page(paper: "a4", margin: 2.2cm, numbering: "1", number-align: center)
#set text(font: "New Computer Modern", size: 11pt, lang: "en")
#set par(justify: true, leading: 0.7em)
#set heading(numbering: "1.")
#show heading.where(level: 1): it => block(above: 1.4em, below: 0.8em)[#text(size: 15pt)[#it]]

// Title block
#align(center)[
  #text(size: 22pt, weight: "bold")[#title] \
  #v(2pt)
  #text(size: 12pt, fill: rgb("#555"))[#subtitle] \
  #v(2pt)
  #text(size: 10pt, fill: rgb("#888"))[#author · #datetime.today().display("[month repr:long] [day], [year]")]
]
#v(1.2em)

= Executive Summary
Replace this with a 2–4 sentence summary of the report's key message and outcome.

= Highlights
- First key result or takeaway.
- Second key result.
- Third key result.

= Performance
Narrative for this section goes here. Reference the table below as needed.

#figure(
  table(
    columns: (auto, 1fr, 1fr, 1fr),
    align: (left, right, right, right),
    stroke: 0.5pt + rgb("#ccc"),
    table.header([*Metric*], [*Q1*], [*Q2*], [*Q3*]),
    [Revenue], [\$1.0M], [\$1.2M], [\$1.5M],
    [Active users], [12.1k], [14.8k], [18.2k],
    [Churn], [3.2%], [2.9%], [2.4%],
  ),
  caption: [Key metrics by quarter.],
)

= Recommendations
+ First recommended action.
+ Second recommended action.

= Appendix
Supporting detail, methodology, or data notes.
