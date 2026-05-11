/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 *
 * Source file is `useLoadingText.ts` (the task list mentioned `useLoadingTe.ts`,
 * which appears to be a typo). Stubbed under the canonical name.
 */
interface ToolInfo {
  toolName?: string;
  toolCategory?: string;
  integrationName?: string;
  iconUrl?: string;
  showCategory?: boolean;
}

const noop = () => {};

export const useLoadingText = () => ({
  loadingText: "",
  loadingTextKey: 0,
  toolInfo: undefined as ToolInfo | undefined,
  setLoadingText: noop as (text: string, toolInfo?: ToolInfo) => void,
  setContextualLoading: noop as (
    isLoading: boolean,
    userMessage?: string,
    text?: string,
  ) => void,
  resetLoadingText: noop as () => void,
});
