"use client";

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
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
import { prepareNewChat } from "@/features/chat/utils/newChatNavigation";
import { usePathname } from "@/i18n/navigation";

const KeyboardShortcutsModal = dynamic(
  () => import("../shared/KeyboardShortcutsModal"),
  { ssr: false },
);

interface KeyboardShortcutsContextValue {
  openShortcutsModal: () => void;
  closeShortcutsModal: () => void;
  isModalOpen: boolean;
  triggerCreateAction: () => void;
}

const KeyboardShortcutsContext =
  createContext<KeyboardShortcutsContextValue | null>(null);

// Route-based create actions config — static, hoisted so it isn't rebuilt on
// every render and the shortcut callbacks never capture a stale copy.
const ROUTE_ACTIONS = [
  { prefix: "/todos", selector: "create-todo" },
  { prefix: "/calendar", navigate: "/calendar?create=true" },
  { prefix: "/workflows", selector: "create-workflow" },
  { prefix: "/integrations", selector: "create-integration" },
] as const;

// Common options for all shortcuts — static, hoisted to module scope.
const hotkeyOptions = { enableOnFormTags: false, preventDefault: true };

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

  // Keep the router ref fresh outside the render body — render must be pure.
  useEffect(() => {
    routerRef.current = router;
  });

  const openShortcutsModal = useCallback(() => setIsModalOpen(true), []);
  const closeShortcutsModal = useCallback(() => setIsModalOpen(false), []);

  const triggerCreateAction = useCallback(() => {
    const action = ROUTE_ACTIONS.find((a) => pathname.startsWith(a.prefix));

    if (action && "navigate" in action) router.push(action.navigate);
    else if (action && "selector" in action) {
      const btn = document.querySelector(
        `[data-keyboard-shortcut="${action.selector}"]`,
      ) as HTMLButtonElement;
      btn?.click();
    } else {
      prepareNewChat();
      router.push("/c");
    }
  }, [pathname, router]);

  useEffect(() => {
    createActionRef.current = triggerCreateAction;
  }, [triggerCreateAction]);

  // ===========================================
  // SHORTCUTS MODAL: ? key
  // ===========================================
  useHotkeys("?", () => openShortcutsModal(), hotkeyOptions);

  // ===========================================
  // CREATE: C key (context-aware)
  // ===========================================
  useHotkeys("c", () => createActionRef.current?.(), hotkeyOptions);

  // ===========================================
  // NAVIGATION SHORTCUTS: G > X sequences
  // ===========================================
  useHotkeys("g>d", () => routerRef.current.push("/dashboard"), hotkeyOptions);
  useHotkeys("g>c", () => routerRef.current.push("/calendar"), hotkeyOptions);
  useHotkeys("g>t", () => routerRef.current.push("/todos"), hotkeyOptions);
  useHotkeys("g>w", () => routerRef.current.push("/workflows"), hotkeyOptions);
  useHotkeys(
    "g>h",
    () => {
      prepareNewChat();
      routerRef.current.push("/c");
    },
    hotkeyOptions,
  );
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
