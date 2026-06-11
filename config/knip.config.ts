import type { KnipConfig } from "knip";

// knip — TS/JS dead-code detection (scripts/dead-code-check.sh + CI, --strict).
// Only suppress when a symbol is genuinely consumed in a way knip can't trace
// (dynamic-by-name renderers, framework-by-convention files, config/CSS-subpath
// imports, parked WIP features). Never add an entry to silence a real finding —
// if nothing uses it, delete the code or the dependency. Every entry needs a
// one-line reason; entries without a live consumer should be removed.
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

    // Calendar support modules: the store/utils/date helpers live outside
    // features/calendar/** (ignored as a parked feature) but are consumed only
    // by it. Suppress their export/type findings so the parked feature stays
    // intact for re-enablement. TODO(team): fold in with the calendar decision.
    "apps/web/src/stores/calendarStore.ts": ["exports", "types"],
    "apps/web/src/utils/calendar/**": ["exports", "types"],
    "apps/web/src/utils/date/calendarDateUtils.ts": ["exports", "types"],
    "apps/web/src/types/features/calendarTypes.ts": ["exports", "types"],

    // Notification enums mirror the backend ActionStyle contract
    // (apps/api/.../notification_models.py). Members like PRIMARY/SECONDARY may
    // be unused in TS today but are valid values the API can serialize, so they
    // must stay in the enum for correct deserialization.
    "libs/shared/ts/src/types/notification.ts": ["enumMembers"],

    // i18n: exports consumed by next-intl framework wiring
    "apps/web/src/i18n/**": ["exports", "types"],

    // Fonts: consumed in layout via CSS variable injection
    "apps/web/src/app/fonts/index.ts": ["exports"],

    // Auto-generated icon path data (DO NOT EDIT): the generator emits both
    // `iconPaths` and `getIconPaths`; only the latter is consumed.
    "apps/web/src/config/iconPaths.generated.ts": ["exports"],

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

    // Builtin docgen skill templates: .mjs/.typ/.py/.tex files materialized into
    // the agent workspace and executed by the skills' build.sh scripts (e.g.
    // `node report.mjs`), never imported as modules — so knip reads them as
    // unused files.
    "apps/api/app/agents/skills/builtin/**",

    // SEO content source-of-truth: human-edited `entries/*.ts` are read by the
    // static-data codegen (scripts/extract-static-data*, which knip ignores) and
    // emitted to public/data/{feature}/*.json — the runtime fetches the JSON via
    // the Cloudflare ASSETS binding, so the .ts sources are never bundled.
    "apps/web/src/features/alternatives/data/entries/**",
    "apps/web/src/features/comparisons/data/entries/**",
    "apps/web/src/features/integrations/data/combosData-*.ts",

    // Parked feature: the /calendar route renders notFound() with its
    // CalendarPage import commented out (app/[locale]/(main)/calendar/page.tsx).
    // The components are intact for re-enablement, not dead code.
    // TODO(team): re-enable the route or remove the feature.
    "apps/web/src/features/calendar/**",
    "apps/web/src/components/layout/sidebar/**/Calendar*.tsx",

    // Dev-only galleries/pages: *.dev.tsx are excluded from production builds
    // and exist for local component/tool exploration.
    "apps/web/src/app/**/dev/**",
    "apps/web/src/**/*.dev.tsx",

    // ErrorBoundary is reusable infra; its only current consumers are the dev
    // galleries above, so it reads as unused once those are ignored.
    "apps/web/src/components/shared/ErrorBoundary.tsx",

    // ToolCallsSection is consumed only by the /dev/tool-gallery page
    // (ignored above), so knip can't see the import. Kept for the gallery.
    "apps/web/src/features/chat/components/bubbles/bot/ToolCallsSection.tsx",

    // Wake-word ("Hey GAIA"): recently merged, currently wired only into the
    // dev/wake-word gallery (ignored above). Work-in-progress, not dead.
    "apps/web/src/features/wake-word/**",

    // Date helpers consumed only by the parked calendar feature (ignored above).
    "apps/web/src/utils/date/dateTimeLocalUtils.ts",

    // One-shot maintenance scripts, not imported by app code.
    "apps/mobile/src/scripts/**",
    "docs/scripts/**",

    // Mintlify React snippets: consumed via `import` in .mdx files, which knip
    // cannot trace. These are legitimately used — knip has no MDX resolver.
    "docs/snippets/**",

    // Tailwind v4 entry: knip misreads the `@source` content globs as JS
    // imports. Tailwind scans these paths; they are not module imports.
    "apps/web/src/app/styles/globals.css",
  ],

  // Binaries provided by monorepo root, mise, Nx, or pnpm scripts (not in each
  // package.json). Includes nx target names invoked as `nx run <target>`.
  ignoreBinaries: [
    "biome",
    "clean",
    "check",
    "fix",
    "format",
    "type",
    "type-check",
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
    // uv / Python toolchain (provided by mise, not npm)
    "uv",
    "uvx",
    // Nx target names + build/dist scripts run via `nx run` / package scripts
    "build",
    "dev",
    "dist",
    "dist:mac",
    "dist:win",
    "dist:linux",
    "lint",
    "lint:fix",
    "tsc",
    "tsx",
    "diff",
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
        // Invoked dynamically as `pnpm exec jscpd` inside
        // scripts/ci/check-duplication.mjs, so knip can't see the usage.
        "jscpd",
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

      // @icons is a path alias to the local icon barrel, not an npm package.
      paths: {
        "@icons": ["src/components/shared/icons.tsx"],
      },

      // Shadcn/Radix primitives live here and are resolved dynamically; their
      // exports/deps (radix, etc.) are consumed only inside this directory.
      ignore: ["src/components/ui/**"],

      ignoreDependencies: [
        // Path alias, not a package (see paths above).
        "@icons",
        // HeroUI ships per-component subpackages pulled in transitively.
        "@heroui/.*",
        // Workspace package resolved via pnpm workspace, not always traced.
        "@gaia/shared",
        // Next.js image optimization (implicitly required, no direct import)
        "sharp",
        // Used by SWC compilation (no direct import in source)
        "@swc-node/register",
        "@swc/core",
        // Used by next-mdx-remote or mdx compilation pipeline
        "mdx",
        "@types/mdx",
        // Radix primitives consumed only inside src/components/ui/** (ignored above).
        "@radix-ui/.*",
        // CSS imported via subpath ("katex/dist/katex.min.css"); katex is a
        // transitive dep of rehype-katex, knip can't resolve the CSS subpath.
        "katex",

        // Consumed only inside knip-ignored directories (calendar feature,
        // components/ui, wake-word, web scripts) — real usage knip can't see.
        "react-day-picker", // calendar + components/ui/calendar.tsx
        "chrono-node", // calendar natural-language date parsing
        "little-date", // calendar date formatting
        "input-otp", // components/ui/input-otp.tsx
        "react-twemoji", // emoji rendering in ignored UI
        "@types/react-twemoji", // type stub for react-twemoji
        "@gaia/wake-word", // wake-word feature (ignored, WIP)
        "onnxruntime-web", // wake-word ONNX runtime (dynamic/worklet load)
        "glob", // used in apps/web/scripts/** (ignored)

        // Referenced in config / type augmentation, not via a normal import.
        "moment-timezone", // next.config.mjs serverExternalPackages
        "@react-types/shared", // `declare module` augmentation in HeroUIProvider
        "animated-number-react", // ambient module declaration in src/types

        "madge", // dev-only circular-dep tool, invoked via script
        // Next.js CSS inliner — optimizeCss is disabled in next.config.mjs, so
        // nothing imports it directly, but it stays a managed Next dependency.
        "critters",
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
        // Metro/Expo build config deps (used in metro.config.js / app.json).
        "@expo/metro-config",
        "expo-updates",
        // Expo plugins (consumed in app.json/app.config.js, not imported)
        "expo-auth-session",
        "expo-blur",
        // Workspace package + UI deps resolved via pnpm workspace hoisting.
        "@gaia/shared",
        "class-variance-authority",
        // React Native CLI — invoked as a binary by Expo/RN tooling.
        "@react-native-community/cli",
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
      // Peer type package for react-dom (pulled in transitively by Ink/React).
      ignoreDependencies: ["@types/react-dom"],
    },

    // ── Shared TS Library ────────────────────────────────────────────
    "libs/shared/ts": {
      entry: ["src/index.ts"],
      includeEntryExports: false, // library exports consumed by other workspaces
      // Optional peer: zustand is a peerDependency consumed by importing apps.
      ignoreDependencies: ["zustand"],
    },

    // ── Wake-word Library ────────────────────────────────────────────
    "libs/wake-word": {
      entry: ["src/index.ts"],
      ignoreDependencies: [
        // Audio capture used by the React Native build path.
        "react-native-live-audio-stream",
        // Vitest internals listed as devDeps but pulled in transitively.
        "loupe",
        "tinybench",
        "tinypool",
        "tinyrainbow",
        // Optional peers resolved by the consuming app (web vs native).
        "onnxruntime-react-native",
        "onnxruntime-web",
        "react-native",
      ],
    },
  },
};

export default config;
