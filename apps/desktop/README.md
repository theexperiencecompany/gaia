# GAIA Desktop

Electron desktop application for GAIA - Your Personal AI Assistant.

## Prerequisites

- Node.js 22+
- pnpm 10+
- The web app must be built first (`mise build:web`)

## Development

```bash
# Install dependencies
mise setup:desktop

# Run in development mode (requires web dev server at localhost:3000)
mise dev:desktop
```

## Building

```bash
# Build the desktop app (includes web build)
mise build:desktop

# Package without distributing (for testing)
mise pack:desktop
```

## Distribution

```bash
# Build for current platform
mise dist:desktop

# Platform-specific builds
mise dist:desktop:mac    # macOS (DMG + ZIP)
mise dist:desktop:win    # Windows (NSIS + Portable)
mise dist:desktop:linux  # Linux (AppImage + DEB + RPM)
```

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

The desktop app runs the Next.js standalone server on port 5174 (or next available)
to avoid conflicts with the development server on port 3000.

## Project Structure

```
apps/desktop/
├── src/
│   ├── main/           # Electron main process
│   │   ├── index.ts    # App entry, window management
│   │   └── server.ts   # Next.js server launcher
│   └── preload/        # Preload scripts for IPC
│       └── index.ts    # Exposed APIs
├── resources/          # App icons and assets
├── electron-builder.yml
├── electron.vite.config.ts
└── package.json
```

## Icons

- `resources/icon.png` - Linux icon
- `resources/icon.ico` - Windows icon
- `resources/icon.icns` - macOS icon (needs to be generated)

To generate macOS .icns from PNG:

```bash
# Using iconutil (macOS only)
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
