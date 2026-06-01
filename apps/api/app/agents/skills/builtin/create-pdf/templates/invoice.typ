// INVOICE TEMPLATE — itemized invoice with auto totals. Edit #let values + items.
// Compile: bash scripts/build.sh main.typ out.pdf

#let from = (name: "Acme Studio", address: "123 Market St, SF, CA 94103", email: "billing@acme.com")
#let to = (name: "Globex Inc.", address: "500 Industrial Ave, Austin, TX 78701")
#let invoice_no = "INV-2026-0042"
#let tax_rate = 0.0  // e.g. 0.08 for 8%
#let currency = "$"

// Each item: (description, quantity, unit_price)
#let items = (
  ("Design services", 20, 120.0),
  ("Front-end development", 35, 140.0),
  ("Project management", 8, 100.0),
)

#let subtotal = items.map(it => it.at(1) * it.at(2)).sum()
#let tax = subtotal * tax_rate
#let total = subtotal + tax
#let money(n) = currency + str(calc.round(n, digits: 2))

#set page(paper: "a4", margin: 2.2cm)
#set text(font: "New Computer Modern", size: 11pt)

#grid(columns: (1fr, 1fr),
  [#text(size: 20pt, weight: "bold")[INVOICE] \ #text(fill: rgb("#888"))[#invoice_no]],
  align(right)[Date: #datetime.today().display("[year]-[month]-[day]")],
)
#v(1em)

#grid(columns: (1fr, 1fr), gutter: 1em,
  [*From* \ #from.name \ #from.address \ #from.email],
  [*Bill to* \ #to.name \ #to.address],
)
#v(1.2em)

#table(
  columns: (1fr, auto, auto, auto),
  align: (left, right, right, right),
  stroke: 0.5pt + rgb("#ccc"),
  table.header([*Description*], [*Qty*], [*Unit*], [*Amount*]),
  ..items.map(it => (
    [#it.at(0)], [#it.at(1)], [#money(it.at(2))], [#money(it.at(1) * it.at(2))],
  )).flatten(),
)
#v(0.6em)

#align(right)[
  #table(columns: (auto, auto), stroke: none, align: (right, right),
    [Subtotal:], [#money(subtotal)],
    [Tax (#str(calc.round(tax_rate * 100, digits: 2))%):], [#money(tax)],
    [*Total:*], [*#money(total)*],
  )
]
#v(1.5em)
#text(fill: rgb("#888"), size: 9pt)[Thank you for your business. Payment due within 30 days.]
