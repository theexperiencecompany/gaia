const { getDefaultConfig } = require("expo/metro-config");
const { withUniwindConfig } = require("uniwind/metro");
const path = require("path");

// Find the monorepo root
const projectRoot = __dirname;
const workspaceRoot = path.resolve(projectRoot, "../..");

const config = getDefaultConfig(__dirname);

// 1. Watch all files within the monorepo
config.watchFolders = [...(config.watchFolders || []), workspaceRoot];

// 2. Let Metro know where to resolve packages and assets
config.resolver.nodeModulesPaths = [
  path.resolve(projectRoot, "node_modules"),
  path.resolve(workspaceRoot, "node_modules"),
];

// Aliases mirror tsconfig paths (Metro doesn't read them): @shared → libs/shared,
// @/assets → apps/mobile/assets — without this require("@/assets/...") falls
// through to the @/* → ./src/* rule and fails (./src/assets/ doesn't exist).
config.resolver.extraNodeModules = {
  "@shared": path.resolve(workspaceRoot, "libs/shared"),
  "@/assets": path.resolve(projectRoot, "assets"),
  // Mirror the web alias pattern, but point @icons to the RN-safe wrapper.
  "@icons": path.resolve(projectRoot, "src/lib/gaia-icons.tsx"),
  // Resolves to TS source (not the package entry) so sub-path imports like
  // @gaia/shared/icons resolve to src/icons/index.ts without relying on Metro's
  // package-exports resolution (the workspace symlink still exists under the isolated linker).
  "@gaia/shared": path.resolve(workspaceRoot, "libs/shared/ts/src"),
};

// 4. Inline require()s — defers loading of JS modules until first use.
//    Speeds up cold start in release builds by avoiding eager evaluation
//    of the entire bundle.
config.transformer = {
  ...config.transformer,
  getTransformOptions: async () => ({
    transform: {
      experimentalImportSupport: false,
      inlineRequires: true,
    },
  }),
};

module.exports = withUniwindConfig(config, {
  // Path to your global.css file
  cssEntryFile: "./global.css",
  // Path for TypeScript definitions
  dtsFile: "./src/uniwind-types.d.ts",
  // Enable debug mode
  debug: true,
  extraThemes: [],
});
