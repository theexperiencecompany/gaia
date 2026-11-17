/**
 * Where a part sits relative to its anchor (the data-parity cell, or an open
 * overlay's data-parity-mark): "self", "css:<selector>" inside it, "all:<selector>"
 * (one part per match, suffixed with its index), "text:<label>" (the innermost
 * element whose text is the label), "up:<selector>" (the closest ancestor) and
 * "up:<selector>|<selector>" (a descendant of that ancestor).
 */
export type PartSelector = string;
export type PartMap = Record<string, PartSelector>;
export type Styles = Record<string, string>;
/** `<id>::<part>::<state>` to the part's computed styles in that state. */
export type Capture = Record<string, Styles>;
