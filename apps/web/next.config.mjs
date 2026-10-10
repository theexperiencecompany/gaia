import bundleAnalyzer from "@next/bundle-analyzer";
import createMDX from "@next/mdx";
import { withSentryConfig } from "@sentry/nextjs";
import fs from "fs";
import createNextIntlPlugin from "next-intl/plugin";
import path from "path";
import { fileURLToPath } from "url";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// In a worktrunk worktree, apps/web/node_modules symlinks to the primary
// worktree's dir, which the default Turbopack root (../..) treats as an
// out-of-root symlink and refuses; bump root up one level so it stays inside (non-worktree checkouts have a real node_modules and are unaffected).
const webNodeModules = path.join(__dirname, "node_modules");
const isWorktreeWithSharedDeps =
  fs.existsSync(webNodeModules) &&
  fs.lstatSync(webNodeModules).isSymbolicLink();
const turbopackRoot = isWorktreeWithSharedDeps
  ? path.join(__dirname, "../../..")
  : path.join(__dirname, "../..");

const withBundleAnalyzer = bundleAnalyzer({
  enabled: process.env.ANALYZE === "true",
});

// The Cloudflare Image Resizing loader (/cdn-cgi/image/) is only valid served
// through the Cloudflare edge (see cf:build/deploy/preview in package.json);
// every other build (Docker, Electron) leaves it unset and falls back to Next's built-in optimizer, else images 404 off-edge.
const useCloudflareImageLoader = process.env.IMAGE_LOADER === "cloudflare";

// PostHog proxies through /ingest to stay first-party and survive ad blockers,
// following NEXT_PUBLIC_POSTHOG_HOST for region-correct ingestion. PostHog Cloud
// serves SDK bundles from a sibling <region>-assets host; self-hosted uses the same origin (the unmatched fallback).
const posthogHost = (
  process.env.NEXT_PUBLIC_POSTHOG_HOST || "https://us.i.posthog.com"
).replace(/\/+$/, "");
const posthogAssetsHost = posthogHost.replace(
  /^(https?:\/\/)(us|eu)\.i\.posthog\.com$/,
  "$1$2-assets.i.posthog.com",
);

const nextConfig = {
  // Dev only (ignored in prod): Next 15+ refuses to serve /_next/* to any origin
  // but localhost, so opening the dev server from a phone on LAN/Tailscale got
  // 403 scripts and never hydrated. These are the private ranges devices sit on.
  allowedDevOrigins: [
    "192.168.*.*",
    "10.*.*.*",
    "172.*.*.*",
    "100.*.*.*",
    "*.local",
    "*.ts.net",
    "*.*.ts.net",
  ],
  // Next's dev-server dedup locks on distDir, refusing a second `next dev` for
  // the same directory. A dedicated dist dir (agents driving the app while a
  // human dev server runs) lifts that without touching the default build.
  ...(process.env.NEXT_DIST_DIR ? { distDir: process.env.NEXT_DIST_DIR } : {}),
  productionBrowserSourceMaps: true,
  // OpenNext file-traces every public/*.wasm into the Worker (even in unrelated
  // routes' .nft.json), collecting the desktop-only ~12MiB wake-word WASM past
  // Cloudflare's 10MiB limit. Exclude it on the Cloudflare build; Electron's standalone build copies public/ wholesale, unaffected.
  ...(useCloudflareImageLoader
    ? { outputFileTracingExcludes: { "*": ["**/public/wake-word/**"] } }
    : {}),
  compiler: {
    removeConsole:
      process.env.NODE_ENV === "production"
        ? {
            exclude: ["error"],
          }
        : false,
  },
  reactStrictMode: true,
  // Enable standalone output for Electron desktop app bundling
  // This creates a minimal production server with all dependencies
  output: "standalone",
  // Explicitly set turbopack workspace root to silence inference warning.
  // Resolved above as `turbopackRoot` to handle worktrunk worktrees correctly.
  turbopack: {
    root: turbopackRoot,
    // node:* aliases rewrite Node built-in specifiers to bare form so Turbopack
    // doesn't emit chunks named [externals]_node:foo_*.js — the colon is illegal
    // on NTFS and breaks `next build` on Windows during standalone tracing (breaks the Electron Windows installer). See vercel/next.js#86194.
    resolveAlias: {
      "@icons": "@theexperiencecompany/gaia-icons/solid-rounded",
      // The wake-word ONNX runtime (onnxruntime-web + ~12MiB WASM) is desktop-only
      // (/wake-listener runs only in Electron). Turbopack still pulls its WASM
      // into the route's server chunk on Cloudflare, past the 10MiB Worker limit — stub it there; the Electron build (IMAGE_LOADER unset) keeps the real runtime.
      ...(useCloudflareImageLoader
        ? {
            "onnxruntime-web": "./scripts/empty-module.mjs",
            "onnxruntime-web/wasm": "./scripts/empty-module.mjs",
          }
        : {}),
      // Stub out unused heavy deps (mirrors the webpack hook below). Webpack's
      // `alias: false` doesn't exist for Turbopack — we point to a tiny empty
      // module that exports a no-op proxy.
      cytoscape: "./scripts/empty-module.mjs",
      "cytoscape-cose-bilkent": "./scripts/empty-module.mjs",
      "cytoscape-fcose": "./scripts/empty-module.mjs",
      "node:inspector": "inspector",
      "node:fs": "fs",
      "node:fs/promises": "fs/promises",
      "node:path": "path",
      "node:stream": "stream",
      "node:stream/web": "stream/web",
      "node:url": "url",
      "node:util": "util",
      "node:crypto": "crypto",
      "node:buffer": "buffer",
      "node:os": "os",
      "node:child_process": "child_process",
      "node:http": "http",
      "node:https": "https",
      "node:net": "net",
      "node:tls": "tls",
      "node:zlib": "zlib",
      "node:events": "events",
      "node:async_hooks": "async_hooks",
      "node:assert": "assert",
      "node:querystring": "querystring",
      "node:worker_threads": "worker_threads",
      "node:process": "process",
      "node:perf_hooks": "perf_hooks",
      "node:diagnostics_channel": "diagnostics_channel",
    },
  },
  experimental: {
    // prefetchInlining stays OFF until OpenNext serves Next's segment-prefetch
    // protocol (as of @opennextjs/cloudflare 1.20.2 it doesn't — /_tree gets the
    // full build-time RSC payload, no x-nextjs-postponed header). With inlining on, the client marks the route cache stale and refetches at ~5 req/s per visible <Link> (observed heygaia.io /signup, 2026-08-18).
    prefetchInlining: false,
    // optimizeCss stays OFF: (1) crashes the Cloudflare/OpenNext bundle (unconditional
    // cpSync of .next/static/css, which Turbopack doesn't emit → ENOENT); (2) tested
    // on webpack it does NOT inline critical CSS (render-blocking <link>s remain) — no FCP benefit, only added critters risk.
    optimizePackageImports: [
      "mermaid",
      "react-syntax-highlighter",
      "cytoscape",
      "@theexperiencecompany/gaia-icons/solid-rounded",
      "@heroui/button",
      "@heroui/chip",
      "@heroui/modal",
      "@heroui/system",
      "@heroui/tooltip",
      "@heroui/select",
      "@heroui/scroll-shadow",
      "@heroui/react",
      "@heroui/skeleton",
      "@heroui/spinner",
      "lucide-react",
      "@radix-ui/react-icons",
      "@radix-ui/react-visually-hidden",
      "date-fns",
      "lodash",
      "motion/react",
      "motion",
      "schema-dts",
    ],
  },
  webpack: (config, { isServer }) => {
    // Exclude cytoscape from bundle since it's not used (both client and server)
    config.resolve.alias = {
      ...config.resolve.alias,
      cytoscape: false,
      "cytoscape-cose-bilkent": false,
      "cytoscape-fcose": false,
    };
    // Alias @icons to the active icon variant — change here to swap the entire set
    config.resolve.alias["@icons"] =
      "@theexperiencecompany/gaia-icons/solid-rounded";

    // Desktop-only wake-word ONNX runtime — stub out of the Cloudflare build
    // so its WASM never lands in the Worker script (see turbopack alias above).
    if (useCloudflareImageLoader) {
      config.resolve.alias["onnxruntime-web"] = false;
      config.resolve.alias["onnxruntime-web/wasm"] = false;
    }

    // Keep gaia-icons out of the eager initial chunk: by default, modules reachable
    // from ≥2 chunks hoist into a shared common chunk, putting ~137 icons on the
    // critical path though most are only used by dynamically-imported below-the-fold sections; scoping to chunks:"async" consolidates them into one async chunk while Navbar's icons stay inlined in main.
    if (!isServer && config.optimization?.splitChunks) {
      const splitChunks = config.optimization.splitChunks;
      splitChunks.cacheGroups = {
        ...splitChunks.cacheGroups,
        gaiaIcons: {
          test: /[\\/]node_modules[\\/]@theexperiencecompany[\\/]gaia-icons[\\/]/,
          name: "gaia-icons-async",
          chunks: "async",
          priority: 40,
          reuseExistingChunk: true,
          enforce: true,
        },
      };
    }

    return config;
  },
  images: {
    // Offload optimization to Cloudflare Image Resizing (/cdn-cgi/image/) via a
    // custom loader — edge-cached, off the worker. Requires Transformations enabled
    // on the zone; gated on the Cloudflare build (see image-loader.ts), else falls through to Next's built-in optimizer.
    ...(useCloudflareImageLoader
      ? { loader: "custom", loaderFile: "./image-loader.ts" }
      : {}),
    // Kept on: remote SVGs are relied upon (simpleicons.org logos, ProductHunt
    // featured.svg, integration icon URLs). Next serves remote SVGs with a
    // restrictive image-pipeline CSP, so this is scoped narrowly.
    dangerouslyAllowSVG: true,
    // Hardening required alongside dangerouslyAllowSVG: optimizer responses are
    // marked as downloads so a directly-navigated SVG can't execute as a live
    // document, and CSP blocks scripts/sandboxes it; <img> loads ignore Content-Disposition/CSP — only top-level navigation is affected.
    contentDispositionType: "attachment",
    contentSecurityPolicy: "default-src 'self'; script-src 'none'; sandbox;",
    minimumCacheTTL: 2_592_000, // 30 days — overrides short upstream Cache-Control (e.g. GitHub's 5 min)
    // Image sources are open-ended (OAuth avatars, LLM/backend integration icons,
    // Unsplash, map tiles), so the https host set can't be enumerated without
    // breaking images; http is dropped since every real source is https and plaintext fetches are an SSRF/mixed-content risk.
    remotePatterns: [
      {
        protocol: "https",
        hostname: "**",
      },
    ],
  },
  env: {
    NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL,
  },
  // *.dev.tsx/*.dev.ts route only in development; production builds never
  // register them, so their pages/layouts/imports are absent from the build
  // graph entirely (no chunks, no compile time). Used by demo/debug routes under app/[locale]/dev/*.
  pageExtensions: [
    "js",
    "jsx",
    "mdx",
    "ts",
    "tsx",
    ...(process.env.NODE_ENV === "development" ? ["dev.ts", "dev.tsx"] : []),
  ],
  async headers() {
    return [
      // Baseline security headers on every route. A full Content-Security-Policy
      // is intentionally deferred — a wrong CSP silently breaks the app and can't
      // be verified by a build alone, so it needs its own scoped rollout.
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          {
            key: "Referrer-Policy",
            value: "strict-origin-when-cross-origin",
          },
        ],
      },
      // /_next/static/*: intentionally NOT setting a custom Cache-Control here.
      // Next content-hashes chunk filenames in prod, so its default immutable
      // headers are correct; in dev, Turbopack reuses filenames across rebuilds, so a custom long-cache header would pin a stale bundle and break hot reloads.
      {
        source: "/images/(.*)",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=2592000, stale-while-revalidate=604800",
          },
        ],
      },
      {
        source: "/site.webmanifest",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=86400, stale-while-revalidate=604800",
          },
        ],
      },
    ];
  },
  async rewrites() {
    return [
      {
        source: "/sitemap.xml",
        destination: "/api/sitemap-xml",
      },
      {
        source: "/ingest/static/:path*",
        destination: `${posthogAssetsHost}/static/:path*`,
      },
      {
        source: "/ingest/array/:path*",
        destination: `${posthogAssetsHost}/array/:path*`,
      },
      {
        source: "/ingest/:path*",
        destination: `${posthogHost}/:path*`,
      },
      {
        source: "/ingest/flags",
        destination: `${posthogHost}/flags`,
      },
    ];
  },
  // This is required to support PostHog trailing slash API requests
  skipTrailingSlashRedirect: true,
};

const withMDX = createMDX({
  // Add markdown plugins here, as desired
});

export default withSentryConfig(
  withNextIntl(withBundleAnalyzer(withMDX(nextConfig))),
  {
  // For all available options, see:
  // https://www.npmjs.com/package/@sentry/webpack-plugin#options

  org: "gaia-la",
  project: "gaia-frontend",

  // Only print logs for uploading source maps in CI
  silent: !process.env.CI,

  // For all available options, see:
  // https://docs.sentry.io/platforms/javascript/guides/nextjs/manual-setup/

  // Upload a larger set of source maps for prettier stack traces (increases build time)
  widenClientFileUpload: true,

  // Keep source maps in the build output so browsers can load them (don't delete after Sentry upload)
  hideSourceMaps: false,

  // Uncomment to route Sentry requests through a Next.js rewrite to bypass
  // ad-blockers (raises server load/hosting cost); ensure the route doesn't collide with Next.js middleware or client-side error reporting fails.
  // tunnelRoute: "/monitoring",

  // Sentry's autoInstrument* flags only work under `webpack:` (unsupported with
  // Turbopack per deprecation warning); bundleSizeOptimizations.excludeTracing/
  // PerformanceMonitoring covers both bundlers instead.
  webpack: {
    autoInstrumentServerFunctions: false,
    autoInstrumentMiddleware: false,
    autoInstrumentAppDirectory: false,
    treeshake: {
      removeDebugLogging: true,
    },
  },

  // Strip unused Sentry features: excludeTracing kills the @opentelemetry +
  // @sentry/node-core + protobuf tracing chunk (~1.5MB raw server-side) — safe
  // since server Sentry isn't initialized (sentry.server.config.ts is empty); excludePerformanceMonitoring drops the rest of the perf SDK.
  bundleSizeOptimizations: {
    excludeDebugStatements: true,
    excludeReplayShadowDom: true,
    excludeReplayIframe: true,
    excludeReplayWorker: true,
    excludeTracing: true,
    excludePerformanceMonitoring: true,
  },
});
