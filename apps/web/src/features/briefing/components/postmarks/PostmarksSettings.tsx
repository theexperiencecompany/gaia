"use client";

import { Button } from "@heroui/button";
import { Skeleton } from "@heroui/skeleton";
import type { PostmarksResponse } from "@shared/api/generated";
import dynamic from "next/dynamic";

import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { usePostmarksQuery } from "../../hooks/usePostmarksQuery";
import { StampCollection } from "./StampCollection";

// maplibre is browser-only, and the globe is the heaviest thing on the page:
// load it on the client, after the copy and the album have painted.
const PostmarksGlobe = dynamic(
  () => import("./PostmarksGlobe").then((module) => module.PostmarksGlobe),
  { ssr: false, loading: () => <Skeleton className="h-full w-full" /> },
);

const GLOBE_FRAME = "relative h-[clamp(320px,52vh,480px)] w-full bg-zinc-950";

/** Settings > Postmarks: where the user's Air Mail briefs came from. */
export function PostmarksSettings() {
  const { data, isLoading, refetch } = usePostmarksQuery();

  return (
    <SettingsPage>
      {isLoading && <PostmarksSkeleton />}
      {!isLoading && !data && <PostmarksError onRetry={() => void refetch()} />}
      {data && <PostmarksCollection collection={data} />}
    </SettingsPage>
  );
}

const POSTMARKS_DESCRIPTION =
  "Some mornings your brief arrives as Air Mail, stamped from a city somewhere in the world. Every stamp you've received is kept here.";

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
            of {total}
          </p>
        }
        className="p-4"
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

function PostmarksError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-2xl bg-zinc-900/60 p-10 text-center">
      <p className="text-sm font-medium text-zinc-200">
        Couldn&apos;t load your postmarks
      </p>
      <p className="max-w-sm text-xs text-zinc-500">
        Your stamps are safe. This page just couldn&apos;t reach them.
      </p>
      <Button
        size="sm"
        color="primary"
        variant="flat"
        radius="full"
        className="mt-1 font-medium"
        onPress={onRetry}
      >
        Try again
      </Button>
    </div>
  );
}
