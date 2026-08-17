# PDF reference (Typst-first)

`read` this when adapting a template. Keep the template's structure; change the content.

## Typst in 60 seconds
- Set-rules configure defaults: `#set text(size: 11pt)`, `#set page(margin: 2cm, numbering: "1")`, `#set heading(numbering: "1.")`.
- Headings: `= H1`, `== H2`, `=== H3`. Body is plain text; blank line = new paragraph.
- Emphasis: `*bold*`, `_italic_`, `` `code` ``. Line break: `\`.
- Variables: `#let name = "Acme"` then use `#name` inline.
- Lists: `- item` (bullet), `+ item` (numbered).
- Tables: `#table(columns: 3, [*A*], [*B*], [*C*], [1], [2], [3])`.
- Images: `#image("logo.png", width: 40%)` (path relative to the source file).
- Money/symbols are literal text; escape a literal `$` as `\$` (a bare `$` opens math mode).
- Today's date: `#datetime.today().display("[year]-[month]-[day]")`.
- Page break: `#pagebreak()`.

## Fonts
Use Typst's bundled **New Computer Modern** (default) or **Libertinus Serif** — no download needed. Avoid naming a font that may be absent; if a font is missing Typst warns and substitutes, which can shift layout.

## Common error → fix
| Error message contains | Cause | Fix |
| --- | --- | --- |
| `unexpected end of block` / `expected closing bracket` | unbalanced `[ ]` or `{ }` | match every bracket; content args use `[...]` |
| `unknown variable` | used `#name` before `#let name = ...` | define the `#let` above its first use |
| `expected content, found ...` | passed a string where content is expected | wrap in `[...]`, e.g. `table(..., [#value])` |
| `unexpected dollar` / math where you wanted text | a bare `$` started math mode | escape money as `\$` |
| `file not found` for an image | wrong relative path | path is relative to the `.typ` file; copy the asset next to it |

## When to fall back to LaTeX (tectonic)
Switch to a `.tex` file (same `build.sh`, pass the `.tex`) when:
- You need a specific LaTeX package with no Typst equivalent (e.g. exotic chem/music/linguistics packages).
- The user requires a specific journal/publisher class (`\documentclass{...}`).
- Typst fails twice on the same construct and a LaTeX equivalent is straightforward.
tectonic auto-downloads only the packages the document uses; standard `article`/`report` classes work out of the box. Keep LaTeX minimal — no manual multi-pass needed, tectonic handles reruns.
