/** Every size the brief's letter is drawn at; its motion is in components/shared/letterMotion. */

/** An opened brief or edition sample is drawn this wide, the screen's width less a gutter when narrower. */
export const BRIEF_LETTER_MAX_WIDTH_PX = 760;
export const LETTER_VIEWPORT_GUTTER_PX = 24;
export const BRIEF_LETTER_WIDTH = `min(${BRIEF_LETTER_MAX_WIDTH_PX}px, calc(100vw - ${LETTER_VIEWPORT_GUTTER_PX}px))`;

/** The folded letter in chat; its panels are cut wide enough for it too. */
export const CHAT_LETTER_MAX_WIDTH_PX = 340;
/** The chat letter lies tipped back this far; the open letter straightens from it. */
export const LETTER_TILT_DEG = 12;
/** The perspective the tipped letter is seen in. */
export const LETTER_TILT_PERSPECTIVE_PX = 1100;
/** The deeper perspective the panels unfold in, so a far crease never looms. */
export const LETTER_FOLD_PERSPECTIVE_PX = 1800;

/** An edition is rendered at 3x a 540px page, plus a desk family's transparent shadow margin. */
export const EDITION_RENDER_WIDTH_PX = 1716;
/** Only reserves space while the edition loads; the image keeps its own ratio. */
export const EDITION_TYPICAL_HEIGHT_PX = 4700;
/** The brief page's column, the width of the edition's printed page. */
export const BRIEF_PAGE_COLUMN_CLASS = "max-w-[540px]";
