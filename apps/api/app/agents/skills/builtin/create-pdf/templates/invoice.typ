// =============================================================================
// INVOICE — detailed itemized invoice with COMPUTED totals, native Typst only.
// =============================================================================
// Few-shot reference template. Demonstrates: drawn letterhead, metadata block,
// Bill-To / Ship-To columns, a styled line-items table driven by a `#let`
// array, computed subtotal/discount/tax/total via `.map` + `.sum`, a money
// formatting helper, and a totals panel + payment footer.
//
// Compile:  typst compile invoice.typ out.pdf
// Build:    bash scripts/build.sh main.typ out.pdf
//
// HOW TO ADAPT: edit the `#let` metadata + the `items` array. Totals recompute
// automatically. Uses ONLY bundled fonts (New Computer Modern) — no @preview
// imports, no external images. Graphics drawn with `rect` / `line` / `table`.
// =============================================================================

// ---- Theme tokens ----------------------------------------------------------
#let accent   = rgb("#0f766e")   // teal brand color
#let accentlt = rgb("#e6f4f1")   // light tint for the table header fill
#let muted    = rgb("#6b7280")
#let ink      = rgb("#1f2937")
#let hairline = 0.5pt + rgb("#d1d5db")

// ---- Seller (you) ----------------------------------------------------------
#let seller = (
  name:    "Lumen Creative Studio",
  tagline: "Brand · Web · Product Design",
  address: "78 Castro Street, San Francisco, CA 94114",
  email:   "billing@lumencreative.com",
  phone:   "+1 (415) 555-0188",
  taxid:   "EIN 84-2910037",
)

// ---- Invoice metadata ------------------------------------------------------
#let invoice = (
  number:    "INV-2026-0184",
  issued:    "May 02, 2026",
  due:       "June 01, 2026",   // net-30
  po:        "PO-44915",
  currency:  "$",
)

// ---- Bill-To / Ship-To -----------------------------------------------------
#let bill_to = (
  name:    "Harborline Coffee Co.",
  attn:    "Attn: Marcus Reyes, Marketing Director",
  address: "210 Pier Avenue, Santa Monica, CA 90405",
  email:   "ap@harborline.coffee",
)
#let ship_to = (
  name:    "Harborline Coffee Co. — Flagship Roastery",
  attn:    "Attn: Receiving Dock",
  address: "55 Industrial Way, Bldg C, Vernon, CA 90058",
)

// ---- Financial parameters --------------------------------------------------
#let discount_rate = 0.10   // 10% loyalty discount on subtotal
#let tax_rate      = 0.0875 // 8.75% sales tax, applied AFTER discount

// ---- Line items ------------------------------------------------------------
// Each row: (description, qty, unit_price). Amount = qty * unit_price.
// Add / remove rows here; every total below recomputes from this array.
#let items = (
  ("Brand identity system — logo, palette, type", 1,  4800.00),
  ("Packaging design — 4 SKU bag wraps",          4,   650.00),
  ("E-commerce site design (Figma, 18 screens)",  18,  140.00),
  ("Front-end build + CMS integration",           1,  6200.00),
  ("Photography art direction (half day)",        2,   900.00),
  ("Project management (retainer hours)",         12,  110.00),
)

// ---- Computed totals -------------------------------------------------------
// `.map` projects each tuple to its line amount; `.sum` folds them.
#let line_amount(it) = it.at(1) * it.at(2)
#let subtotal = items.map(line_amount).sum()
#let discount = subtotal * discount_rate
#let taxable  = subtotal - discount
#let tax      = taxable * tax_rate
#let total    = taxable + tax

// ---- Money helper ----------------------------------------------------------
// Formats a number as $ with a thousands separator and exactly 2 decimals.
// Built from primitives so it needs no external library.
#let money(n) = {
  let cents  = calc.round(n * 100)
  let whole  = calc.trunc(cents / 100)
  let frac   = calc.rem(cents, 100)
  // Group the integer part into comma-separated thousands.
  let digits = str(whole).clusters().rev()
  let grouped = ()
  for (i, d) in digits.enumerate() {
    if i > 0 and calc.rem(i, 3) == 0 { grouped.push(",") }
    grouped.push(d)
  }
  let int_str = grouped.rev().join()
  let frac_str = if frac < 10 { "0" + str(frac) } else { str(frac) }
  invoice.currency + int_str + "." + frac_str
}

// ---- Page + base typography ------------------------------------------------
#set page(
  paper: "us-letter",
  margin: (top: 2cm, bottom: 1.8cm, x: 2.2cm),
  footer: context [
    #line(length: 100%, stroke: hairline)
    #v(2pt)
    #set text(size: 8pt, fill: muted)
    #grid(
      columns: (1fr, auto),
      [#seller.name · #seller.taxid],
      [Page #counter(page).display() of #counter(page).final().first()],
    )
  ],
)
#set text(font: "New Computer Modern", size: 10.5pt, fill: ink)
#set par(leading: 0.62em)

// =============================================================================
// LETTERHEAD — drawn masthead with the big "INVOICE" wordmark on the right.
// =============================================================================
#grid(
  columns: (1fr, auto),
  align: (left + bottom, right + bottom),
  [
    #grid(
      columns: (auto, 1fr),
      gutter: 10pt,
      rect(width: 5pt, height: 34pt, fill: accent, radius: 1pt),
      [
        #text(size: 17pt, weight: "bold", fill: accent)[#seller.name]
        #v(-7pt)
        #text(size: 9pt, fill: muted, style: "italic")[#seller.tagline]
      ],
    )
  ],
  text(size: 30pt, weight: "bold", fill: accent, tracking: 1pt)[INVOICE],
)
#v(4pt)
#line(length: 100%, stroke: 1.4pt + accent)
#v(-7pt)
#line(length: 100%, stroke: hairline)
#v(2pt)
#text(size: 8.5pt, fill: muted)[
  #box[#seller.address] #h(1fr) #box[#seller.phone] #h(8pt) #box[#seller.email]
]

#v(1.4em)

// =============================================================================
// META BLOCK + ADDRESSES — invoice numbers on the right, parties on the left.
// =============================================================================
#grid(
  columns: (1fr, 1fr, auto),
  column-gutter: 16pt,
  // Bill To
  [
    #text(size: 8.5pt, weight: "bold", fill: accent, tracking: 0.5pt)[BILL TO]
    #v(2pt)
    #text(weight: "bold")[#bill_to.name] \
    #text(size: 9.5pt, fill: muted)[#bill_to.attn] \
    #text(size: 9.5pt)[#bill_to.address] \
    #text(size: 9.5pt, fill: muted)[#bill_to.email]
  ],
  // Ship To
  [
    #text(size: 8.5pt, weight: "bold", fill: accent, tracking: 0.5pt)[SHIP TO]
    #v(2pt)
    #text(weight: "bold")[#ship_to.name] \
    #text(size: 9.5pt, fill: muted)[#ship_to.attn] \
    #text(size: 9.5pt)[#ship_to.address]
  ],
  // Invoice metadata — a borderless two-column key/value table.
  [
    #table(
      columns: (auto, auto),
      stroke: none,
      inset: (x: 6pt, y: 2.5pt),
      align: (right, right),
      [#text(fill: muted)[Invoice #sym.numero]], [#text(weight: "bold")[#invoice.number]],
      [#text(fill: muted)[Issued]],              [#invoice.issued],
      [#text(fill: muted)[Due]],                 [#text(weight: "bold")[#invoice.due]],
      [#text(fill: muted)[PO #sym.numero]],      [#invoice.po],
    )
  ],
)

#v(1.4em)

// =============================================================================
// LINE-ITEMS TABLE — styled header fill, right-aligned numeric columns,
// zebra striping via a per-row fill function.
// =============================================================================
#table(
  columns: (1fr, auto, auto, auto),
  align: (left, center, right, right),
  inset: (x: 8pt, y: 7pt),
  stroke: none,
  // Zebra stripes: header row uses the accent tint; body rows alternate.
  fill: (_, row) => if row == 0 { accentlt } else if calc.even(row) { rgb("#f9fafb") },
  table.header(
    text(weight: "bold", fill: accent)[Description],
    text(weight: "bold", fill: accent)[Qty],
    text(weight: "bold", fill: accent)[Unit Price],
    text(weight: "bold", fill: accent)[Amount],
  ),
  // Spread the mapped rows into the table. `.flatten()` turns the array of
  // 4-tuples into a flat sequence of cells.
  ..items.map(it => (
    [#it.at(0)],
    [#it.at(1)],
    [#money(it.at(2))],
    [#money(line_amount(it))],
  )).flatten(),
)
#line(length: 100%, stroke: hairline)

#v(0.8em)

// =============================================================================
// TOTALS PANEL — right-aligned, with the grand total emphasized on an accent
// band. Notes sit on the left, balancing the layout.
// =============================================================================
#grid(
  columns: (1fr, auto),
  column-gutter: 24pt,
  // Notes / payment terms (left).
  [
    #text(size: 8.5pt, weight: "bold", fill: accent, tracking: 0.5pt)[PAYMENT TERMS]
    #v(3pt)
    #set text(size: 9pt, fill: muted)
    #set par(leading: 0.6em)
    Payment due within 30 days of the issue date (Net-30). \
    Wire: Pacific National Bank · Routing 121000358 · Acct 884901223 \
    Make checks payable to #seller.name. \
    A 1.5% monthly finance charge applies to overdue balances.
  ],
  // Totals (right). Fixed-width box so labels and figures align cleanly.
  box(width: 230pt)[
    #table(
      columns: (1fr, auto),
      stroke: none,
      inset: (x: 8pt, y: 4pt),
      align: (left, right),
      [Subtotal],                                              [#money(subtotal)],
      [Discount (#str(calc.round(discount_rate * 100))%)],     [#text(fill: rgb("#b91c1c"))[#sym.minus#money(discount)]],
      [Tax (#str(calc.round(tax_rate * 100, digits: 2))%)],    [#money(tax)],
    )
    #v(2pt)
    // Grand-total band, drawn with a filled rect behind the row.
    #block(
      fill: accent,
      inset: (x: 8pt, y: 7pt),
      radius: 3pt,
      width: 100%,
      grid(
        columns: (1fr, auto),
        align: (left + horizon, right + horizon),
        text(fill: white, weight: "bold", size: 11pt)[Total Due],
        text(fill: white, weight: "bold", size: 13pt)[#money(total)],
      ),
    )
  ],
)

#v(2em)

// =============================================================================
// FOOTER NOTE — thank-you line, centered.
// =============================================================================
#align(center)[
  #text(size: 9.5pt, fill: muted, style: "italic")[
    Thank you for partnering with #seller.name. We appreciate your business.
  ]
]
