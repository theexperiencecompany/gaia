"use client";

import { m } from "motion/react";
import type { SocialProfilesResults } from "../../types/websocket";

type SocialProfilesRevealCardProps = SocialProfilesResults;

export function SocialProfilesRevealCard({
  profiles,
}: SocialProfilesRevealCardProps) {
  if (!profiles || profiles.length === 0) {
    return null;
  }

  return (
    <m.div
      className="rounded-xl bg-zinc-800/60 p-4"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      <p className="mb-2 text-xs text-zinc-400">
        Found{" "}
        <span className="font-medium text-zinc-300">{profiles.length}</span>{" "}
        {profiles.length === 1 ? "profile" : "profiles"}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {profiles.map((profile) => (
          <span
            key={profile.platform}
            className="rounded-full bg-zinc-700 px-2 py-0.5 text-xs text-zinc-300"
          >
            {profile.platform}
          </span>
        ))}
      </div>
    </m.div>
  );
}
