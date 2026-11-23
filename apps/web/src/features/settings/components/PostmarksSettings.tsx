"use client";

import { Skeleton } from "@heroui/react";
import type { PostmarksResponse } from "@shared/api/generated";
import { useQuery } from "@tanstack/react-query";

import { LoadError } from "@/components/shared/LoadError";
import {
  PostmarksGlobe,
  postmarksQuery,
  StampCollection,
} from "@/features/briefing";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";

const GLOBE_FRAME = "relative h-[clamp(320px,52vh,480px)] w-full bg-zinc-950";

/** Settings > Postmarks: where the user's Air Mail briefs came from. */
export function PostmarksSettings() {
  const { data, isLoading, refetch } = useQuery(postmarksQuery());

  return (
    <SettingsPage>
      {isLoading && <PostmarksSkeleton />}
      {!isLoading && !data && (
        <LoadError
          title="Couldn't load your postmarks"
          description="Your stamps are safe. This page just couldn't reach them."
          onRetry={() => void refetch()}
        />
      )}
      {data && <PostmarksCollection collection={data} />}
    </SettingsPage>
  );
}

const POSTMARKS_DESCRIPTION =
  "When your brief arrives as Air Mail, it is posted from a city somewhere in the world and carries that city's stamp. Each new city is kept here, and the album fills in one morning at a time.";

interface PostmarksCollectionProps {
  collection: PostmarksResponse;
}

function PostmarksCollection({ collection }: PostmarksCollectionProps) {
  const { postmarks, total } = collection;
  return (
    <>
      <SettingsSection title="Postmarks" description={POSTMARKS_DESCRIPTION}>
        <section aria-label="Globe of collected stamps" className={GLOBE_FRAME}>
          <PostmarksGlobe postmarks={postmarks} />
          {postmarks.length === 0 && (
            <div className="pointer-events-none absolute inset-x-0 bottom-0 flex flex-col gap-1 bg-gradient-to-t from-zinc-950 via-zinc-950/80 to-transparent p-6 pt-16">
              <p className="text-sm font-medium text-zinc-100">No stamps yet</p>
              <p className="text-xs text-zinc-400">
                Your first Air Mail brief lights its city on this globe.
              </p>
            </div>
          )}
        </section>
      </SettingsSection>
      <SettingsSection
        title="Collection"
        titleAccessory={
          <p className="ml-auto text-sm text-zinc-500 tabular-nums">
            <span className="font-medium text-zinc-100">
              {postmarks.length}
            </span>{" "}
            of {total} cities
          </p>
        }
        className="p-5"
      >
        <StampCollection postmarks={postmarks} total={total} />
      </SettingsSection>
    </>
  );
}

function PostmarksSkeleton() {
  return (
    <SettingsSection title="Postmarks" description={POSTMARKS_DESCRIPTION}>
      <Skeleton className={GLOBE_FRAME} />
    </SettingsSection>
  );
}
