"use client";

import { Skeleton } from "@heroui/react";
import dynamic from "next/dynamic";

/**
 * maplibre is browser-only, and the globe is the heaviest thing on its page:
 * it loads on the client, after the copy and the album have painted.
 */
export const PostmarksGlobe = dynamic(
  () => import("./PostmarksGlobe").then((module) => module.PostmarksGlobe),
  { ssr: false, loading: () => <Skeleton className="h-full w-full" /> },
);
