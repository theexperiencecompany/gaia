"use client";

import type {
  BriefingEdition,
  BriefingEditions,
  EditionChoice,
} from "@shared/api/generated";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";
import {
  briefingApi,
  briefingEditionsQuery,
  briefingKeys,
} from "@/features/briefing";
import { toast } from "@/lib/toast";

interface UseBriefingEditionsSettings {
  /** null until the stored choices load; nothing is shown as stored before then. */
  editions: BriefingEdition[] | null;
  /** The stored choices could not be read. */
  loadFailed: boolean;
  refetch: () => void;
  /** Take an edition out of the rotation, or put it back. The last one on stays on. */
  toggleOn: (family: string) => void;
  /** Favourite an edition (turning it back on), or unfavourite it. */
  toggleFavourite: (family: string) => void;
}

const SAVE_FAILED = "Couldn't save your editions.";
const LAST_ONE_ON = "Keep at least one edition on.";

/**
 * Owns which daily editions the user's brief draws: each one on, off or a
 * favourite, shown at once, saved on every change and rolled back on failure.
 *
 * Each save sends the whole map, so saves run one after another in one scope:
 * the last one to land is always the newest choice.
 */
export function useBriefingEditionsSettings(): UseBriefingEditionsSettings {
  const qc = useQueryClient();
  const { data, isError, refetch } = useQuery(briefingEditionsQuery());
  // What the server last confirmed, which a refused save rolls back to.
  const confirmed = useRef<BriefingEditions | undefined>(undefined);

  const mutation = useMutation({
    scope: { id: briefingKeys.editions.join("/") },
    mutationFn: (next: BriefingEdition[]) =>
      briefingApi.updateEditions({
        choices: Object.fromEntries(next.map((e) => [e.family, e.choice])),
      }),
    onSuccess: (stored) => {
      confirmed.current = stored;
    },
    onError: () => {
      qc.setQueryData(briefingKeys.editions, confirmed.current);
      toast.error(SAVE_FAILED);
    },
  });

  // Read from the cache, not the render: a second tap may land before the first re-renders.
  const stored = () =>
    qc.getQueryData<BriefingEditions>(briefingKeys.editions)?.editions ?? [];

  const choiceOf = (family: string) =>
    stored().find((edition) => edition.family === family)?.choice;

  const choose = (family: string, choice: EditionChoice) => {
    const next = stored().map((edition) =>
      edition.family === family ? { ...edition, choice } : edition,
    );
    confirmed.current ??= { editions: stored() };
    qc.setQueryData(briefingKeys.editions, { editions: next });
    mutation.mutate(next);
  };

  const toggleOn = (family: string) => {
    if (choiceOf(family) === "off") {
      choose(family, "on");
      return;
    }
    const onCount = stored().filter((e) => e.choice !== "off").length;
    if (onCount === 1) {
      toast.info(LAST_ONE_ON);
      return;
    }
    choose(family, "off");
  };

  const toggleFavourite = (family: string) => {
    choose(family, choiceOf(family) === "favourite" ? "on" : "favourite");
  };

  return {
    editions: data?.editions ?? null,
    loadFailed: isError,
    refetch: () => void refetch(),
    toggleOn,
    toggleFavourite,
  };
}
