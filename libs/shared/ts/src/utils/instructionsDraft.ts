/**
 * An edit to a user's standing instructions, pinned to the record it started from.
 *
 * The save sends base.revision as base_revision. Pinning it when typing starts,
 * not reading it at save time, is what lets the server catch a write that landed
 * meanwhile (often GAIA's own): a background refetch would otherwise move the
 * base forward and the stale draft would silently overwrite the newer text.
 */
export interface InstructionsRecordLike {
  content: string;
  revision: number;
}

export interface InstructionsEdit<T extends InstructionsRecordLike> {
  content: string;
  base: T | undefined;
}

export interface InstructionsDraftView<T extends InstructionsRecordLike> {
  /** The record a save is guarded against: the pinned one while editing, else the loaded one. */
  base: T | undefined;
  value: string;
  isDirty: boolean;
}

/** Apply a keystroke: keep the first base this edit saw, or pin the loaded record. */
export const editInstructions = <T extends InstructionsRecordLike>(
  previous: InstructionsEdit<T> | null,
  content: string,
  loaded: T | undefined,
): InstructionsEdit<T> => ({ content, base: previous?.base ?? loaded });

/** What the editor shows and saves against, given the current edit and the loaded record. */
export const viewInstructionsDraft = <T extends InstructionsRecordLike>(
  edit: InstructionsEdit<T> | null,
  loaded: T | undefined,
): InstructionsDraftView<T> => {
  const base = edit?.base ?? loaded;
  const value = edit?.content ?? base?.content ?? "";
  return { base, value, isDirty: base !== undefined && value !== base.content };
};
