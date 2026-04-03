"use client";

import { Spinner } from "@heroui/spinner";
import { Edit02Icon } from "@icons";
import { AnimatePresence, m } from "motion/react";
import { useState } from "react";
import { apiService } from "@/lib/api/service";
import { WRITING_STYLE_LABEL } from "../../constants/messages";
import type { WritingStyleResults } from "../../types/websocket";

type WritingStyleRevealCardProps = WritingStyleResults;

export function WritingStyleRevealCard({
  style_summary,
  sample_snippets,
}: WritingStyleRevealCardProps) {
  const snippet = sample_snippets?.[0] ?? null;
  const [isEditing, setIsEditing] = useState(false);
  const [editedValue, setEditedValue] = useState(snippet ?? "");
  const [isSaving, setIsSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const handleSave = async () => {
    if (!editedValue.trim() || isSaving) return;
    setIsSaving(true);
    try {
      await apiService.post("/onboarding/writing-style", {
        edited_sample: editedValue.trim(),
      });
      setSaved(true);
      setIsEditing(false);
    } catch {
      // silent — non-blocking
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <m.div
      className="overflow-hidden rounded-2xl bg-zinc-800/60 p-4"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 280, damping: 22 }}
    >
      <p className="mb-2 text-xs text-zinc-400">{WRITING_STYLE_LABEL}</p>

      <m.p
        className="pl-3 text-sm text-zinc-400"
        initial={{ opacity: 0, x: -6 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: 0.06, duration: 0.25, ease: [0.19, 1, 0.22, 1] }}
      >
        {style_summary}
      </m.p>

      <AnimatePresence>
        {snippet && !saved && (
          <m.div
            className="mt-3 pl-3"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ delay: 0.12, duration: 0.25 }}
          >
            {isEditing ? (
              <div className="flex flex-col gap-2">
                <textarea
                  className="w-full resize-none rounded-xl bg-zinc-900 px-3 py-2 text-xs text-zinc-300 placeholder-zinc-600 outline-none focus:ring-1 focus:ring-zinc-600"
                  rows={3}
                  value={editedValue}
                  onChange={(e) => setEditedValue(e.target.value)}
                />
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={handleSave}
                    disabled={isSaving}
                    className="flex items-center gap-1.5 rounded-lg bg-zinc-700 px-3 py-1.5 text-xs font-medium text-zinc-200 transition-colors hover:bg-zinc-600 disabled:opacity-50"
                  >
                    {isSaving ? <Spinner size="sm" color="current" /> : "Save"}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setIsEditing(false);
                      setEditedValue(snippet);
                    }}
                    className="text-xs text-zinc-500 transition-colors hover:text-zinc-300"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex items-start justify-between gap-2">
                <p className="text-xs italic text-zinc-500 leading-relaxed">
                  &ldquo;{snippet}&rdquo;
                </p>
                <button
                  type="button"
                  onClick={() => setIsEditing(true)}
                  className="shrink-0 text-zinc-600 transition-colors hover:text-zinc-400"
                  aria-label="Edit writing style example"
                >
                  <Edit02Icon className="size-3.5" />
                </button>
              </div>
            )}
          </m.div>
        )}

        {saved && (
          <m.p
            key="saved"
            className="mt-2 pl-3 text-xs text-emerald-400"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
          >
            Style saved.
          </m.p>
        )}
      </AnimatePresence>
    </m.div>
  );
}
