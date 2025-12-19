"use client";

import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { useHotkeys } from "react-hotkeys-hook";

import KeyboardShortcutsModal from "../shared/KeyboardShortcutsModal";

interface KeyboardShortcutsContextValue {
  openShortcutsModal: () => void;
  closeShortcutsModal: () => void;
  isModalOpen: boolean;
  triggerCreateAction: () => void;
}

const KeyboardShortcutsContext =
  createContext<KeyboardShortcutsContextValue | null>(null);

export function useKeyboardShortcuts() {
  const context = useContext(KeyboardShortcutsContext);
  if (!context) {
    throw new Error(
      "useKeyboardShortcuts must be used within KeyboardShortcutsProvider",
    );
  }
  return context;
}

interface KeyboardShortcutsProviderProps {
  children: ReactNode;
}

/**
 * Provider component that sets up global keyboard shortcuts
 */
export default function KeyboardShortcutsProvider({
  children,
}: KeyboardShortcutsProviderProps) {
  const router = useRouter();
  const pathname = usePathname();
  const [isModalOpen, setIsModalOpen] = useState(false);

  const createActionRef = useRef<(() => void) | null>(null);
  const routerRef = useRef(router);
  routerRef.current = router;

  const openShortcutsModal = useCallback(() => setIsModalOpen(true), []);
  const closeShortcutsModal = useCallback(() => setIsModalOpen(false), []);

  // Route-based create actions config
  const ROUTE_ACTIONS = [
    { prefix: "/todos", selector: "create-todo" },
    { prefix: "/calendar", navigate: "/calendar?create=true" },
    { prefix: "/workflows", selector: "create-workflow" },
    { prefix: "/goals", selector: "create-goal" },
  ] as const;

  const triggerCreateAction = useCallback(() => {
    const action = ROUTE_ACTIONS.find((a) => pathname.startsWith(a.prefix));

    if (action && "navigate" in action) router.push(action.navigate);
    else if (action && "selector" in action) {
      const btn = document.querySelector(
        `[data-keyboard-shortcut="${action.selector}"]`,
      ) as HTMLButtonElement;
      btn?.click();
    } else router.push("/c");
  }, [pathname, router]);

  useEffect(() => {
    createActionRef.current = triggerCreateAction;
  }, [triggerCreateAction]);

  // Common options for all shortcuts
  const hotkeyOptions = { enableOnFormTags: false, preventDefault: true };

  // ===========================================
  // SHORTCUTS MODAL: ? key
  // ===========================================
  useHotkeys("?", () => openShortcutsModal(), hotkeyOptions);

  // ===========================================
  // CREATE: C key (context-aware)
  // Uses keyup to avoid conflict with g>c sequence
  // ===========================================
  useHotkeys(
    "c",
    (e) => {
      const target = e.target as HTMLElement;
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.isContentEditable
      ) {
        return;
      }
      createActionRef.current?.();
    },
    { enableOnFormTags: false, keyup: true, keydown: false },
  );

  // ===========================================
  // NAVIGATION SHORTCUTS: G > X sequences
  // ===========================================
  useHotkeys("g>d", () => routerRef.current.push("/dashboard"), hotkeyOptions);
  useHotkeys("g>c", () => routerRef.current.push("/calendar"), hotkeyOptions);
  useHotkeys("g>t", () => routerRef.current.push("/todos"), hotkeyOptions);
  useHotkeys("g>o", () => routerRef.current.push("/goals"), hotkeyOptions);
  useHotkeys("g>w", () => routerRef.current.push("/workflows"), hotkeyOptions);
  useHotkeys("g>h", () => routerRef.current.push("/c"), hotkeyOptions);
  useHotkeys(
    "g>i",
    () => routerRef.current.push("/integrations"),
    hotkeyOptions,
  );

  return (
    <KeyboardShortcutsContext.Provider
      value={{
        openShortcutsModal,
        closeShortcutsModal,
        isModalOpen,
        triggerCreateAction,
      }}
    >
      {children}
      <KeyboardShortcutsModal
        isOpen={isModalOpen}
        onOpenChange={setIsModalOpen}
      />
    </KeyboardShortcutsContext.Provider>
  );
}
