"use client";

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
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

// Route-based create actions config
const ROUTE_ACTIONS = [
  { prefix: "/todos", selector: "create-todo" },
  { prefix: "/calendar", navigate: "/calendar?create=true" },
  { prefix: "/workflows", selector: "create-workflow" },
  { prefix: "/integrations", selector: "create-integration" },
] as const;

// Common options for all shortcuts
const HOTKEY_OPTIONS = { enableOnFormTags: false, preventDefault: true };

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
  useHotkeys("?", () => openShortcutsModal(), HOTKEY_OPTIONS);

  // ===========================================
  // CREATE: C key (context-aware)
  // ===========================================
  useHotkeys("c", () => createActionRef.current?.(), HOTKEY_OPTIONS);

  // ===========================================
  // NAVIGATION SHORTCUTS: G > X sequences
  // ===========================================
  useHotkeys("g>d", () => routerRef.current.push("/dashboard"), HOTKEY_OPTIONS);
  useHotkeys("g>c", () => routerRef.current.push("/calendar"), HOTKEY_OPTIONS);
  useHotkeys("g>t", () => routerRef.current.push("/todos"), HOTKEY_OPTIONS);
  useHotkeys("g>w", () => routerRef.current.push("/workflows"), HOTKEY_OPTIONS);
  useHotkeys(
    "g>h",
    () => {
      prepareNewChat();
      routerRef.current.push("/c");
    },
    HOTKEY_OPTIONS,
  );
  useHotkeys(
    "g>i",
    () => routerRef.current.push("/integrations"),
    HOTKEY_OPTIONS,
  );

  const contextValue = useMemo(
    () => ({
      openShortcutsModal,
      closeShortcutsModal,
      isModalOpen,
      triggerCreateAction,
    }),
    [openShortcutsModal, closeShortcutsModal, isModalOpen, triggerCreateAction],
  );

  return (
    <KeyboardShortcutsContext.Provider value={contextValue}>
      {children}
      <KeyboardShortcutsModal
        isOpen={isModalOpen}
        onOpenChange={setIsModalOpen}
      />
    </KeyboardShortcutsContext.Provider>
  );
}
