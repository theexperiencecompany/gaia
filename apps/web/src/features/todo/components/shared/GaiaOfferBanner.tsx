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

  // Stacked, not one row: text and buttons each get a full line, so the CTA
  // never clips or drifts regardless of container width (list row or sidebar).
  return (
    <div className="mt-2 space-y-1.5" onClick={(e) => e.stopPropagation()}>
      <p className="flex items-start gap-2 text-xs text-zinc-400">
        <SparklesIcon className="mt-0.5 size-3.5 shrink-0 text-violet-400" />
        <span className="line-clamp-2 min-w-0">{offer}</span>
      </p>
      <div className="flex items-center gap-1 pl-5">
        <Button
          size="sm"
          variant="flat"
          radius="lg"
          className="h-7 bg-violet-400/10 text-violet-400"
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
          className="size-7 min-w-0 text-zinc-500"
          onPress={() => {
            persistDismissedOffer(todoId);
            setDismissed(true);
          }}
        >
          <Cancel01Icon className="size-3.5" />
        </Button>
      </div>
    </div>
  );
};
