// RESUME / CV TEMPLATE — single column. Adapt #let values and the sections.
// Compile: bash scripts/build.sh main.typ out.pdf

#let name = "Alex Rivera"
#let role = "Senior Software Engineer"
#let contact = "alex@example.com · +1 555 0100 · San Francisco, CA · github.com/alexr"

#set page(paper: "a4", margin: (x: 2cm, y: 1.8cm))
#set text(font: "New Computer Modern", size: 10.5pt)
#set par(leading: 0.65em)

#let section(title) = {
  v(0.6em)
  text(size: 12pt, weight: "bold", fill: rgb("#1a4d8f"))[#upper(title)]
  line(length: 100%, stroke: 0.5pt + rgb("#1a4d8f"))
  v(0.2em)
}
#let entry(title, sub, date, body) = {
  grid(columns: (1fr, auto), [*#title*], align(right)[#text(fill: rgb("#777"))[#date]])
  text(style: "italic")[#sub]
  body
  v(0.4em)
}

#align(center)[
  #text(size: 20pt, weight: "bold")[#name] \
  #text(size: 11pt, fill: rgb("#555"))[#role] \
  #text(size: 9pt, fill: rgb("#777"))[#contact]
]

#section("Summary")
One or two lines summarizing experience and strengths.

#section("Experience")
#entry("Senior Software Engineer", "Acme Corp", "2022 — Present")[
  - Led X, achieving Y (quantified result).
  - Built Z used by N users.
]
#entry("Software Engineer", "Globex Inc.", "2019 — 2022")[
  - Shipped feature A; improved metric B by C%.
]

#section("Skills")
Python, TypeScript, React, PostgreSQL, Kubernetes, LangGraph.

#section("Education")
#entry("B.S. Computer Science", "State University", "2015 — 2019")[]
