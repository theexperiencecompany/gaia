/**
 * electron-builder afterSign hook.
 *
 * When real code signing is disabled (local builds with
 * CSC_IDENTITY_AUTO_DISCOVERY=false), the packaged app keeps only the
 * Electron binary's linker signature with a broken bundle seal. macOS 26's
 * RunningBoard kills LaunchServices-launched apps with an invalid seal
 * ~12s after launch (Dock icon appears, then vanishes). Ad-hoc signing
 * restores a valid seal so local builds run from Finder.
 */
const { execFileSync } = require("node:child_process");
const path = require("node:path");

module.exports = async function adhocSign(context) {
  if (context.electronPlatformName !== "darwin") return;
  if (process.env.CSC_IDENTITY_AUTO_DISCOVERY !== "false") return;

  const appName = `${context.packager.appInfo.productFilename}.app`;
  const appPath = path.join(context.appOutDir, appName);

  console.log(`  • ad-hoc signing (real signing disabled)  file=${appPath}`);
  execFileSync("codesign", ["--force", "--deep", "--sign", "-", appPath], {
    stdio: "inherit",
  });
};
