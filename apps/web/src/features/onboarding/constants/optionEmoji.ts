/**
 * Apple emoji artwork for the onboarding option chips, keyed by the option
 * `value` used in `professionOptions` and `needOptions`.
 *
 * The PNGs are Apple's emoji artwork, vendored from the `emoji-datasource-apple`
 * package (64px set) into `public/images/emoji/apple/` and named by codepoint,
 * so the chips render identically on Windows/Linux where the platform font has
 * no Apple glyphs. A unit test asserts every option value has an entry here.
 */

const EMOJI_DIR = "/images/emoji/apple";

export const OPTION_EMOJI: Record<string, string> = {
  // professions
  founder: `${EMOJI_DIR}/1f680.png`,
  executive: `${EMOJI_DIR}/1f4bc.png`,
  sales: `${EMOJI_DIR}/1f91d.png`,
  product: `${EMOJI_DIR}/1f9e9.png`,
  creative: `${EMOJI_DIR}/1f3a8.png`,
  engineering: `${EMOJI_DIR}/1f6e0-fe0f.png`,
  marketing: `${EMOJI_DIR}/1f4e3.png`,
  finance: `${EMOJI_DIR}/1f4ca.png`,
  student: `${EMOJI_DIR}/1f393.png`,
  other: `${EMOJI_DIR}/2728.png`,

  // needs
  inbox: `${EMOJI_DIR}/1f4e5.png`,
  calendar: `${EMOJI_DIR}/1f4c5.png`,
  briefings: `${EMOJI_DIR}/2600-fe0f.png`,
  todos: `${EMOJI_DIR}/2705.png`,
  memory: `${EMOJI_DIR}/1f9e0.png`,
  research: `${EMOJI_DIR}/1f50e.png`,
  automation: `${EMOJI_DIR}/2699-fe0f.png`,
  reach: `${EMOJI_DIR}/1f4f1.png`,
};
