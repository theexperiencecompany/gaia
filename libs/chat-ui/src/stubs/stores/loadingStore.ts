/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
interface ToolInfo {
  toolName?: string;
  toolCategory?: string;
  integrationName?: string;
  iconUrl?: string;
  showCategory?: boolean;
}

interface LoadingState {
  isLoading: boolean;
  loadingText: string;
  loadingTextKey: number;
  toolInfo?: ToolInfo;
}

interface LoadingActions {
  setIsLoading: (loading: boolean) => void;
  setLoadingText: (
    text: string | { text: string; toolInfo?: ToolInfo },
  ) => void;
  resetLoadingText: () => void;
  setLoading: (loading: boolean, text?: string) => void;
  setLoadingWithContext: (
    loading: boolean,
    userMessage?: string,
    text?: string,
  ) => void;
}

type LoadingStore = LoadingState & LoadingActions;

const noop = () => {};

const frozenState: LoadingStore = Object.freeze({
  isLoading: false,
  loadingText: "",
  loadingTextKey: 0,
  toolInfo: undefined,
  setIsLoading: noop,
  setLoadingText: noop,
  resetLoadingText: noop,
  setLoading: noop,
  setLoadingWithContext: noop,
});

type Selector<U> = (state: LoadingStore) => U;

interface UseLoadingStoreFn {
  <U>(selector: Selector<U>): U;
  (): LoadingStore;
  getState: () => LoadingStore;
  setState: (partial: Partial<LoadingStore>) => void;
  subscribe: (listener: (state: LoadingStore) => void) => () => void;
}

export const useLoadingStore: UseLoadingStoreFn = (<U,>(
  selector?: Selector<U>,
) => {
  if (selector) return selector(frozenState);
  return frozenState;
}) as UseLoadingStoreFn;
useLoadingStore.getState = () => frozenState;
useLoadingStore.setState = noop;
useLoadingStore.subscribe = () => noop;

export const useIsLoading = (): boolean => false;
