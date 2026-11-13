"use client";

import {
  memo,
  type ReactNode,
  Suspense,
  use,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

/** Start hydrating a deferred section this far before it scrolls into view. */
const HYDRATE_AHEAD_MARGIN = "100% 0px";
/** Events that mean the user reached a section before it scrolled near: hydrate it now so the event lands. */
const INTERACTION_EVENTS = ["pointerdown", "keydown", "focusin"] as const;

const unsubscribeNothing = () => undefined;
// The hydration state never changes under a mounted component, so nothing to subscribe to.
const subscribeNever = () => unsubscribeNothing;

/** True while React hydrates server HTML (it reads the server snapshot then), false in a client render. */
function useIsHydrating(): boolean {
  return useSyncExternalStore(
    subscribeNever,
    () => false,
    () => true,
  );
}

/** A promise React's `use` reads synchronously once its status says fulfilled. */
type TrackedPromise = Promise<void> & {
  status?: "fulfilled";
  value?: undefined;
};

interface Gate {
  promise: TrackedPromise;
  open: () => void;
}

/** Mark a promise fulfilled so `use` reads it synchronously instead of suspending for a microtask. */
function markFulfilled(promise: TrackedPromise): void {
  promise.status = "fulfilled";
  promise.value = undefined;
}

const OPEN_GATE: Gate = { promise: Promise.resolve(), open: () => undefined };
markFulfilled(OPEN_GATE.promise);

/** Opening marks the promise fulfilled first, so a hydration React runs synchronously inside an event reads it. */
function createClosedGate(): Gate {
  const { promise, resolve } = Promise.withResolvers<void>();
  return {
    promise,
    open: () => {
      markFulfilled(promise);
      resolve();
    },
  };
}

function GatedChildren({
  gate,
  children,
}: {
  gate: Promise<void>;
  children: ReactNode;
}) {
  use(gate);
  return children;
}

interface DeferredBoundaryProps {
  gate: Promise<void>;
  isOpen: boolean;
  children: ReactNode;
}

/** Skips every re-render while the gate is closed: handed new props then, a dehydrated boundary drops its HTML (or stalls a transition). */
const DeferredBoundary = memo(
  function DeferredBoundary({ gate, children }: DeferredBoundaryProps) {
    // While hydrating, a suspended boundary keeps its server HTML and shows no fallback.
    return (
      <Suspense fallback={null}>
        <GatedChildren gate={gate}>{children}</GatedChildren>
      </Suspense>
    );
  },
  (previous, next) => !previous.isOpen && !next.isOpen,
);

/**
 * Leave a below-the-fold section's server HTML dehydrated until it nears the
 * viewport, then hydrate those same nodes in place. Skipping its hydration takes
 * that work off the page-load main thread; DOM nodes and focus survive.
 *
 * A pointer, key or focus inside it opens it early. Mounted by a client navigation, it renders at once.
 */
export function HydrateOnVisible({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const isHydrating = useIsHydrating();
  // Server render and hydration both read the server snapshot, so only the global tells them apart.
  const [gate] = useState(
    // react-doctor-disable-next-line react-doctor/no-hydration-branch-on-browser-global
    () =>
      typeof window === "undefined" || !isHydrating
        ? OPEN_GATE
        : createClosedGate(),
  );
  const [isOpen, setIsOpen] = useState(gate === OPEN_GATE);

  useEffect(() => {
    const node = ref.current;
    if (gate === OPEN_GATE || !node) return;
    const stopWatching = () => {
      observer.disconnect();
      for (const type of INTERACTION_EVENTS) {
        window.removeEventListener(type, openOnInteraction, true);
      }
    };
    const open = () => {
      stopWatching();
      gate.open();
      setIsOpen(true);
    };
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) open();
      },
      { rootMargin: HYDRATE_AHEAD_MARGIN },
    );
    // React hydrates a dehydrated boundary the user interacts with, but only an open gate lets it; the window
    // capture phase runs before React's root listener, which swallows events it cannot dispatch yet.
    const openOnInteraction = (event: Event) => {
      if (event.target instanceof Node && node.contains(event.target)) open();
    };
    observer.observe(node);
    for (const type of INTERACTION_EVENTS) {
      window.addEventListener(type, openOnInteraction, true);
    }
    return stopWatching;
  }, [gate]);

  return (
    <div ref={ref}>
      <DeferredBoundary gate={gate.promise} isOpen={isOpen}>
        {children}
      </DeferredBoundary>
    </div>
  );
}
