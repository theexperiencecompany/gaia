"use client";

import { useCallback, useState } from "react";

import type { Integration } from "../types";

/**
 * Open/close state for the CLI connect modal.
 *
 * Mirrors `useBearerTokenModal`: the list component decides *that* a CLI
 * integration should open a modal, and this owns the rest. The integration is
 * deliberately kept after `close()` so the modal still has a name to render
 * while it animates out — clearing it makes the title flash empty.
 */
export function useCliConnectModal() {
  const [isOpen, setIsOpen] = useState(false);
  const [integration, setIntegration] = useState<Integration | null>(null);

  const open = useCallback((target: Integration) => {
    setIntegration(target);
    setIsOpen(true);
  }, []);

  const close = useCallback(() => setIsOpen(false), []);

  return {
    isOpen,
    integrationId: integration?.id ?? null,
    integrationName: integration?.name ?? "",
    open,
    close,
  };
}
