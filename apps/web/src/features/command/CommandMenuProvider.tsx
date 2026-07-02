"use client";

import { AnimatePresence } from "motion/react";
import nextDynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import ErrorBoundary from "@/components/shared/ErrorBoundary";
import { useConfirmation } from "@/hooks/useConfirmation";
import type { CommandHost } from "./model/types";
import { useCommandMenuStore } from "./store";

// The menu (cmdk + all providers + data hooks) is code-split and only mounted
// while open — so it costs nothing until the first ⌘K.
const CommandMenu = nextDynamic(() => import("./CommandMenu"), { ssr: false });

/** Warm the menu chunk on hover/focus of a trigger. */
export const preloadCommandMenu = () => {
  void import("./CommandMenu");
};

/**
 * Mounts the command menu once at the app root. Owns global shortcuts, the
 * confirm dialog, and the host capabilities the menu needs. Drop one
 * `<CommandMenuProvider />` into the layout — nothing else required.
 */
export function CommandMenuProvider() {
  const router = useRouter();
  const isOpen = useCommandMenuStore((s) => s.isOpen);
  const close = useCommandMenuStore((s) => s.close);

  // Stabilize confirm so the host (and the menu's command groups) stay stable.
  const { confirm: rawConfirm, confirmationProps } = useConfirmation();
  const confirmRef = useRef(rawConfirm);
  confirmRef.current = rawConfirm;
  const confirm = useCallback<CommandHost["confirm"]>(
    (opts) => confirmRef.current(opts),
    [],
  );
  const host = useMemo<CommandHost>(
    () => ({ close, confirm }),
    [close, confirm],
  );

  // ⌘K toggles the menu; ⌘, jumps to settings (parity with the old menu).
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const mod = event.metaKey || event.ctrlKey;
      if (mod && event.key === "k") {
        event.preventDefault();
        useCommandMenuStore.getState().toggle();
      } else if (mod && event.key === ",") {
        event.preventDefault();
        router.push("/settings");
        useCommandMenuStore.getState().close();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [router]);

  return (
    <>
      <ErrorBoundary>
        <AnimatePresence>
          {isOpen && <CommandMenu host={host} />}
        </AnimatePresence>
      </ErrorBoundary>
      <ConfirmationDialog {...confirmationProps} />
    </>
  );
}
