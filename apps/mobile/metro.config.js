const { getDefaultConfig } = require("expo/metro-config");
const { withUniwindConfig } = require("uniwind/metro");
const path = require("path");

// Find the monorepo root
const projectRoot = __dirname;
const workspaceRoot = path.resolve(projectRoot, "../..");

const config = getDefaultConfig(__dirname);

// 1. Watch all files within the monorepo
config.watchFolders = [workspaceRoot];

// 2. Let Metro know where to resolve packages and assets
config.resolver.nodeModulesPaths = [
  path.resolve(projectRoot, "node_modules"),
  path.resolve(workspaceRoot, "node_modules"),
];

// 3. Add aliases:
//    - @shared  → libs/shared  (monorepo shared library)
//    - @/assets → apps/mobile/assets  (project assets folder)
//      NOTE: Metro does not read tsconfig paths, so the @/assets alias that
//      TypeScript resolves must be explicitly mirrored here. Without this,
//      require("@/assets/...") would fall through to the @/* → ./src/* rule
//      and fail because ./src/assets/ does not exist.
config.resolver.extraNodeModules = {
  "@shared": path.resolve(workspaceRoot, "libs/shared"),
  "@/assets": path.resolve(projectRoot, "assets"),
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
