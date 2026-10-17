import { useStdout } from "ink";

/** Cards stop growing here: on a wide terminal a full-width box is mostly empty. */
const MAX_CARD_WIDTH = 100;
const FALLBACK_COLUMNS = 80;

/** The width a boxed card takes: the terminal's, up to MAX_CARD_WIDTH. */
export function useCardWidth(): number {
  const { stdout } = useStdout();
  return Math.min(stdout.columns || FALLBACK_COLUMNS, MAX_CARD_WIDTH);
}
