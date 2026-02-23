/**
 * @module @gaia/shared/bots
 *
 * Shared bot library for all GAIA platform integrations (Discord, Slack, Telegram).
 *
 * Architecture overview:
 * - adapter/   - BaseBotAdapter abstract class + richMessageToMarkdown renderer
 * - commands/  - Unified BotCommand definitions (auth, help, settings, gaia, todo, etc.)
 * - types/     - Shared TypeScript interfaces (ChatRequest, CommandContext, BotCommand, etc.)
 * - api/       - GaiaClient: single HTTP client for all bot-to-backend communication
 * - config/    - Environment variable loader (GAIA_API_URL, GAIA_BOT_API_KEY, etc.)
 * - utils/     - Reusable logic split into three layers:
 *     - formatters.ts  - Pure display functions (formatTodo, formatBotError, etc.)
 *     - commands.ts    - Business-logic handlers (handleTodoList, dispatchTodoSubcommand, etc.)
 *     - streaming.ts   - handleStreamingChat: shared streaming + throttled editing
 *
 * When adding a new bot command:
 * 1. Create a new BotCommand in commands/<name>.ts
 * 2. Add it to the allCommands array in commands/index.ts
 * 3. If needed, add API methods to GaiaClient and formatters to formatters.ts
 *
 * When adding a new platform bot:
 * 1. Create a new directory under apps/bots/<platform>/
 * 2. Extend BaseBotAdapter and implement the five lifecycle methods
 * 3. In index.ts: create adapter instance, call adapter.boot(allCommands)
 */
export * from "./adapter";
export * from "./api";
export * from "./commands";
export * from "./config";
export * from "./types";
export * from "./utils";
