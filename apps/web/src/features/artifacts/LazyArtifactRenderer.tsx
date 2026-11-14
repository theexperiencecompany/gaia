"use client";

import { Skeleton } from "@heroui/skeleton";
import dynamic from "next/dynamic";

/** The artifact renderer, loaded only on surfaces that show an artifact. */
export const LazyArtifactRenderer = dynamic(
  () =>
    import("@/features/artifacts/openui/ArtifactRenderer").then(
      (m) => m.ArtifactRenderer,
    ),
  {
    ssr: false,
    loading: () => <Skeleton className="h-64 w-full rounded-2xl" />,
  },
);
