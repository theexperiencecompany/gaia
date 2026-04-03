import type { KnipConfig } from "knip";

const config: KnipConfig = {
  // ─── Global: suppress exports/types for dynamically-consumed files ───
  // ignoreIssues is root-only (not valid at workspace level).
  ignoreIssues: {
    // OpenUI: components resolved by name via @openuidev/react-lang Renderer
    "apps/web/src/config/openui/components/**": ["exports", "types"],
    "apps/web/src/config/openui/genericLibrary.tsx": ["exports", "types"],

    // Tool/message registries: keys consumed via dynamic iteration
    "apps/web/src/config/registries/toolRegistry.ts": ["exports", "types"],
    "apps/web/src/config/registries/baseMessageRegistry.ts": [
      "exports",
      "types",
    ],

    // SEO programmatic routes: data consumed by [slug] generateStaticParams()
    "apps/web/src/features/alternatives/data/**": ["exports", "types"],
    "apps/web/src/features/comparisons/data/**": ["exports", "types"],
    "apps/web/src/features/glossary/data/**": ["exports", "types"],
    "apps/web/src/features/personas/data/**": ["exports", "types"],
    "apps/web/src/features/integrations/data/combosData.ts": [
      "exports",
      "types",
    ],

    // i18n: exports consumed by next-intl framework wiring
    "apps/web/src/i18n/**": ["exports", "types"],

    // Fonts: consumed in layout via CSS variable injection
    "apps/web/src/app/fonts/index.ts": ["exports"],

    // Landing page demos: persona-specific demo data resolved by slug at runtime
    "apps/web/src/features/landing/components/demo/*-demo/*Constants*": [
      "exports",
    ],
    "apps/web/src/features/landing/components/demo/constants.ts": [
      "exports",
      "types",
    ],
    "apps/web/src/features/landing/components/demo/workflowsDemoData.tsx": [
      "exports",
      "types",
    ],
    "apps/web/src/features/landing/components/demo/todo-demo/*": ["exports"],
    "apps/web/src/features/landing/components/demo/workflow-demo/*": [
      "exports",
    ],
  },

  // Types/interfaces re-exported for consumers but only used in the same file
  ignoreExportsUsedInFile: {
    interface: true,
    type: true,
  },

  // Exclude non-app files from unused file detection
  ignore: [
    // Agent skill templates (not app code, used by Claude Code skill system)
    ".agents/skills/**",
    ".claude/skills/**",
  ],

  // Binaries provided by monorepo root, mise, or Nx (not in each package.json)
  ignoreBinaries: [
    "biome",
    "clean",
    "check",
    "fix",
    "format",
    "type",
    "deploy-commands",
    "mise",
    "python3",
    "python",
    "source-map-explorer",
    "android",
    "ios",
    "web",
    "eslint",
    "prettier",
    "lsof",
    "netstat",
    "tasklist",
    "powershell",
    "iex",
  ],

  // ─── Workspace definitions ───────────────────────────────────────────
  workspaces: {
    // ── Root ──────────────────────────────────────────────────────────
    ".": {
      ignoreDependencies: [
        // Hoisted for React Native / Expo resolution
        "@react-navigation/native",
        "@react-navigation/native-stack",
        "@swc/helpers",
        // React/ReactDOM are peer deps consumed by all workspaces
        "react",
        "react-dom",
      ],
    },

    // ── Web App ──────────────────────────────────────────────────────
    "apps/web": {
      entry: [
        // Next.js App Router conventions
        "src/app/**/page.{ts,tsx}",
        "src/app/**/layout.{ts,tsx}",
        "src/app/**/loading.{ts,tsx}",
        "src/app/**/error.{ts,tsx}",
        "src/app/**/not-found.{ts,tsx}",
        "src/app/**/template.{ts,tsx}",
        "src/app/**/default.{ts,tsx}",
        "src/app/**/route.{ts,tsx}",
        "src/app/**/middleware.{ts,tsx}",
        "src/middleware.{ts,tsx}",
        "src/app/**/opengraph-image.{ts,tsx}",
        "src/app/**/twitter-image.{ts,tsx}",
        "src/app/**/sitemap.{ts,tsx}",
        "src/app/**/robots.{ts,tsx}",
        "src/app/**/manifest.{ts,tsx}",
        "src/app/api/**/*.{ts,tsx}",
        // Global styles (Tailwind entry)
        "src/app/styles/globals.css",
        // next.config
        "next.config.mjs",
        "open-next.config.ts",
      ],
      project: ["src/**/*.{ts,tsx}", "!src/**/*.test.{ts,tsx}"],

      ignoreDependencies: [
        // Next.js image optimization (implicitly required, no direct import)
        "sharp",
        // Used by SWC compilation (no direct import in source)
        "@swc-node/register",
        "@swc/core",
        // Used by next-mdx-remote or mdx compilation pipeline
        "mdx",
        "@types/mdx",
      ],
    },

    // ── Desktop App ──────────────────────────────────────────────────
    "apps/desktop": {
      entry: ["electron.vite.config.ts", "src/**/*.{ts,tsx}"],
      ignoreDependencies: ["wait-on"],
    },

    // ── Mobile App ───────────────────────────────────────────────────
    "apps/mobile": {
      entry: ["metro.config.js", "src/**/*.{ts,tsx}", "app/**/*.{ts,tsx}"],
      ignoreDependencies: [
        "metro-minify-terser",
        // Expo plugins (consumed in app.json/app.config.js, not imported)
        "expo-auth-session",
        "expo-blur",
      ],
    },

    // ── Bots (umbrella) ──────────────────────────────────────────────
    "apps/bots": {
      ignoreDependencies: [
        "@gaia/bot-discord",
        "@gaia/bot-slack",
        "@gaia/bot-telegram",
        "@gaia/bot-whatsapp",
      ],
    },

    // ── CLI Package ──────────────────────────────────────────────────
    "packages/cli": {
      entry: ["src/index.{ts,tsx}", "src/commands/**/*.{ts,tsx}"],
    },

    // ── Shared TS Library ────────────────────────────────────────────
    "libs/shared/ts": {
      entry: ["src/index.ts"],
      includeEntryExports: false, // library exports consumed by other workspaces
    },
  },
};

export default config;
