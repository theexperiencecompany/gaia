import { defineCloudflareConfig } from "@opennextjs/cloudflare";
import r2IncrementalCache from "@opennextjs/cloudflare/overrides/incremental-cache/r2-incremental-cache";
import { withRegionalCache } from "@opennextjs/cloudflare/overrides/incremental-cache/regional-cache";
import doQueue from "@opennextjs/cloudflare/overrides/queue/do-queue";
import doShardedTagCache from "@opennextjs/cloudflare/overrides/tag-cache/do-sharded-tag-cache";
import { withFilter } from "@opennextjs/cloudflare/overrides/tag-cache/tag-cache-filter";
import { PUBLIC_PAGE_TAGS } from "./src/lib/publicPages";

export default defineCloudflareConfig({
  // R2 durable store fronted by Cloudflare's regional Cache API so repeat
  // in-region hits skip the R2 round-trip (warm-PoP TTFB ~0.5s).
  incrementalCache: withRegionalCache(r2IncrementalCache, {
    mode: "long-lived",
  }),
  // Records when /api/public-pages/revalidate cleared a route, so a cached page older than that is rebuilt.
  // Filtered to the routes it can clear: every other page is served without a Durable Object lookup.
  tagCache: withFilter({
    tagCache: doShardedTagCache(),
    filterFn: (tag) =>
      PUBLIC_PAGE_TAGS.has(typeof tag === "string" ? tag : tag.tag),
  }),
  // DO queue runs ISR revalidation for the time-based `revalidate` on landing pages.
  queue: doQueue,
  // Serve cached ISR/SSG pages + RSC prefetches without booting the full NextServer.
  enableCacheInterception: true,
});
