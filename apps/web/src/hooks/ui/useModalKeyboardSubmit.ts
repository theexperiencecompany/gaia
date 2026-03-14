"use client";

import { useEffect, useRef } from "react";

interface ModalKeyboardSubmitOptions {
  isOpen: boolean;
  loading: boolean;
  isMac: boolean;
  handleSubmit: () => void;
}

/**
 * Attaches a Cmd/Ctrl+Enter keyboard shortcut to submit a modal form.
 * Uses a ref to always read the latest loading/isMac/handleSubmit values
 * without re-registering the event listener on every render.
 */
export function useModalKeyboardSubmit({
  isOpen,
  loading,
  isMac,
  handleSubmit,
}: ModalKeyboardSubmitOptions): void {
  const stateRef = useRef({ loading, isMac, handleSubmit });
  stateRef.current = { loading, isMac, handleSubmit };

  useEffect(() => {
    if (!isOpen) return;

    const onKeyDown = (e: KeyboardEvent) => {
      const {
        loading: isLoading,
        isMac: mac,
        handleSubmit: submit,
      } = stateRef.current;
      if (isLoading) return;
      const modifierKey = mac ? e.metaKey : e.ctrlKey;
      if (modifierKey && e.key === "Enter") {
        e.preventDefault();
        submit();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [isOpen]);
}
