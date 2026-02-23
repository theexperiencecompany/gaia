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

// 3. Add alias for @shared to point to libs/shared
config.resolver.extraNodeModules = {
  "@shared": path.resolve(workspaceRoot, "libs/shared"),
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
