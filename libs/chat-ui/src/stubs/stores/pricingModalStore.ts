/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
interface PricingModalStore {
  open: boolean;
  openModal: () => void;
  closeModal: () => void;
}

const noop = () => {};

const frozenState: PricingModalStore = Object.freeze({
  open: false,
  openModal: noop,
  closeModal: noop,
});

type Selector<U> = (state: PricingModalStore) => U;

interface UseStoreFn {
  <U>(selector: Selector<U>): U;
  (): PricingModalStore;
  getState: () => PricingModalStore;
  setState: (partial: Partial<PricingModalStore>) => void;
  subscribe: (listener: (state: PricingModalStore) => void) => () => void;
}

export const usePricingModalStore: UseStoreFn = (<U,>(
  selector?: Selector<U>,
) => {
  if (selector) return selector(frozenState);
  return frozenState;
}) as UseStoreFn;
usePricingModalStore.getState = () => frozenState;
usePricingModalStore.setState = noop;
usePricingModalStore.subscribe = () => noop;
