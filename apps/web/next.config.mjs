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

// When this checkout is a worktrunk worktree, `apps/web/node_modules` is a
// symlink to the primary worktree's directory (sibling of this repo). The
// default Turbopack root (`../..`, the repo root) considers that an out-of-root
// symlink and refuses to dev. Bump the root one level up — to the parent of
// the repo — so the symlink target stays inside it. Non-worktree checkouts
// (CI, fresh clones, anyone not using `wt`) have a real `node_modules`
// directory, so this codepath never triggers and behavior is unchanged.
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

const nextConfig = {
  productionBrowserSourceMaps: true,
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
    // Change the value here to swap the entire icon variant across the app
    // node:* aliases rewrite Node built-in specifiers to their bare form so
    // Turbopack does not emit chunks named `[externals]_node:foo_*.js` — the
    // colon is illegal on NTFS and breaks `next build` on Windows during
    // standalone output tracing (breaks the Electron Windows installer).
    // See: https://github.com/vercel/next.js/discussions/86194
    // and:  https://nextjs-forum.com/post/1471409705514569798
    resolveAlias: {
      "@icons": "@theexperiencecompany/gaia-icons/solid-rounded",
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
  serverExternalPackages: ["moment", "moment-timezone"],
  experimental: {
    // Inline critical CSS via critters so the first paint doesn't wait on a
    // separate CSS round-trip. Object form (e.g. `{ fonts: true, preload: "swap" }`)
    // silently no-ops in Next 16.1.6 — stick with the boolean.
    optimizeCss: true,
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

    // Keep gaia-icons out of the eager/initial landing chunk.
    // By default, modules reachable from >= 2 chunks get hoisted into a shared
    // common chunk — that's how ~137 icons ended up on the critical path even
    // though most are only referenced by dynamically-imported below-the-fold
    // sections. Scoping this cache group to `chunks: "async"` means icons
    // shared across async sections consolidate into a single async gaia-icons
    // chunk that loads with the first async section, while the handful of
    // icons reachable from initial code (Navbar) stay inlined in the main
    // chunk.
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
    dangerouslyAllowSVG: true,
    minimumCacheTTL: 2_592_000, // 30 days — overrides short upstream Cache-Control (e.g. GitHub's 5 min)
    remotePatterns: [
      {
        protocol: "https",
        hostname: "**",
      },
      {
        protocol: "http",
        hostname: "**",
      },
    ],
  },
  env: {
    NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL,
  },
  pageExtensions: ["js", "jsx", "mdx", "ts", "tsx"],
  async headers() {
    return [
      {
        source: "/_next/static/(.*)",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=31536000, immutable",
          },
        ],
      },
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
        destination: "https://us-assets.i.posthog.com/static/:path*",
      },
      {
        source: "/ingest/:path*",
        destination: "https://us.i.posthog.com/:path*",
      },
      {
        source: "/ingest/flags",
        destination: "https://us.i.posthog.com/flags",
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

  // Uncomment to route browser requests to Sentry through a Next.js rewrite to circumvent ad-blockers.
  // This can increase your server load as well as your hosting bill.
  // Note: Check that the configured route will not match with your Next.js middleware, otherwise reporting of client-
  // side errors will fail.
  // tunnelRoute: "/monitoring",

  // Disable auto-instrumentation to prevent @sentry/node-core + OpenTelemetry from leaking into the bundle
  webpack: {
    autoInstrumentServerFunctions: false,
    autoInstrumentMiddleware: false,
    autoInstrumentAppDirectory: false,
    treeshake: {
      removeDebugLogging: true,
    },
  },

  // Strip unused Sentry features from the client bundle
  bundleSizeOptimizations: {
    excludeDebugStatements: true,
    excludeReplayShadowDom: true,
    excludeReplayIframe: true,
    excludeReplayWorker: true,
  },
});
