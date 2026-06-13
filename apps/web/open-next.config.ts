import { defineCloudflareConfig } from "@opennextjs/cloudflare";
import r2IncrementalCache from "@opennextjs/cloudflare/overrides/incremental-cache/r2-incremental-cache";
import { withRegionalCache } from "@opennextjs/cloudflare/overrides/incremental-cache/regional-cache";
import doQueue from "@opennextjs/cloudflare/overrides/queue/do-queue";

export default defineCloudflareConfig({
  // R2 durable store fronted by Cloudflare's regional Cache API so repeat
  // in-region hits skip the R2 round-trip (warm-PoP TTFB ~0.5s).
  incrementalCache: withRegionalCache(r2IncrementalCache, {
    mode: "long-lived",
  }),
  // DO queue runs ISR revalidation for the time-based `revalidate` on landing pages.
  queue: doQueue,
  // Serve cached ISR/SSG pages + RSC prefetches without booting the full NextServer.
  enableCacheInterception: true,
});
