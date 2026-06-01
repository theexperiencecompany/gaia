// LETTER TEMPLATE — formal/business letter. Adapt the #let values and body.
// Compile: bash scripts/build.sh main.typ out.pdf

#let sender = (
  name: "Jane Doe",
  title: "Head of Operations",
  org: "Acme Corp",
  address: "123 Market St, San Francisco, CA 94103",
  email: "jane@acme.com",
)
#let recipient = (
  name: "Mr. John Smith",
  org: "Globex Inc.",
  address: "500 Industrial Ave, Austin, TX 78701",
)
#let subject = "Re: Partnership proposal"

#set page(paper: "a4", margin: 2.5cm)
#set text(font: "New Computer Modern", size: 11pt)
#set par(leading: 0.75em)

// Sender block (top-right)
#align(right)[
  #sender.name \
  #sender.title, #sender.org \
  #sender.address \
  #sender.email
]
#v(0.5em)
#datetime.today().display("[month repr:long] [day], [year]")
#v(1em)

// Recipient block
#recipient.name \
#recipient.org \
#recipient.address
#v(1em)

*#subject*
#v(0.8em)

Dear #recipient.name,

Replace this paragraph with the opening — why you are writing.

Replace this paragraph with the body — the substance of your message, the ask,
or the proposal. Keep it clear and concise.

Replace this with the closing paragraph and next steps.

#v(1em)
Sincerely, \
#v(2em)
#sender.name \
#sender.title, #sender.org
