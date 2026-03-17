# GAIA Mobile

React Native / Expo app for the GAIA personal AI assistant.

## Prerequisites

| Tool           | Version | Notes                                                   |
| -------------- | ------- | ------------------------------------------------------- |
| Node           | 22+     | via `mise` or `nvm`                                     |
| pnpm           | 10+     | `npm i -g pnpm`                                         |
| Java JDK       | 17      | Required for Android — `brew install --cask temurin@17` |
| Android Studio | latest  | Local Android builds + emulator                         |
| Xcode          | 15+     | Local iOS builds — macOS only                           |
| EAS CLI        | 16+     | Cloud builds — `npm i -g eas-cli`                       |
| Watchman       | latest  | Recommended — `brew install watchman`                   |

### JDK setup (Android)

After installing JDK 17 via Homebrew, add to `~/.zshrc`:

```bash
export JAVA_HOME=$(/usr/libexec/java_home -v 17)
export ANDROID_HOME=$HOME/Library/Android/sdk
export PATH=$PATH:$ANDROID_HOME/emulator:$ANDROID_HOME/platform-tools
```

Then run `source ~/.zshrc`.

---

## Quick Start

```bash
# From monorepo root
pnpm install

# Start the Expo dev server
mise run dev
# or: cd apps/mobile && expo start
```

Scan the QR code with **Expo Go** (basic features) or your **dev client build** (required for all native modules like WebView, notifications).

---

## Running on Device / Emulator

```bash
mise run android     # Build debug APK + launch on connected device or emulator
mise run ios         # Build + launch on iOS simulator (macOS only)
```

---

## Building with EAS (Cloud)

EAS (Expo Application Services) builds the native app in the cloud — no local Android Studio / Xcode setup needed.

```bash
eas login            # One-time login (Expo account)
```

| Command                      | What it does                                                      |
| ---------------------------- | ----------------------------------------------------------------- |
| `mise run build:dev`         | Dev client — install once, then use hot reload via `mise run dev` |
| `mise run build:dev:android` | Dev client APK only                                               |
| `mise run build:preview`     | Shareable internal APK/IPA (no store submission)                  |
| `mise run build:prod`        | Production release (auto-increments version)                      |
| `mise run submit`            | Submit latest production build to App Store + Google Play         |

> **Why a dev client?** The app uses native modules (`react-native-webview`, `expo-notifications`, `expo-secure-store`) that Expo Go doesn't support. Build the dev client once with `mise run build:dev`, install it on your device, then develop normally with hot reload.

Build dashboard: **https://expo.dev/accounts/heygaia/projects/gaia-mobile/builds**

---

## Environment

| File           | Purpose                             |
| -------------- | ----------------------------------- |
| `.env.local`   | Local dev overrides (not committed) |
| `.env.staging` | Staging environment                 |
| `eas.json`     | EAS build profiles                  |

Key env vars:

```bash
EXPO_PUBLIC_API_URL=http://localhost:8000/api/v1   # API base URL
```

---

## Project Structure

```
src/
  app/                    # Expo Router file-based routes
    (app)/
      (tabs)/             # Bottom tab screens
        index.tsx         # Chat
        todos/            # Todos
        workflows/        # Workflows
        integrations/     # Integrations
        notifications/    # Alerts
      settings/           # Settings screen
      c/[id].tsx          # Deep-link to specific conversation
    login/                # Auth screens
    signup/

  features/
    auth/                 # Login, token storage, user context
    chat/                 # Chat messages, composer, streaming, tool cards
    integrations/         # Integration list, OAuth flow, detail sheet
    notifications/        # In-app notifications
    settings/             # Settings sections
    todos/                # Todo list, subtasks, bulk operations
    workflows/            # Workflow list, detail, triggers, schedule builder

  components/
    ui/                   # Shared UI (MessageBubble, MarkdownRenderer, etc.)
    icons/                # Icon wrappers

  lib/                    # API client, SSE, WebSocket, utilities
  stores/                 # Zustand global state
```

---

## Features

### Chat

- iMessage-style bubbles with grouped variants
- Real-time streaming responses (SSE)
- Tool output cards (33+ types: email, calendar, weather, search, todos, code, charts, Reddit, etc.)
- Mermaid diagram rendering (WebView)
- KaTeX math rendering (WebView — `$...$` inline, `$$...$$` block)
- Thinking bubble (collapsible reasoning display)
- Emoji-only message scaling (1/2/3 emoji = 52/40/32px, no bubble for single)
- Animated wave loading indicator with tool-aware pulsating icons
- File attachments, reply quoting, follow-up action chips
- Model picker in composer
- Slash command sheet with category icons + integration lock indicators
- Calendar event + workflow + tool context indicators in composer

### Todos

- Create / edit / delete with priority, due date, labels, projects
- Subtask management (bottom sheet — create, toggle, delete)
- Filter tabs: All, Today, Upcoming, Completed
- Bulk multi-select (long-press → Complete / Delete action bar)

### Workflows

- Create / edit / delete workflows
- Trigger picker with 11 integration triggers (Gmail, GitHub, Slack, Calendar, Notion, Linear, Todoist, Google Sheets, Asana)
- Schedule builder: preset chips (hourly/daily/weekly/monthly), time picker, day selector, custom cron
- Execution history with status badges
- Community workflows discovery

### Integrations

- Connect / disconnect OAuth integrations
- Detail sheet with tools list and bearer token support
- Integration lock indicators in slash command sheet

### Notifications

- In-app notification center with Unread / All tabs
- Time-grouped list (Today, Yesterday, Earlier)
- Action buttons per notification
- Real-time updates

### Settings

- Account (name, email, sign out)
- Preferences (profession, response style, timezone, custom instructions)
- Linked Accounts (Telegram, Discord, Slack)
- Memory management (search, add, swipe-to-delete)
- Notifications (push, channel preferences)
- Usage & subscription

---

## All `mise` Commands

```bash
mise run dev                  # Start Expo dev server
mise run dev:clear            # Start with cleared Metro cache
mise run android              # Run on Android
mise run ios                  # Run on iOS
mise run build:dev            # EAS dev client build (all platforms)
mise run build:dev:android    # EAS dev client APK
mise run build:dev:ios        # EAS dev client IPA
mise run build:preview        # EAS preview build
mise run build:prod           # EAS production build
mise run submit               # Submit to app stores
mise run lint                 # Biome lint
mise run lint:fix             # Biome lint + auto-fix
mise run type                 # TypeScript type check
mise run prebuild             # Generate native folders
mise run prebuild:clean       # Regenerate native folders from scratch
mise run clean                # Remove .expo, android, ios
mise run clean:all            # Full clean including node_modules
```

---

## Firebase (Android Push Notifications)

1. Download `google-services.json` from [Firebase Console](https://console.firebase.google.com) → Project Settings → Android App
2. Place it at `apps/mobile/google-services.json`
3. For FCM v1 credentials: `eas credentials` or Expo Dashboard → Credentials

See `google-services.json.template` for the required structure.
