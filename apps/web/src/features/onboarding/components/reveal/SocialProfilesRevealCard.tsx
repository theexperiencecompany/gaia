"use client";

import { Edit02Icon, PlusSignIcon } from "@icons";
import { AnimatePresence, m } from "motion/react";
import { useState } from "react";
import { apiService } from "@/lib/api/service";
import type { SocialProfilesResults } from "../../types/websocket";

type SocialProfilesRevealCardProps = SocialProfilesResults;

interface EditableProfile {
  platform: string;
  url: string;
  editingUrl: string;
  isEditing: boolean;
}

const PLATFORM_LABELS: Record<string, string> = {
  twitter: "X / Twitter",
  linkedin: "LinkedIn",
  github: "GitHub",
  instagram: "Instagram",
  facebook: "Facebook",
  youtube: "YouTube",
  medium: "Medium",
  tiktok: "TikTok",
  mastodon: "Mastodon",
  bluesky: "Bluesky",
  threads: "Threads",
};

export function SocialProfilesRevealCard({
  profiles,
}: SocialProfilesRevealCardProps) {
  const [rows, setRows] = useState<EditableProfile[]>(() =>
    (profiles ?? []).map((p) => ({
      platform: p.platform,
      url: p.url,
      editingUrl: p.url,
      isEditing: false,
    })),
  );
  const [saved, setSaved] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isDirty, setIsDirty] = useState(false);

  if (!profiles || profiles.length === 0) return null;

  const startEdit = (index: number) => {
    setRows((prev) =>
      prev.map((r, i) => (i === index ? { ...r, isEditing: true } : r)),
    );
  };

  const commitEdit = (index: number) => {
    setRows((prev) =>
      prev.map((r, i) =>
        i === index ? { ...r, url: r.editingUrl, isEditing: false } : r,
      ),
    );
    setIsDirty(true);
  };

  const addRow = () => {
    setRows((prev) => [
      ...prev,
      { platform: "", url: "", editingUrl: "", isEditing: true },
    ]);
    setIsDirty(true);
  };

  const handleSave = async () => {
    if (isSaving) return;
    setIsSaving(true);
    try {
      const toSave = rows
        .filter((r) => r.platform && r.url)
        .map(({ platform, url }) => ({ platform, url }));
      await apiService.post("/onboarding/social-profiles", {
        profiles: toSave,
      });
      setSaved(true);
      setIsDirty(false);
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
      <p className="mb-3 text-xs text-zinc-400">
        Found{" "}
        <span className="font-medium text-zinc-300">{profiles.length}</span>{" "}
        {profiles.length === 1 ? "profile" : "profiles"}
      </p>

      <div className="flex flex-col gap-2">
        {rows.map((row, index) => (
          <m.div
            key={`${row.platform}-${index}`}
            className="flex items-center gap-2"
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{
              delay: index * 0.05,
              duration: 0.25,
              ease: [0.19, 1, 0.22, 1],
            }}
          >
            {row.isEditing ? (
              <>
                <input
                  className="w-24 shrink-0 rounded-lg bg-zinc-900 px-2 py-1 text-xs text-zinc-300 placeholder-zinc-600 outline-none focus:ring-1 focus:ring-zinc-600"
                  placeholder="platform"
                  value={row.platform}
                  onChange={(e) =>
                    setRows((prev) =>
                      prev.map((r, i) =>
                        i === index ? { ...r, platform: e.target.value } : r,
                      ),
                    )
                  }
                />
                <input
                  className="min-w-0 flex-1 rounded-lg bg-zinc-900 px-2 py-1 text-xs text-zinc-300 placeholder-zinc-600 outline-none focus:ring-1 focus:ring-zinc-600"
                  placeholder="https://..."
                  value={row.editingUrl}
                  onChange={(e) =>
                    setRows((prev) =>
                      prev.map((r, i) =>
                        i === index ? { ...r, editingUrl: e.target.value } : r,
                      ),
                    )
                  }
                  onKeyDown={(e) => {
                    if (e.key === "Enter") commitEdit(index);
                  }}
                />
                <button
                  type="button"
                  onClick={() => commitEdit(index)}
                  className="shrink-0 rounded px-2 py-0.5 text-xs text-zinc-400 transition-colors hover:text-zinc-200"
                >
                  Done
                </button>
              </>
            ) : (
              <>
                <span className="w-20 shrink-0 text-xs font-medium text-zinc-300">
                  {PLATFORM_LABELS[row.platform] ?? row.platform}
                </span>
                <span className="min-w-0 flex-1 truncate text-xs text-zinc-500">
                  {row.url}
                </span>
                <button
                  type="button"
                  onClick={() => startEdit(index)}
                  className="shrink-0 text-zinc-600 transition-colors hover:text-zinc-400"
                  aria-label={`Edit ${row.platform} profile`}
                >
                  <Edit02Icon className="size-3" />
                </button>
              </>
            )}
          </m.div>
        ))}
      </div>

      <div className="mt-3 flex items-center gap-3">
        <button
          type="button"
          onClick={addRow}
          className="flex items-center gap-1 text-xs text-zinc-500 transition-colors hover:text-zinc-300"
        >
          <PlusSignIcon className="size-3" />
          Add profile
        </button>

        <AnimatePresence>
          {isDirty && !saved && (
            <m.button
              type="button"
              onClick={handleSave}
              disabled={isSaving}
              className="rounded-lg bg-zinc-700 px-3 py-1 text-xs font-medium text-zinc-200 transition-colors hover:bg-zinc-600 disabled:opacity-50"
              initial={{ opacity: 0, x: -4 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0 }}
            >
              {isSaving ? "Saving…" : "Save"}
            </m.button>
          )}
          {saved && (
            <m.span
              key="saved"
              className="text-xs text-emerald-400"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
            >
              Saved.
            </m.span>
          )}
        </AnimatePresence>
      </div>
    </m.div>
  );
}
