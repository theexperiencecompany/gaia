"use client";

import { useCallback, useRef, useState } from "react";

import { toast } from "@/lib/toast";

/** Shared copy-to-clipboard behavior with a transient "copied" flag. Each
 *  version renders its own control — only the behavior is shared. */
export function useCopyLink(value: string) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      toast.success("Invite link copied");
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Couldn't copy — select the link manually");
    }
  }, [value]);

  return { copied, copy };
}
