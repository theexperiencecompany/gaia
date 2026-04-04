"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Tooltip } from "@heroui/tooltip";
import {
  CheckmarkCircle02Icon,
  Delete02Icon,
  Edit02Icon,
  Globe02Icon,
} from "@icons";
import { m } from "motion/react";
import Image from "next/image";
import { useState } from "react";
import { apiService } from "@/lib/api/service";
import type { SocialProfilesResults } from "../../types/websocket";

type SocialProfilesRevealCardProps = SocialProfilesResults;

interface EditableProfile {
  platform: string;
  url: string;
  editingHandle: string;
  isEditing: boolean;
}

const PLATFORM_ICONS: Record<string, string> = {
  twitter: "/images/icons/twitter.webp",
  linkedin: "/images/icons/linkedin.svg",
  github: "/images/icons/github.png",
  instagram: "/images/icons/instagram.svg",
  youtube: "/images/icons/youtube.svg",
  reddit: "/images/icons/macos/reddit.webp",
};

interface PlatformMeta {
  display: string;
  base: string;
}

const PLATFORM_PREFIX: Record<string, PlatformMeta> = {
  twitter: { display: "twitter.com/", base: "https://twitter.com/" },
  linkedin: { display: "linkedin.com/in/", base: "https://linkedin.com/in/" },
  github: { display: "github.com/", base: "https://github.com/" },
  instagram: { display: "instagram.com/", base: "https://instagram.com/" },
  facebook: { display: "facebook.com/", base: "https://facebook.com/" },
  youtube: { display: "youtube.com/@", base: "https://youtube.com/@" },
  medium: { display: "medium.com/@", base: "https://medium.com/@" },
  tiktok: { display: "tiktok.com/@", base: "https://tiktok.com/@" },
  mastodon: {
    display: "mastodon.social/@",
    base: "https://mastodon.social/@",
  },
  bluesky: { display: "bsky.app/profile/", base: "https://bsky.app/profile/" },
  threads: { display: "threads.net/@", base: "https://threads.net/@" },
  reddit: { display: "reddit.com/u/", base: "https://reddit.com/u/" },
};

function urlToHandle(url: string, platform: string): string {
  const meta = PLATFORM_PREFIX[platform];
  if (!meta) return url;
  if (url.startsWith(meta.base)) return url.slice(meta.base.length);
  try {
    const u = new URL(url);
    const path = u.pathname.replace(/^\//, "");
    if (platform === "linkedin") return path.replace(/^in\//, "");
    if (
      ["youtube", "medium", "tiktok", "mastodon", "threads"].includes(platform)
    ) {
      return path.replace(/^@/, "");
    }
    return path;
  } catch {
    return url;
  }
}

function handleToUrl(handle: string, platform: string): string {
  if (!handle) return "";
  if (handle.startsWith("http")) return handle;
  const meta = PLATFORM_PREFIX[platform];
  return meta ? `${meta.base}${handle}` : handle;
}

export function SocialProfilesRevealCard({
  profiles,
}: SocialProfilesRevealCardProps) {
  const [rows, setRows] = useState<EditableProfile[]>(() =>
    (profiles ?? []).map((p) => ({
      platform: p.platform,
      url: p.url,
      editingHandle: urlToHandle(p.url, p.platform),
      isEditing: false,
    })),
  );

  if (!profiles || profiles.length === 0) return null;

  const startEdit = (index: number) => {
    setRows((prev) =>
      prev.map((r, i) =>
        i === index
          ? {
              ...r,
              isEditing: true,
              editingHandle: urlToHandle(r.url, r.platform),
            }
          : r,
      ),
    );
  };

  const commitEdit = async (index: number) => {
    let updatedRows: EditableProfile[] = [];
    setRows((prev) => {
      updatedRows = prev.map((r, i) =>
        i === index
          ? {
              ...r,
              url: handleToUrl(r.editingHandle, r.platform),
              isEditing: false,
            }
          : r,
      );
      return updatedRows;
    });

    try {
      const toSave = updatedRows
        .filter((r) => r.platform && r.url)
        .map(({ platform, url }) => ({ platform, url }));
      await apiService.post("/onboarding/social-profiles", {
        profiles: toSave,
      });
    } catch {
      // silent
    }
  };

  const cancelEdit = (index: number) => {
    setRows((prev) =>
      prev.map((r, i) => (i === index ? { ...r, isEditing: false } : r)),
    );
  };

  const removeRow = (index: number) => {
    setRows((prev) => prev.filter((_, i) => i !== index));
  };

  return (
    <m.div
      className="ml-10.75 overflow-hidden rounded-2xl bg-zinc-800/60 p-4"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 280, damping: 22 }}
    >
      <p className="mb-3 text-xs text-zinc-400">
        Found{" "}
        <span className="font-medium text-zinc-300">{profiles.length}</span>{" "}
        {profiles.length === 1 ? "profile" : "profiles"}
      </p>

      <div className="flex flex-col gap-1.5">
        {rows.map((row, index) => {
          const iconEl = PLATFORM_ICONS[row.platform] ? (
            <Image
              src={PLATFORM_ICONS[row.platform]}
              alt={row.platform}
              width={17}
              height={17}
              unoptimized={PLATFORM_ICONS[row.platform].endsWith(".svg")}
            />
          ) : (
            <Globe02Icon className="size-3.5 shrink-0 text-zinc-600" />
          );

          const startContent = (
            <div className="flex shrink-0 items-center gap-1.5">
              {iconEl}
              <span className="select-none whitespace-nowrap text-sm text-zinc-500">
                {PLATFORM_PREFIX[row.platform]?.display ?? `${row.platform}/`}
              </span>
            </div>
          );

          const endContent = row.isEditing ? (
            <Button
              size="sm"
              color="success"
              variant="flat"
              endContent={
                <CheckmarkCircle02Icon className="size-3.5 min-w-3.5" />
              }
              onPress={() => commitEdit(index)}
            >
              Save
            </Button>
          ) : (
            <div className="flex items-center gap-0.5">
              <Tooltip content="Edit" size="sm">
                <Button
                  isIconOnly
                  size="sm"
                  variant="light"
                  onPress={() => startEdit(index)}
                  aria-label={`Edit ${row.platform}`}
                >
                  <Edit02Icon className="size-3.5 text-zinc-500" />
                </Button>
              </Tooltip>
              <Tooltip content="Remove" size="sm">
                <Button
                  isIconOnly
                  size="sm"
                  variant="light"
                  onPress={() => removeRow(index)}
                  aria-label={`Remove ${row.platform}`}
                >
                  <Delete02Icon className="size-3.5 text-zinc-500" />
                </Button>
              </Tooltip>
            </div>
          );

          return (
            <m.div
              key={`${row.platform}-${index}`}
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{
                delay: index * 0.04,
                duration: 0.25,
                ease: [0.19, 1, 0.22, 1],
              }}
            >
              <Input
                // key forces remount on edit toggle so autoFocus fires correctly
                key={row.isEditing ? "editing" : "viewing"}
                // biome-ignore lint/a11y/noAutofocus: intentional focus on edit
                autoFocus={row.isEditing}
                isReadOnly={!row.isEditing}
                variant="flat"
                placeholder="username"
                value={
                  row.isEditing
                    ? row.editingHandle
                    : urlToHandle(row.url, row.platform)
                }
                onValueChange={(v) =>
                  setRows((prev) =>
                    prev.map((r, i) =>
                      i === index ? { ...r, editingHandle: v } : r,
                    ),
                  )
                }
                onBlur={() => row.isEditing && commitEdit(index)}
                onKeyDown={(e: React.KeyboardEvent) => {
                  if (e.key === "Enter" && row.isEditing) commitEdit(index);
                  if (e.key === "Escape" && row.isEditing) cancelEdit(index);
                }}
                startContent={startContent}
                endContent={endContent}
                classNames={{
                  inputWrapper:
                    "bg-zinc-900 rounded-xl shadow-none data-[hover=true]:bg-zinc-900 group-data-[focus=true]:bg-zinc-900",
                  input: "text-sm text-zinc-300 placeholder:text-zinc-600",
                }}
              />
            </m.div>
          );
        })}
      </div>
    </m.div>
  );
}
