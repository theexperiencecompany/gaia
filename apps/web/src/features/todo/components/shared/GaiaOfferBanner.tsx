"use client";

import { Button } from "@heroui/button";
import { Cancel01Icon, SparklesIcon } from "@icons";
import type React from "react";
import { useEffect, useState } from "react";
import { useHandoffTodo } from "@/features/todo/hooks/useHandoffTodo";

const DISMISSED_OFFERS_KEY = "gaia-todo-offers-dismissed";

function readDismissedOffers(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = localStorage.getItem(DISMISSED_OFFERS_KEY);
    return raw ? new Set(JSON.parse(raw) as string[]) : new Set();
  } catch {
    return new Set();
  }
}

function persistDismissedOffer(todoId: string): void {
  if (typeof window === "undefined") return;
  try {
    const dismissed = readDismissedOffers();
    dismissed.add(todoId);
    localStorage.setItem(
      DISMISSED_OFFERS_KEY,
      JSON.stringify(Array.from(dismissed)),
    );
  } catch {
    // Local dismiss is a nice-to-have — silently no-op if storage is unavailable.
  }
}

interface GaiaOfferBannerProps {
  todoId: string;
  offer: string;
}

/**
 * Quiet, dismissible "GAIA can do this" affordance for a user-owned todo
 * with a `gaia_offer`. There's no per-offer-dismiss endpoint, so dismissal
 * is tracked client-side (localStorage), same as other locally-dismissed
 * one-off UI affordances in this codebase.
 */
export const GaiaOfferBanner: React.FC<GaiaOfferBannerProps> = ({
  todoId,
  offer,
}) => {
  const [dismissed, setDismissed] = useState(false);
  const handoffTodo = useHandoffTodo();

  useEffect(() => {
    setDismissed(readDismissedOffers().has(todoId));
  }, [todoId]);

  if (dismissed) return null;

  return (
    <div
      className="mt-2 flex items-center gap-2 text-xs text-zinc-500"
      onClick={(e) => e.stopPropagation()}
    >
      <SparklesIcon className="size-3.5 shrink-0 text-violet-400" />
      <span className="min-w-0 flex-1 truncate">{offer}</span>
      <Button
        size="sm"
        variant="light"
        radius="lg"
        className="h-6 min-w-0 px-2 text-xs text-violet-400"
        isLoading={handoffTodo.isPending}
        onPress={() => handoffTodo.mutate(todoId)}
      >
        Let GAIA handle it
      </Button>
      <Button
        size="sm"
        variant="light"
        radius="lg"
        isIconOnly
        aria-label="Dismiss offer"
        className="size-6 min-w-0"
        onPress={() => {
          persistDismissedOffer(todoId);
          setDismissed(true);
        }}
      >
        <Cancel01Icon className="size-3.5" />
      </Button>
    </div>
  );
};
