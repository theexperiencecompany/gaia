import { useTerminalSize } from "./use-terminal-size.js";

/** Cards stop growing here: on a wide terminal a full-width box is mostly empty. */
const MAX_CARD_WIDTH = 100;

/** The width a boxed card takes: the terminal's, up to MAX_CARD_WIDTH. */
export function useCardWidth(): number {
  return Math.min(useTerminalSize().columns, MAX_CARD_WIDTH);
}
