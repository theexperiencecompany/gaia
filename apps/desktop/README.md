# GAIA Desktop

Electron desktop application for GAIA — Your Personal AI Assistant.

## Prerequisites

- Node.js 22+
- pnpm 10+
- Nx CLI (`npm i -g nx` or use `npx nx`)

## Development

```bash
# Install dependencies (from repo root)
pnpm install

# Run in development mode (starts web dev server + Electron)
nx dev desktop
```

## Building & Packaging

### Step-by-step build

The full build pipeline for macOS:

```bash
# 1. Build the Next.js web app in standalone mode
nx build web

# 2. Dereference pnpm symlinks so electron-builder can sign correctly
bash apps/desktop/scripts/prepare-next-server.sh

# 3. Build the Electron main/preload bundles
nx build desktop

# 4. Package into a DMG + ZIP
nx run desktop:dist:mac
```

Or run everything in one command:

```bash
nx run desktop:dist:mac   # macOS (DMG + ZIP for x64 + arm64)
nx run desktop:dist:win   # Windows (NSIS installer + portable exe)
nx run desktop:dist:linux # Linux (AppImage + DEB + RPM)
```

Output lands in `apps/desktop/release/<version>/`.

### Quick test package (no distribution artifacts)

```bash
nx run desktop:pack   # creates an unpacked app dir, skips installer creation
```

---

## Running the built app

After `nx run desktop:dist:mac` completes:

```bash
# Open the .app from Finder / double-click the DMG, or run it from terminal:
open "apps/desktop/release/0.1.1/mac-arm64/GAIA.app"

# Or launch the binary directly (useful for seeing stdout logs):
"apps/desktop/release/0.1.1/mac-arm64/GAIA.app/Contents/MacOS/GAIA"
```

---

## "This app is damaged" / "App is corrupt" on macOS

This happens because macOS Gatekeeper blocks apps that are **not code-signed and notarized** with an Apple Developer certificate. The quarantine extended attribute (`com.apple.quarantine`) is set automatically on any file downloaded from the internet.

The built app also ships with only a linker-level ad-hoc signature (`Info.plist=not bound`, `Sealed Resources=none`), which Gatekeeper cannot evaluate.

### Fix 1 — Remove quarantine + re-sign with ad-hoc (no Apple account needed)

This is the right fix for local development and internal distribution. The ad-hoc signature tells macOS the binary is self-consistent; removing quarantine means Gatekeeper won't re-check it.

```bash
APP="/Applications/GAIA.app"   # or path to your .app

# 1. Remove the quarantine flag
xattr -cr "$APP"

# 2. Re-sign all inner helpers and frameworks (Electron requires bottom-up order)
for helper in "$APP/Contents/Frameworks/"*.app; do
  codesign --deep --force --sign - "$helper"
done
codesign --deep --force --sign - "$APP/Contents/Frameworks/Electron Framework.framework"
codesign --deep --force --sign - "$APP"

# 3. Verify
codesign --verify --deep --strict "$APP" && echo "OK"

# 4. Open it
open "$APP"
```

You only need to do this once per installed build. The app will open without any warning.

### Fix 2 — Right-click workaround

Right-click the `.app` → **Open** → click **Open** in the security dialog. macOS stores the exception and won't warn again.

### Fix 3 — Distribution (proper signing + notarization)

To ship to end users without any warning, you need an **Apple Developer account** ($99/year) and to configure electron-builder with your credentials.

**Required environment variables:**

| Variable | Description |
|---|---|
| `APPLE_ID` | Your Apple ID email |
| `APPLE_APP_SPECIFIC_PASSWORD` | App-specific password from appleid.apple.com |
| `APPLE_TEAM_ID` | Your 10-character Team ID from developer.apple.com |
| `CSC_LINK` | Base64-encoded `.p12` certificate, or path to it |
| `CSC_KEY_PASSWORD` | Password for the `.p12` certificate |

**Export your certificate:**

```bash
# Export from Keychain Access → "Developer ID Application: ..." → Export as .p12
# Then base64-encode it:
base64 -i certificate.p12 | pbcopy   # copies to clipboard
```

**Build with signing:**

```bash
export APPLE_ID="you@example.com"
export APPLE_APP_SPECIFIC_PASSWORD="xxxx-xxxx-xxxx-xxxx"  # pragma: allowlist secret
export APPLE_TEAM_ID="XXXXXXXXXX"
export CSC_LINK="$(base64 -i certificate.p12)"
export CSC_KEY_PASSWORD="your-cert-password"  # pragma: allowlist secret

nx run desktop:dist:mac
```

electron-builder will automatically:
1. Sign the app with your Developer ID certificate
2. Submit to Apple's notarization service
3. Staple the notarization ticket to the DMG

---

## Publishing

### 1. GitHub Releases (primary channel)

electron-builder is already configured to publish to GitHub Releases (`apps/desktop/electron-builder.yml`):

```yaml
publish:
  provider: github
  owner: theexperiencecompany
  repo: gaia
  releaseType: release
```

**Publish a new release:**

```bash
# Set your GitHub token
export GH_TOKEN="ghp_..."

# Build and publish in one step
GH_TOKEN=$GH_TOKEN nx run desktop:dist:mac
```

This creates a draft GitHub Release at `https://github.com/theexperiencecompany/gaia/releases` with the DMG and ZIP attached. Promote the draft to published from the GitHub UI, or set `releaseType: release` to auto-publish.

**Auto-update:** `electron-updater` in the app checks GitHub Releases for new versions and prompts users to download updates automatically.

---

### 2. Homebrew Cask

Create a Homebrew tap so macOS users can install with:

```bash
brew install --cask theexperiencecompany/tap/gaia
```

**Step 1 — Create the tap repository:**

Create a GitHub repo named `homebrew-tap` under `theexperiencecompany` org.
The tap URL will be `https://github.com/theexperiencecompany/homebrew-tap`.

**Step 2 — Add a cask formula:**

Create `Casks/gaia.rb` in that repo:

```ruby
cask "gaia" do
  version "0.1.1"

  if Hardware::CPU.arm?
    url "https://github.com/theexperiencecompany/gaia/releases/download/v#{version}/GAIA-arm64.dmg"
    sha256 "REPLACE_WITH_SHA256_OF_ARM64_DMG"
  else
    url "https://github.com/theexperiencecompany/gaia/releases/download/v#{version}/GAIA-x64.dmg"
    sha256 "REPLACE_WITH_SHA256_OF_X64_DMG"
  end

  name "GAIA"
  desc "Your Personal AI Assistant"
  homepage "https://heygaia.io"

  app "GAIA.app"

  zap trash: [
    "~/Library/Application Support/GAIA",
    "~/Library/Caches/io.heygaia.desktop",
    "~/Library/Logs/GAIA",
    "~/Library/Preferences/io.heygaia.desktop.plist",
  ]
end
```

**Get the SHA256 of the DMG:**

```bash
shasum -a 256 "apps/desktop/release/0.1.1/GAIA-arm64.dmg"
```

**Step 3 — Test the cask locally:**

```bash
brew tap theexperiencecompany/tap https://github.com/theexperiencecompany/homebrew-tap
brew install --cask theexperiencecompany/tap/gaia
brew audit --cask theexperiencecompany/tap/gaia
```

**Step 4 — Update the cask on each release:**

Update `version` and both `sha256` values in `gaia.rb`, commit, and push. Users running `brew upgrade` will pick it up automatically.

> **Note:** Homebrew requires the app to be notarized. Unsigned builds will fail `brew audit`. Set up signing first (see above).

---

### 3. Direct download (website)

Host the DMG/EXE on your CDN and link from `heygaia.io/download`. Suggested filenames after upload:

| File | Platform |
|---|---|
| `GAIA-arm64.dmg` | macOS Apple Silicon |
| `GAIA-x64.dmg` | macOS Intel |
| `GAIA-arm64.exe` | Windows ARM |
| `GAIA-x64.exe` | Windows x86_64 |
| `GAIA-x64.AppImage` | Linux x86_64 |
| `GAIA-x64.deb` | Debian/Ubuntu |
| `GAIA-x64.rpm` | Fedora/RHEL |

---

### 4. Scoop (Windows)

Create a Scoop bucket so Windows users can install with:

```powershell
scoop bucket add gaia https://github.com/theexperiencecompany/scoop-bucket
scoop install gaia
```

Create `bucket/gaia.json` in the `scoop-bucket` repo:

```json
{
  "version": "0.1.1",
  "description": "Your Personal AI Assistant",
  "homepage": "https://heygaia.io",
  "license": "Proprietary",
  "url": "https://github.com/theexperiencecompany/gaia/releases/download/v0.1.1/GAIA-x64.exe",
  "hash": "REPLACE_WITH_SHA256",
  "installer": {
    "script": [
      "Start-Process -Wait -FilePath \"$dir\\GAIA-x64.exe\" -ArgumentList \"/S /D=$dir\""
    ]
  },
  "shortcuts": [
    ["GAIA.exe", "GAIA"]
  ]
}
```

---

## Release checklist

Before tagging a release:

- [ ] Bump `version` in `apps/desktop/package.json`
- [ ] Ensure `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, `APPLE_TEAM_ID`, `CSC_LINK`, `CSC_KEY_PASSWORD` are set (for signed builds)
- [ ] Run `nx run desktop:dist:mac` (and `dist:win`, `dist:linux` if needed)
- [ ] Set `GH_TOKEN` and publish to GitHub Releases
- [ ] Update `sha256` in `Casks/gaia.rb` in the homebrew-tap repo
- [ ] Update direct download links on the website

---

## Architecture

```
┌─────────────────────────────────────────────┐
│              Electron Main Process          │
│  ┌─────────────────────────────────────┐    │
│  │     Next.js Standalone Server       │    │
│  │         (Port 5174+)                │    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│           BrowserWindow (Chromium)          │
│            loads localhost:5174             │
└─────────────────────────────────────────────┘
```

The desktop app embeds the Next.js standalone server and serves it locally on port 5174. The Electron window loads `http://localhost:5174`. A splash screen is shown while the server starts.

## Project Structure

```
apps/desktop/
├── src/
│   ├── main/
│   │   ├── index.ts        # App entry, lifecycle
│   │   ├── server.ts       # Spawns embedded Next.js server
│   │   ├── deep-link.ts    # OAuth gaia:// URL handling
│   │   ├── auto-updater.ts # electron-updater integration
│   │   ├── ipc.ts          # IPC handlers
│   │   └── windows/        # BrowserWindow management
│   └── preload/
│       └── index.ts        # Exposed APIs (contextBridge)
├── resources/
│   ├── icons/              # App icons (all sizes)
│   └── entitlements.mac.plist
├── scripts/
│   ├── prepare-next-server.sh   # Dereference pnpm symlinks (macOS/Linux)
│   └── prepare-next-server.mjs  # Same, cross-platform Node.js version
├── electron-builder.yml
├── electron.vite.config.ts
└── package.json
```

## Generating macOS icons

```bash
mkdir icon.iconset
sips -z 16 16     icon.png --out icon.iconset/icon_16x16.png
sips -z 32 32     icon.png --out icon.iconset/icon_16x16@2x.png
sips -z 32 32     icon.png --out icon.iconset/icon_32x32.png
sips -z 64 64     icon.png --out icon.iconset/icon_32x32@2x.png
sips -z 128 128   icon.png --out icon.iconset/icon_128x128.png
sips -z 256 256   icon.png --out icon.iconset/icon_128x128@2x.png
sips -z 256 256   icon.png --out icon.iconset/icon_256x256.png
sips -z 512 512   icon.png --out icon.iconset/icon_256x256@2x.png
sips -z 512 512   icon.png --out icon.iconset/icon_512x512.png
sips -z 1024 1024 icon.png --out icon.iconset/icon_512x512@2x.png
iconutil -c icns icon.iconset
rm -rf icon.iconset
```
