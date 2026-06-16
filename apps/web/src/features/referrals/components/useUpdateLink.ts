"use client";

import { useState } from "react";

import { toast } from "@/lib/toast";

import { useUpdateReferralCode } from "../hooks/useReferrals";

// Lowercase letters/numbers with single hyphens between (no leading/trailing or
// doubled hyphens), length 3 to 32.
const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/** Inline "customize invite link" edit state. Validates the vanity slug locally
 *  then persists it via PATCH /referrals/code (useUpdateReferralCode); the query
 *  refetch from that mutation refreshes the displayed link. */
export function useUpdateLink(code: string) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(code);
  const update = useUpdateReferralCode();

  const start = () => {
    setDraft(code);
    setEditing(true);
  };

  const cancel = () => {
    setEditing(false);
    setDraft(code);
  };

  const save = () => {
    if (update.isPending) return;
    const nextSlug = draft.trim().toLowerCase();
    if (nextSlug === code) {
      setEditing(false);
      return;
    }
    if (nextSlug.length < 3 || nextSlug.length > 32) {
      toast.error("Use 3 to 32 characters.");
      return;
    }
    if (!SLUG_PATTERN.test(nextSlug)) {
      toast.error("Use lowercase letters, numbers, and single hyphens.");
      return;
    }
    update.mutate(nextSlug, { onSuccess: () => setEditing(false) });
  };

  return {
    editing,
    draft,
    setDraft,
    saving: update.isPending,
    start,
    cancel,
    save,
  };
}
