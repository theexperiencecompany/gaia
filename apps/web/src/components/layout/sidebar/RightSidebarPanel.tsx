"use client";

import { type ReactNode, useEffect, useRef } from "react";
import { createPortal } from "react-dom";

import { useRightSidebarSlot } from "@/components/layout/sidebar/RightSidebarSlot";
import {
  useCloseRightSidebar,
  useLayoutStore,
  useOpenRightSidebar,
} from "@/stores/layoutStore";
import type { RightSidebarMode } from "@/stores/layoutStore.types";

interface RightSidebarPanelProps {
  /** Presentation mode the sidebar opens in while this panel is mounted. */
  mode: RightSidebarMode;
  /**
   * Called when the sidebar is closed from outside this panel — the X button or
   * Escape. The owning page uses it to clear whatever selection mounted the
   * panel. Not called when the panel itself unmounts.
   */
  onClose?: () => void;
  children: ReactNode;
}

/**
 * Mounts a panel into the right sidebar: opening it on mount, closing it on
 * unmount, and portalling `children` into the slot rendered by the layout.
 *
 * Pages own their panel's props as ordinary React props — nothing about the
 * panel goes through the store, which holds only `{ isOpen, mode }`.
 */
export default function RightSidebarPanel({
  mode,
  onClose,
  children,
}: RightSidebarPanelProps) {
  const slot = useRightSidebarSlot();
  const open = useOpenRightSidebar();
  const close = useCloseRightSidebar();
  const isUnmountingRef = useRef(false);

  // Read through a ref so the subscription below is set up once and never
  // resubscribes just because the page passed a new closure.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  // Declared before the open/close effect so that on unmount React runs this
  // cleanup (unsubscribe) first — the store close below then can't be mistaken
  // for the user pressing X.
  useEffect(() => {
    return useLayoutStore.subscribe((state, prevState) => {
      if (prevState.rightSidebar.isOpen && !state.rightSidebar.isOpen) {
        if (isUnmountingRef.current) return;
        onCloseRef.current?.();
      }
    });
  }, []);

  useEffect(() => {
    isUnmountingRef.current = false;
    open(mode);
    return () => {
      isUnmountingRef.current = true;
      close();
    };
  }, [mode, open, close]);

  if (!slot) return null;
  return createPortal(children, slot);
}
