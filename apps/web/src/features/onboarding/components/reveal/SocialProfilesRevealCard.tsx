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
      className="overflow-hidden rounded-2xl bg-zinc-800/60 p-4"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 280, damping: 22 }}
    >
      <p className="mb-2 text-xs text-zinc-400">
        Found{" "}
        <span className="font-medium text-zinc-300">{profiles.length}</span>{" "}
        {profiles.length === 1 ? "profile" : "profiles"}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {profiles.map((profile, index) => (
          <m.span
            key={profile.platform}
            className="rounded-full bg-zinc-700 px-2 py-0.5 text-xs text-zinc-300"
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{
              delay: index * 0.06,
              duration: 0.25,
              ease: [0.19, 1, 0.22, 1],
            }}
          >
            {profile.platform}
          </m.span>
        ))}
      </div>
    </m.div>
  );
}
