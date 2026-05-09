// VSCode Dark+ color theme for syntax highlighting

export const THEME = {
  background: "#1e1e1e",
  headerBg: "#1a1a1a",
  headerBorder: "#3f3f46",
  gutterText: "#858585",
  plain: "#d4d4d4",
  keyword: "#569cd6", // blue - if/else/for/while/return/const/let/var/function/class/import/export/from/async/await
  string: "#ce9178", // orange-brown - "string" 'string' `template`
  number: "#b5cea8", // light green - 123 0xFF 3.14
  comment: "#6a9955", // green - // comment /* comment */
  function: "#dcdcaa", // yellow - function calls
  type: "#4ec9b0", // teal - type names, class names
  operator: "#d4d4d4", // plain - = + - * / < > ! & | ?
  punctuation: "#d4d4d4", // plain - () {} [] , ; :
  property: "#9cdcfe", // light blue - .property
  variable: "#9cdcfe", // light blue - variables
  tag: "#569cd6", // blue - HTML/JSX tags
  attribute: "#9cdcfe", // light blue - HTML/JSX attributes
  regex: "#d16969", // red - /regex/
  boolean: "#569cd6", // blue - true/false/null/undefined
  decorator: "#dcdcaa", // yellow - @decorator
} as const;

export type TokenType = keyof Omit<
  typeof THEME,
  "background" | "headerBg" | "headerBorder" | "gutterText" | "plain"
>;
