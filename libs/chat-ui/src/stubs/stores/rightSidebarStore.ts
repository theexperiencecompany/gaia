/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
import type { ReactNode } from "react";

export type RightSidebarVariant = "sheet" | "sidebar" | "artifact";

interface RightSidebarState {
  content: ReactNode | null;
  isOpen: boolean;
  variant: RightSidebarVariant;
  setContent: (content: ReactNode | null) => void;
  setVariant: (variant: RightSidebarVariant) => void;
  open: (variant?: RightSidebarVariant) => void;
  openWithContent: (
    content: ReactNode,
    variant?: RightSidebarVariant,
  ) => void;
  close: () => void;
}

const noop = () => {};

const frozenState: RightSidebarState = Object.freeze({
  content: null,
  isOpen: false,
  variant: "sidebar" as RightSidebarVariant,
  setContent: noop,
  setVariant: noop,
  open: noop,
  openWithContent: noop,
  close: noop,
});

type Selector<U> = (state: RightSidebarState) => U;

interface UseStoreFn {
  <U>(selector: Selector<U>): U;
  (): RightSidebarState;
  getState: () => RightSidebarState;
  setState: (partial: Partial<RightSidebarState>) => void;
  subscribe: (listener: (state: RightSidebarState) => void) => () => void;
}

export const useRightSidebar: UseStoreFn = (<U,>(selector?: Selector<U>) => {
  if (selector) return selector(frozenState);
  return frozenState;
}) as UseStoreFn;
useRightSidebar.getState = () => frozenState;
useRightSidebar.setState = noop;
useRightSidebar.subscribe = () => noop;
