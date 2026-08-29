/**
 * @gaia/shared/chat/composer — headless, UI-agnostic composer base.
 *
 * Import via: `import { useComposerBase, COMPOSER_CONSTANTS } from "@gaia/shared/chat/composer"`
 *
 * This barrel is the public entry for the shared composer scaffold.
 * It keeps platform glue (DOM `getDropdownPosition`, RN TextInput,
 * Zustand persist) in app layers and shares only pure state + slash
 * logic.
 */

export {
  type ComposerState,
  createComposerBase,
  INITIAL_COMPOSER_STATE,
  type UseComposerBaseOptions,
  type UseComposerBaseReturn,
  useComposerBase,
} from "./composerState";
export { COMPOSER_CONSTANTS, type ComposerConstants } from "./constants";

export {
  buildCategories,
  clampSelection,
  detectSlashCommand,
  type EnhancedToolInfo,
  filterMatchesByCategory,
  getCommandQuery,
  getMatchingCommands,
  getNextCategoryIndex,
  getSelectedMatch,
  getUnlockedCount,
  handleSlashCommandKey,
  handleSlashKey,
  isCommandMode,
  isValidSlashPosition,
  type SlashCommandMatch,
  type SlashDetection,
  type SlashKey,
  type SlashKeyContext,
  type SlashKeyResult,
  type SlashTool,
} from "./slash";
