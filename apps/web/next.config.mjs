import bundleAnalyzer from "@next/bundle-analyzer";
import createMDX from "@next/mdx";
import { withSentryConfig } from "@sentry/nextjs";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

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
  // Explicitly set turbopack workspace root to silence inference warning
  turbopack: {
    root: path.join(__dirname, "../.."),
    // Change the value here to swap the entire icon variant across the app
    resolveAlias: {
      "@icons": "@theexperiencecompany/gaia-icons/solid-rounded",
      // cytoscape: emptyStub,
      // "cytoscape-cose-bilkent": emptyStub,
      // "cytoscape-fcose": emptyStub,
    },
  },
  serverExternalPackages: ["moment", "moment-timezone"],
  experimental: {
    optimizePackageImports: [
      "mermaid",
      "react-syntax-highlighter",
      "cytoscape",
      "@theexperiencecompany/gaia-icons/solid-rounded",
      // "@heroui/*",
    ],
  },
  webpack: (config) => {
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
        destination: "/sitemap-index",
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

export default withSentryConfig(withBundleAnalyzer(withMDX(nextConfig)), {
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
