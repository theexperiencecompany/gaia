"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef } from "react";

import {
  useComposerTextActions,
  usePendingPrompt,
} from "@/stores/composerStore";

/**
 * Fills the composer from the two out-of-band seeds that can arrive with a
 * chat: a staged prompt (composer store) and a `?q=` deep link.
 *
 * Lives with the composer, not the page, so a prompt staged while the composer
 * is unmounted (e.g. during a voice call) isn't dropped.
 */
export const useComposerSeeds = (
  inputRef: React.RefObject<HTMLTextAreaElement | null>,
): void => {
  const router = useRouter();
  const pendingPrompt = usePendingPrompt();
  const { appendToInputText, clearPendingPrompt } = useComposerTextActions();

  // Append rather than replace, and leave the caret ready, so a seed behaves
  // exactly like clicking a suggestion chip.
  const seedInput = useCallback(
    (text: string) => {
      appendToInputText(text);
      inputRef.current?.focus();
    },
    [appendToInputText, inputRef],
  );

  // Exactly-once guard keyed on the prompt: StrictMode re-runs the effect
  // before the cleared store has propagated, and appending twice would hand
  // the user a duplicated draft. A different prompt staged later still seeds.
  const seededPromptRef = useRef<string | null>(null);

  useEffect(() => {
    if (!pendingPrompt) return;
    if (seededPromptRef.current === pendingPrompt) return;
    seededPromptRef.current = pendingPrompt;
    seedInput(pendingPrompt);
    clearPendingPrompt();
  }, [pendingPrompt, seedInput, clearPendingPrompt]);

  // Read straight from the URL rather than into React state: the seed is a
  // one-shot mount read, and the ref makes it idempotent if `seedInput`'s
  // identity changes before the router has stripped the param.
  const queryPromptSeededRef = useRef(false);

  useEffect(() => {
    if (queryPromptSeededRef.current) return;
    const queryPrompt = new URLSearchParams(window.location.search).get("q");
    if (!queryPrompt) return;
    queryPromptSeededRef.current = true;
    seedInput(queryPrompt);
    const url = new URL(window.location.href);
    url.searchParams.delete("q");
    router.replace(url.pathname + url.search, { scroll: false });
  }, [seedInput, router]);
};
