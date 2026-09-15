/**
 * electron-builder afterSign hook (macOS). Two mutually exclusive paths:
 * - Signing disabled (dev/CI): ad-hoc sign restores a valid seal — macOS 26's
 *   RunningBoard kills an invalid-seal app ~12s after launch. No notarization.
 * - Signed (Developer-ID): notarizes when Apple ID creds are set, required so
 *   the TCC Full Disk Access grant survives a rebuild (differs by cdhash otherwise).
 */
const { execFileSync } = require("node:child_process");
const path = require("node:path");

function adhocSign(appPath) {
  console.log(`  • ad-hoc signing (real signing disabled)  file=${appPath}`);
  // Absolute path to the SIP-protected system binary — never resolve via
  // $PATH, which a caller could repoint at a malicious `codesign`.
  execFileSync(
    "/usr/bin/codesign",
    ["--force", "--deep", "--sign", "-", appPath],
    { stdio: "inherit" },
  );
}

async function notarizeApp(context, appPath) {
  const appleId = process.env.APPLE_ID;
  const appleIdPassword = process.env.APPLE_APP_SPECIFIC_PASSWORD;
  const teamId = process.env.APPLE_TEAM_ID;
  if (!appleId || !appleIdPassword || !teamId) {
    console.warn(
      "  • notarization skipped — APPLE_ID / APPLE_APP_SPECIFIC_PASSWORD / APPLE_TEAM_ID not set",
    );
    return;
  }

  const { notarize } = require("@electron/notarize");
  console.log(`  • notarizing (notarytool)  file=${appPath}`);
  await notarize({ appPath, appleId, appleIdPassword, teamId });
}

module.exports = async function afterSign(context) {
  if (context.electronPlatformName !== "darwin") return;

  const appName = `${context.packager.appInfo.productFilename}.app`;
  const appPath = path.join(context.appOutDir, appName);

  if (process.env.CSC_IDENTITY_AUTO_DISCOVERY === "false") {
    adhocSign(appPath);
    return;
  }

  await notarizeApp(context, appPath);
};
