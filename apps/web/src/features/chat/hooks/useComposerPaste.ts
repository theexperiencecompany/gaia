"use client";

import type React from "react";
import { useEffect, useRef } from "react";

import {
  LARGE_PASTE_THRESHOLD_CHARS,
  PASTED_TEXT_FILENAME,
} from "@/features/chat/constants/files";

interface UseComposerPasteParams {
  /** The composer textarea — only pastes landing in it are captured. */
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
  attachFiles: (files: File[]) => Promise<void>;
}

/**
 * Global paste handling for the composer: an image pasted into the input
 * becomes a file attachment, and a very large text paste becomes a .txt
 * attachment so the input stays responsive.
 */
export function useComposerPaste({
  inputRef,
  attachFiles,
}: UseComposerPasteParams): void {
  // Store paste handler in a ref to avoid re-subscribing the event listener
  // whenever dependencies change (advanced-event-handler-refs pattern).
  const handlePasteRef = useRef((_e: ClipboardEvent) => {
    /* placeholder: replaced with the real handler in the effect below */
  });
  useEffect(() => {
    handlePasteRef.current = (e: ClipboardEvent) => {
      // Only react to pastes inside the composer input — an image pasted into
      // any other element while Composer is mounted must not be captured.
      if (e.target !== inputRef.current) return;

      const items = e.clipboardData?.items;
      if (!items) return;
      for (let i = 0; i < items.length; i++) {
        if (items[i].type.indexOf("image") !== -1) {
          const file = items[i].getAsFile();
          if (file) {
            e.preventDefault();
            attachFiles([file]);
            return;
          }
        }
      }

      // Large text pasted into the composer becomes a .txt attachment instead of
      // inline text — keeps the input responsive and rides the file pipeline.
      const text = e.clipboardData?.getData("text/plain");
      if (text && text.length > LARGE_PASTE_THRESHOLD_CHARS) {
        e.preventDefault();
        attachFiles([
          new File([text], PASTED_TEXT_FILENAME, { type: "text/plain" }),
        ]);
      }
    };
  });

  // Add paste event listener for images (stable subscription)
  useEffect(() => {
    const listener = (e: ClipboardEvent) => handlePasteRef.current(e);
    document.addEventListener("paste", listener);
    return () => {
      document.removeEventListener("paste", listener);
    };
  }, []);
}
