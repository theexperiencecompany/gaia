"use client";

import type { BriefingEdition, EditionChoice } from "@shared/api/generated";
import { useEffect, useRef, useState } from "react";
import { toast } from "@/lib/toast";
import { NotificationsAPI } from "@/services/api/notifications";

interface UseBriefingEditionsSettings {
  /** null until the stored choices load; nothing is shown as stored before then. */
  editions: BriefingEdition[] | null;
  /** The stored choices could not be read; the API client has already reported why. */
  loadFailed: boolean;
  /** Take an edition out of the rotation, or put it back. The last one on stays on. */
  toggleOn: (family: string) => void;
  /** Favourite an edition (turning it back on), or unfavourite it. */
  toggleFavourite: (family: string) => void;
}

const SAVE_FAILED = "Couldn't save your editions.";
const LAST_ONE_ON = "Keep at least one edition on.";
const NOTHING_SAVING: Promise<void> = Promise.resolve();

/**
 * Owns which daily editions the user's brief draws: each one on, off or a
 * favourite, saved on every change and rolled back on failure.
 *
 * Each save sends the whole map, so saves run one after another: the last one
 * to land is always the newest choice.
 */
export function useBriefingEditionsSettings(): UseBriefingEditionsSettings {
  const [editions, setEditions] = useState<BriefingEdition[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  // What the server last confirmed, which a refused save rolls back to.
  const confirmed = useRef<BriefingEdition[] | null>(null);
  const saving = useRef(NOTHING_SAVING);

  useEffect(() => {
    NotificationsAPI.getBriefingEditions().then(
      (stored) => {
        confirmed.current = stored.editions;
        setEditions(stored.editions);
      },
      () => setLoadFailed(true),
    );
  }, []);

  const choose = (family: string, choice: EditionChoice) => {
    if (!editions) return;
    const next = editions.map((edition) =>
      edition.family === family ? { ...edition, choice } : edition,
    );
    setEditions(next);
    const choices = Object.fromEntries(next.map((e) => [e.family, e.choice]));
    saving.current = saving.current.then(async () => {
      try {
        const stored = await NotificationsAPI.updateBriefingEditions({
          choices,
        });
        confirmed.current = stored.editions;
      } catch {
        setEditions(confirmed.current);
        toast.error(SAVE_FAILED);
      }
    });
  };

  const choiceOf = (family: string) =>
    editions?.find((edition) => edition.family === family)?.choice;

  const toggleOn = (family: string) => {
    if (!editions) return;
    if (choiceOf(family) === "off") {
      choose(family, "on");
      return;
    }
    const onCount = editions.filter((e) => e.choice !== "off").length;
    if (onCount === 1) {
      toast.info(LAST_ONE_ON);
      return;
    }
    choose(family, "off");
  };

  const toggleFavourite = (family: string) => {
    choose(family, choiceOf(family) === "favourite" ? "on" : "favourite");
  };

  return { editions, loadFailed, toggleOn, toggleFavourite };
}
