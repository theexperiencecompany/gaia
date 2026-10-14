"use client";

import { Button } from "@heroui/button";
import { Skeleton } from "@heroui/skeleton";
import type { PostmarksResponse } from "@shared/api/generated";
import dynamic from "next/dynamic";

import { usePostmarksQuery } from "../../hooks/usePostmarksQuery";
import { StampCollection } from "./StampCollection";

// maplibre is browser-only, and the globe is the heaviest thing on the page:
// load it on the client, after the copy and the album have painted.
const PostmarksGlobe = dynamic(
  () => import("./PostmarksGlobe").then((module) => module.PostmarksGlobe),
  { ssr: false, loading: () => <Skeleton className="h-full w-full" /> },
);

const GLOBE_FRAME =
  "relative h-[clamp(320px,52vh,480px)] w-full overflow-hidden rounded-3xl bg-zinc-950";

/** Settings > Postmarks: where the user's Air Mail briefs came from. */
export function PostmarksSettings() {
  const { data, isLoading, refetch } = usePostmarksQuery();

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-8">
      <header className="flex flex-col gap-2">
        <h1 className="font-serif text-4xl font-normal tracking-tight text-zinc-100">
          Postmarks
        </h1>
        <p className="max-w-[60ch] text-sm leading-relaxed text-zinc-400">
          Some mornings your brief arrives as Air Mail, stamped from a city
          somewhere in the world. Every stamp you&apos;ve received is kept here.
        </p>
      </header>
      {isLoading && <PostmarksSkeleton />}
      {!isLoading && !data && <PostmarksError onRetry={() => void refetch()} />}
      {data && <PostmarksCollection collection={data} />}
    </div>
  );
}

interface PostmarksCollectionProps {
  collection: PostmarksResponse;
}

function PostmarksCollection({ collection }: PostmarksCollectionProps) {
  const { postmarks, total } = collection;
  return (
    <>
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
      <section className="flex flex-col gap-4">
        <div className="flex items-baseline justify-between">
          <h2 className="text-xs font-medium uppercase tracking-wider text-zinc-500">
            Collection
          </h2>
          <p className="text-sm text-zinc-500 tabular-nums">
            <span className="font-medium text-zinc-100">
              {postmarks.length}
            </span>{" "}
            of {total}
          </p>
        </div>
        <StampCollection postmarks={postmarks} total={total} />
      </section>
    </>
  );
}

function PostmarksSkeleton() {
  return (
    <>
      <Skeleton className={GLOBE_FRAME} />
      <Skeleton className="h-40 w-full rounded-2xl" />
    </>
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
