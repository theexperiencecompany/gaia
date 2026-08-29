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

export { COMPOSER_CONSTANTS, type ComposerConstants } from "./constants";

export {
  useComposerBase,
  createComposerBase,
  INITIAL_COMPOSER_STATE,
  type ComposerState,
  type UseComposerBaseOptions,
  type UseComposerBaseReturn,
} from "./composerState";

export {
  isCommandMode,
  getCommandQuery,
  getMatchingCommands,
  filterMatchesByCategory,
  buildCategories,
  clampSelection,
  getNextCategoryIndex,
  getSelectedMatch,
  getUnlockedCount,
  isValidSlashPosition,
  detectSlashCommand,
  handleSlashKey,
  handleSlashCommandKey,
  type SlashTool,
  type EnhancedToolInfo,
  type SlashCommandMatch,
  type SlashDetection,
  type SlashKey,
  type SlashKeyContext,
  type SlashKeyResult,
} from "./slash";
