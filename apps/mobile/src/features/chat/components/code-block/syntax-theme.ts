// VSCode Dark+ inspired color theme for syntax highlighting
// Matches the web app's vscDarkPlus Prism theme

export const THEME = {
  background: "#1e1e2e",
  headerBg: "#181825",
  headerBorder: "#313244",
  gutterText: "#585b70",
  plain: "#cdd6f4",
  keyword: "#cba6f7", // purple - if/else/for/while/return/const/let/var/function/class/import/export/from/async/await
  string: "#a6e3a1", // green - "string" 'string' `template`
  number: "#fab387", // peach - 123 0xFF 3.14
  comment: "#6c7086", // overlay0 - // comment /* comment */
  function: "#89b4fa", // blue - function calls
  type: "#f9e2af", // yellow - type names, class names
  operator: "#89dceb", // sky - = + - * / < > ! & | ?
  punctuation: "#9399b2", // overlay2 - () {} [] , ; :
  property: "#b4befe", // lavender - .property
  tag: "#f38ba8", // red - HTML/JSX tags
  attribute: "#fab387", // peach - HTML/JSX attributes
  regex: "#f38ba8", // red - /regex/
  boolean: "#fab387", // peach - true/false/null/undefined
  decorator: "#f9e2af", // yellow - @decorator
} as const;

export type TokenType = keyof Omit<
  typeof THEME,
  "background" | "headerBg" | "headerBorder" | "gutterText" | "plain"
>;
