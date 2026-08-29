# Expo MCP + Vision Comparison Pipeline

> **Agent 8 — Workflow Phase: Expo MCP & Vision Setup**
> Reusable, side-by-side Web vs Native visual verification for `apps/mobile` (Expo 55, React Native 0.83, expo-router) and `apps/web` (Next.js).

## 0. Verification — Current MCP Servers (`mcp status`)

Run from `gaia` worktree:

```bash
cat .mcp.json | python3 -m json.tool
# OR via pi global cache:
cat ~/.pi/agent/mcp-cache.json | python3 -c "import json; d=json.load(open('/Users/aryan/.pi/agent/mcp-cache.json')); print(list(d['servers'].keys()))"
```

**Captured Sat Aug 29 21:35 UTC:**

```
Global pi config (~/.pi/agent/settings.json):
  packages: context-mode, pi-mcp-adapter, pi-web-access, pi-subagents, pi-dynamic-workflows, pi-goal, piolium, pi-retry, omp-nous-portal-provider
  mcpServers: NONE (global) — all servers are project-local

Gaia worktree .mcp.json — 6 servers defined:
  - dagger:        dagger -s mcp
  - infisical:     npx -y @infisical/mcp               (universal-auth)
  - code-review-graph: uvx code-review-graph serve
  - langsmith:     uvx langsmith-mcp-server
  - chrome-devtools: npx -y chrome-devtools-mcp@latest --autoConnect
  - mobile:        npx -y @mobilenext/mobile-mcp@latest

Live MCP cache (last pi startup): 3 actually loaded → [code-review-graph, chrome-devtools, posthog]
# expo-mcp is NOT configured — gap this pipeline closes.
```

**Expo versions on this machine:**

```
$ npx expo --version          → 57.0.20
$ npx expo-mcp --version      → 0.2.4  (expo-mcp@0.2.4, @expo/mcp-tunnel@0.2.3)
$ node --version              → 22.23.2 (via mise)
$ xcode-select -p             → /Library/Developer/CommandLineTools  (Xcode.app NOT installed — see § Troubleshooting)
```

---

## 1. Expo CLI — Install & Verify

Gaia uses `mise` + `pnpm` workspaces. Expo is a workspace dep (`apps/mobile`), but agents need a resolvable CLI anywhere.

```bash
# From repo root — verify (no install needed, already in lockfile):
cd /Users/aryan/Projects/gaia
npx expo --version          # → 57.0.20  (also check apps/mobile/package.json "expo": "^55.0.27")
pnpm --filter gaia-mobile expo --version

# If you need to update / reinstall:
pnpm add -w expo@latest                    # root (if needed)
pnpm --filter gaia-mobile add expo@^55.0.27
pnpm install

# Optional global shim (not required — prefer npx):
npm install -g expo-cli   # DEPRECATED — use `npx expo` instead

# Verify config is loadable:
npx expo config --type public --json | jq '.expo.slug, .expo.ios.bundleIdentifier, .expo.android.package'
# Expected: "gaia", "io.heygaia.gaiamobile", "io.heygaia.gaiamobile"

# Verify web target builds:
npx --prefix apps/mobile expo export --platform web --dump-sitemap 2>&1 | head -20
```

**mise note:** `apps/mobile` tasks are monorepo-aware. Use `mise //apps/mobile:start` or `cd apps/mobile && npx expo start`.

---

## 2. Expo MCP Server — Install & Configure

### 2a. What `expo-mcp` provides

| Tool | Description | When to use |
|---|---|---|
| `automation_take_screenshot` | Full-screen or `testID` crop via native automation (iOS XCUITest / Android UiAutomator) — returns JPEG base64 | Primary native screenshot for vision loop |
| `automation_tap` | Tap by `{x,y}` or `testID` | Navigate before screenshot (e.g., open `/settings`) |
| `automation_find_view` | Dump view props for `testID` | Assert a component mounted before screenshot |
| `expo_router_sitemap` | `expo-router-sitemap` dump | Enumerate routes to compare |
| `open_devtools` | Launch React Native DevTools | Debug bridge |
| `collect_app_logs` | Collect `logcat`/`syslog`/`js_console` for `durationMs` | Diagnose blank screenshots |

Upstream: `expo-mcp@0.2.4` (https://github.com/expo/expo-mcp, package `packages/expo-mcp`) + `@expo/mcp-tunnel@0.2.3`.

### 2b. Install

```bash
cd /Users/aryan/Projects/gaia/apps/mobile

# One-off (no save) — fastest for agents:
npx -y expo-mcp@latest --help
# → Usage: expo-mcp [options]  (requires --dev-server-url)

# Pinned workspace install (recommended — committed to lockfile):
pnpm add -D expo-mcp@^0.2.4

# Alternative umbrella that bundles expo-mcp + mobile-mcp (community):
pnpm add -D local-expo-mcp@^0.5.1   # wraps expo-mcp + mobile-mcp in one server
```

### 2c. Dev server prerequisite

`expo-mcp` **requires a running Metro dev server** and its URL. It talks to the app via `@expo/mcp-tunnel`.

```bash
# Terminal 1 — start Metro (pick one):
cd apps/mobile
npx expo start --port 8081 --clear
# OR with env:
pnpm --filter gaia-mobile dev:local        # dotenv -e .env.local expo start
pnpm --filter gaia-mobile dev:staging

# Confirm the tunnel:
curl -s http://localhost:8081/status | jq .  # or check Metro logs for "Metro waiting on exp://..."

# Expo web (for side-by-side) — Terminal 2:
cd apps/web
pnpm dev  # or mise dev  (Next on http://localhost:3000)
# OR static web build:
npx --prefix apps/mobile expo start --web --port 8082
```

Capture the **dev server URL** — usually `http://localhost:8081`. You will pass it to the MCP server.

### 2d. Verify `expo-mcp` standalone

```bash
# --dev-server-url is mandatory (exits 1 if omitted)
npx expo-mcp --dev-server-url http://localhost:8081 --root $(pwd) --help

# Collect logs smoke test (app must be installed on simulator):
npx expo-mcp --dev-server-url http://localhost:8081 \
  --collect-logs 2000 \
  --app-id io.heygaia.gaiamobile \
  --platform ios 2>&1 | head -50
```

---

## 3. `mcp.json` Snippet — Drop-in for `gaia/.mcp.json`

`expo-mcp` is a **stdio** server. Unlike most MCP servers, its `args` must include the live Metro URL. Two patterns:

### Pattern A — Stdio (local dev, single user) — **recommended**

Add to `gaia/.mcp.json` `mcpServers`:

```json
{
  "mcpServers": {
    "expo-mcp": {
      "command": "npx",
      "args": [
        "-y",
        "expo-mcp@0.2.4",
        "--dev-server-url",
        "http://localhost:8081",
        "--root",
        "/Users/aryan/Projects/gaia/apps/mobile"
      ],
      "env": {},
      "type": "stdio"
    }
  }
}
```

### Pattern B — With tunnel (remote / shared URL)

If your Metro is behind `ngrok` or Expo tunnel, add `--mcp-server-url`:

```json
{
  "mcpServers": {
    "expo-mcp": {
      "command": "npx",
      "args": [
        "-y",
        "expo-mcp@0.2.4",
        "--dev-server-url",
        "http://localhost:8081",
        "--mcp-server-url",
        "wss://mcp.expo.dev",
        "--root",
        "/Users/aryan/Projects/gaia/apps/mobile"
      ],
      "type": "stdio"
    }
  }
}
```

### Pattern C — All-in-one `local-expo-mcp` (expo-mcp + mobile-mcp combined)

Use if you want **one server** instead of two (requires `npm install local-expo-mcp`):

```json
{
  "mcpServers": {
    "local-expo": {
      "command": "npx",
      "args": [
        "-y",
        "local-expo-mcp@latest",
        "--dev-server-url",
        "http://localhost:8081",
        "--root",
        "/Users/aryan/Projects/gaia/apps/mobile"
      ],
      "type": "stdio"
    }
  }
}
```

### Complete `gaia/.mcp.json` (merged — copy-paste ready)

```json
{
  "mcpServers": {
    "dagger": {
      "command": "dagger",
      "args": ["-s", "mcp"],
      "env": {}
    },
    "infisical": {
      "command": "npx",
      "args": ["-y", "@infisical/mcp"],
      "env": {
        "INFISICAL_AUTH_METHOD": "universal-auth",
        "INFISICAL_UNIVERSAL_AUTH_CLIENT_ID": "${INFISICAL_MCP_CLIENT_ID:-}",
        "INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET": "${INFISICAL_MCP_CLIENT_SECRET:-}",
        "INFISICAL_HOST_URL": "https://app.infisical.com"
      }
    },
    "code-review-graph": {
      "command": "uvx",
      "args": ["code-review-graph", "serve"],
      "type": "stdio"
    },
    "langsmith": {
      "command": "uvx",
      "args": ["langsmith-mcp-server"],
      "type": "stdio",
      "env": {
        "LANGSMITH_API_KEY": "${LANGSMITH_API_KEY:-}"
      }
    },
    "chrome-devtools": {
      "command": "npx",
      "args": ["-y", "chrome-devtools-mcp@latest", "--autoConnect"],
      "env": {}
    },
    "mobile": {
      "command": "npx",
      "args": ["-y", "@mobilenext/mobile-mcp@latest"],
      "env": {
        "ANDROID_HOME": "/Users/aryan/Library/Android/sdk",
        "PATH": "/Users/aryan/Library/Android/sdk/platform-tools:/Users/aryan/Library/Android/sdk/emulator:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
      }
    },
    "expo-mcp": {
      "command": "npx",
      "args": [
        "-y",
        "expo-mcp@0.2.4",
        "--dev-server-url",
        "http://localhost:8081",
        "--root",
        "/Users/aryan/Projects/gaia/apps/mobile"
      ],
      "type": "stdio"
    }
  }
}
```

> **Important:** `ANDROID_HOME` above is corrected from the stale `dhruvmaradiya` path in the initial `.mcp.json`. Update it per machine. On this Mac, Android SDK is not installed — install via `brew install --cask android-commandlinetools` or Android Studio if you need Android screenshots.

**Apply & verify:**

```bash
# After editing .mcp.json, restart the agent session / reload MCP:
# In Pi:  :restart  or  quit + reopen
# Verify via cache (agent will repopulate on next start):
cat ~/.pi/agent/mcp-cache.json | python3 -m json.tool | grep -A2 '"expo'
# Or ask the agent:  "list available mcp tools"  → should show automation_take_screenshot etc.

# Quick health check — list tools exposed by expo-mcp:
npx @modelcontextprotocol/inspector --cli npx -y expo-mcp --dev-server-url http://localhost:8081 --root ./apps/mobile --method tools/list 2>&1 | jq .
```

### Pi-specific note (no `~/.pi/agent/mcp.json`)

Pi loads MCP from `.mcp.json` in the **worktree root** (`gaia/.mcp.json`), not `~/.pi/agent/mcp.json`. Keep `~/.pi/agent/settings.json` for packages only. `mcp-cache.json` is read-only — do not edit.

---

## 4. Agent Screenshot Access — Web vs Native

### 4a. Web screenshots — 3 options (choose per fidelity/speed)

| Method | Tool | Command / MCP tool | Pros | Cons |
|---|---|---|---|---|
| **Playwright** (recommended) | `pnpm --filter gaia-web exec playwright` | `npx playwright screenshot http://localhost:3000/c web.png --full-page` | Deterministic, headless, supports mobile viewport, fast | Requires `npx playwright install` |
| **chrome-devtools MCP** | `chrome-devtools` server | `take_screenshot` / `navigate_page` tools | No extra install if MCP already loaded; agent-native | Needs Chrome autoConnect + live web server |
| **Loki/Chromatic** (batch) | `loki` | `npx loki --chromeConcurrency 4` | Whole storybook, iterates all routes | Heavy — use for parity audits, not inner loop |

```bash
# Playwright — install once:
pnpm add -D @playwright/test playwright   # apps/web already has @playwright/test@^1.62.1
npx playwright install chromium --with-deps

# Single route screenshot:
npx playwright screenshot \
  --browser chromium \
  --viewport-size "390,844" \
  --full-page \
  http://localhost:3000/c \
  ./screenshots/web-c.png

# With mobile viewport + dark mode (Gaia is dark-themed):
DEVICE="iPhone 14" npx playwright test --project chromium  # via e2e harness
# OR one-liner with playwright codegen:
node -e "
import { chromium } from 'playwright';
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport:{width:390,height:844}, colorScheme:'dark' });
const page = await ctx.newPage();
await page.goto('http://localhost:3000/c', { waitUntil:'networkidle' });
await page.screenshot({ path:'screenshots/web-c.png', fullPage:true });
await browser.close();
"
```

**Web harness already in repo:** `apps/web/e2e/harness.ts` sets `WEB_BASE_URL=http://localhost:3000`, `API_BASE_URL=http://localhost:8000/api/v1`, and `global-setup.ts` seeds dev user `dev@gaia.local`. Reuse its `WEB_BASE_URL` in scripts.

### 4b. Native screenshots — 3 layers (fallback chain)

```
1. expo-mcp  automation_take_screenshot  (preferred — app-aware, testID crops, 700KB JPEG)
   ↓ if no simulator / no Metro
2. mobile-mcp  mobile_take_screenshot   (generic iOS/Android — works without Expo, via mobilecli)
   ↓ if MCP not loaded
3. Raw CLI  xcrun simctl / adb screencap  (zero-dep fallback, always works if simulator booted)
```

**Layer 1 — expo-mcp (via MCP tool):**

No CLI — invoked by the agent. Example prompt payload the agent sends:

```json
{
  "tool": "automation_take_screenshot",
  "arguments": {
    "projectRoot": "/Users/aryan/Projects/gaia/apps/mobile",
    "platform": "ios"
  }
}
```

For a specific component (requires `testID` prop on the React Native view):

```json
{
  "tool": "automation_take_screenshot",
  "arguments": {
    "projectRoot": "/Users/aryan/Projects/gaia/apps/mobile",
    "platform": "ios",
    "testID": "chat-composer"
  }
}
```

The tool returns `image/jpeg` base64 (resized to ≤700KB, width ≤960, quality 85→40, via `jimp-compact`).

**Layer 2 — mobile-mcp:**

```json
{ "tool": "mobile_take_screenshot", "arguments": {} }
{ "tool": "mobile_save_screenshot", "arguments": { "filePath": "/tmp/native.png" } }
```

**Layer 3 — Raw CLI (for scripts / CI):**

```bash
# iOS Simulator — requires Xcode + booted simulator
xcrun simctl list devices booted --json | jq '.devices[][] | select(.state=="Booted")'
xcrun simctl io booted screenshot ./screenshots/native-c.png
# Optional: crop status bar
# sips -c 844 390 ./screenshots/native-c.png  (or use jimp)

# Variant — specific device UDID:
UDID=$(xcrun simctl list devices booted --json | jq -r '.devices[][] | select(.state=="Booted") | .udid' | head -1)
xcrun simctl io "$UDID" screenshot ./screenshots/native-c.png

# Android Emulator / Device:
adb devices                          # list booted
adb exec-out screencap -p > ./screenshots/native-c.png
# OR via emulator console:
adb -s emulator-5554 exec-out screencap -p > ./screenshots/native-c.png

# Expo web fallback (renders RN for web — not a true native screenshot but useful for CSS diff):
npx expo start --web --port 8082 &
npx playwright screenshot http://localhost:8082 ./screenshots/expo-web-c.png
```

**Device boot helpers:**

```bash
# iOS — boot most recent iPhone 15 simulator:
open -a Simulator  # or: xcrun simctl boot "iPhone 15" 2>/dev/null; xcrun simctl bootstatus "iPhone 15"
xcrun simctl list devicetypes | grep iPhone | tail -5
xcrun simctl create "Gaia-iPhone-15" "iPhone 15" "iOS17.5"  # if needed

# Android — start emulator headless:
emulator -avd Pixel_7_API_34 -no-window -no-audio &
adb wait-for-device
```

### 4c. Adding `testID`s (required for component-level crops)

Expo MCP's `testID` screenshot only works if the view sets the prop:

```tsx
// apps/mobile/components/ChatComposer.tsx
<View testID="chat-composer">
  <TextInput testID="chat-composer-input" placeholder="What can I do for you today?" />
</View>
```

Audit which screens are missing IDs:

```bash
grep -R "testID" apps/mobile --include="*.tsx" | cut -d: -f2 | sort -u | head -30
# Compare with sitemap:
npx --prefix apps/mobile expo-router-sitemap 2>&1 | grep "Route:"
```

---

## 5. Visual Diff Tool — pixelmatch / loki / playwright

### 5a. Lightweight — pixelmatch + pngjs (recommended for loop)

Best for: Web-vs-Native per-route diff in CI or the agent loop. Tiny, fast, no Docker.

```bash
# Install once (repo-root or apps/mobile):
pnpm add -D pixelmatch@^7.2.0 pngjs@^7.0.0 sharp@^0.33.5

# Quick CLI diff (see reusable script §7):
node scripts/vision-compare.mjs --web ./screenshots/web-c.png --native ./screenshots/native-c.png --out ./screenshots/diff-c.png --threshold 0.1
# Exit 0 if diff < threshold, 1 if >.
```

How it works: loads both PNGs via `pngjs`, ensures equal dimensions (resizes with `sharp` to 390×844 logical), runs `pixelmatch`, writes diff PNG with red mismatches, emits `diffPixels`, `diffRatio`, `pass`.

**Threshold guide:**

| Threshold | Use case |
|---|---|
| `0.1` (default) | Pixel-strict — catches 1px shifts, font rendering diffs |
| `0.15` | Normal — ignores antialiasing, allows Web vs Native font diffs |
| `0.25` | Lenient — layout only (use with vision LLM) |

### 5b. Heavyweight — Loki (Storybook visual regression)

Best for: Full parity audit across all stories (not inner loop).

```bash
pnpm add -D loki@^0.35.1 @loki/runner @loki/target-chrome-app @loki/target-native-ios-simulator

# Requires .loki.json + running Storybook:
cat > .loki.json <<'JSON'
{
  "configurations": {
    "chrome.laptop": { "target": "chrome.app", "chromeConcurrency": 4 },
    "ios.sim":       { "target": "native-ios-simulator", "iosDir": "apps/mobile/ios" }
  }
}
JSON

npx loki update --requireReference --reactUri file:./storybook-static
npx loki test --requireReference --reactUri file:./storybook-static
# Outputs: .loki/difference/ + .loki/report.json
```

### 5c. Built-in — Playwright `toHaveScreenshot`

Zero extra dep if you already use `apps/web` e2e:

```ts
// apps/web/e2e/visual.spec.ts
import { test, expect } from "@playwright/test";
test("chat — visual", async ({ page }) => {
  await page.goto("/c");
  await page.waitForSelector("[placeholder*='What can I do']");
  await expect(page).toHaveScreenshot("web-c.png", { maxDiffPixelRatio: 0.02 });
});
```

---

## 6. Side-by-Side Comparison Loop

### 6a. Mental model

```
for each route in sitemap (/c, /todos, /settings, /integrations, /chat/:id):
  1. Navigate  (web: page.goto, native: automation_tap by testID or deep link)
  2. Screenshot (web: playwright, native: expo-mcp)
  3. Normalize  (resize both to 390×844 @2x, strip status bar)
  4. Diff       (pixelmatch → diff.png + diffRatio)
  5. Vision     (if diffRatio > threshold OR every time, send both images to LLM)
  6. Decide     (PASS / FLAG with notes)
```

### 6b. Manual loop (one route, for debugging)

```bash
# Terminal 1: web
mise dev --sim   # boots api (8000) + web (3000) + sim harness

# Terminal 2: mobile Metro
cd apps/mobile && npx expo start --port 8081 --clear

# Terminal 3: iOS simulator (requires Xcode)
open -a Simulator && xcrun simctl boot "iPhone 15" || true

# Now run one comparison:
ROUTE="/c"
WEB_URL="http://localhost:3000$ROUTE"
MOBILE_DEEP_LINK="gaia://chat"           # per app.json scheme + host
mkdir -p ./screenshots

# 1. Web
npx playwright screenshot --viewport-size "390,844" "$WEB_URL" "./screenshots/web-$(echo $ROUTE | tr / -).png"

# 2. Native — via MCP (agent tool) OR raw:
xcrun simctl openurl booted "$MOBILE_DEEP_LINK" 2>/dev/null || true
sleep 2
xcrun simctl io booted screenshot "./screenshots/native-$(echo $ROUTE | tr / -).png"

# 3. Diff
node scripts/vision-compare.mjs \
  --web "./screenshots/web-$(echo $ROUTE | tr / -).png" \
  --native "./screenshots/native-$(echo $ROUTE | tr / -).png" \
  --out "./screenshots/diff-$(echo $ROUTE | tr / -).png" \
  --threshold 0.1 \
  --vision   # also call LLM if OPENAI_API_KEY / ANTHROPIC_API_KEY set

# Check output:
open ./screenshots/diff--c.png
cat ./screenshots/report.json | jq .
```

### 6c. Automated loop (all routes)

```bash
# Run the full comparison pipeline for every expo-router route:
node scripts/vision-compare.mjs --all-routes \
  --web-base http://localhost:3000 \
  --mobile-scheme gaia \
  --platform ios \
  --threshold 0.12 \
  --vision \
  --output-dir ./screenshots

# Output layout:
# ./screenshots/
#   web-c.png, native-c.png, diff-c.png
#   web-todos.png, native-todos.png, diff-todos.png
#   ...
#   report.json   # { route, diffRatio, pass, visionVerdict, visionNotes }[]
#   report.html   # side-by-side viewer

# Filter to one platform:
node scripts/vision-compare.mjs --all-routes --platform android --threshold 0.15

# CI mode — fail if any diff > threshold:
node scripts/vision-compare.mjs --all-routes --threshold 0.1 --strict && echo "visual parity OK" || echo "visual diff detected"
```

### 6d. Deep links → route mapping

| Web (Next) path | Mobile (expo-router) | Deep link | Notes |
|---|---|---|---|
| `/c` | `app/(tabs)/chat.tsx` | `gaia://chat` | Chat home / new conversation |
| `/c/:id` | `app/chat/[id].tsx` | `gaia://chat/<id>` | Existing conversation |
| `/todos` | `app/(tabs)/todos.tsx` | `gaia://todos` | Todos list |
| `/settings` | `app/(tabs)/settings.tsx` | `gaia://settings` | Settings |
| `/integrations` | `app/integrations/index.tsx` | `gaia://integrations` | Integrations |

Add new rows as you add routes. The script reads `expo-router-sitemap` when `--all-routes` is passed, so it stays in sync.

---

## 7. Vision Prompt — Feeding Screenshots to the LLM

`pixelmatch` catches pixel diffs but not **semantic parity** (e.g., "web shows a button, native shows a drawer — same function but different UX"). Use a vision LLM as the second gate.

### 7a. Prompt template (copy into script or agent instruction)

```
You are a senior mobile QA comparing a WEB screenshot (left/first image) and a NATIVE iOS screenshot (right/second image) of the SAME route in the Gaia app.

Context: Gaia web is Next.js (apps/web), native is Expo 55 + expo-router (apps/mobile). Both should render identical content, navigation, and state for the same seeded dev user (dev@gaia.local) — see apps/web/e2e/harness.ts.

Task: Compare the two images and respond in STRICT JSON only.

```json
{
  "verdict": "PASS" | "FLAG" | "BLOCK",
  "confidence": 0.0-1.0,
  "diffPixelsApprox": "<estimate of % pixels differing>",
  "issues": [
    { "severity": "low|medium|high", "type": "layout|content|color|typography|missing-element|extra-element|navigation", "description": "one sentence", "location": "where in the screen" }
  ],
  "notes": "one sentence summary — mention if differences are expected (e.g., web-only browser chrome vs native tab bar)",
  "expectedDiffsDismissed": ["list any differences that are intentionally platform-specific and should NOT count as failures"]
}
```

Rules:
- PASS = visually equivalent for the user (allow platform chrome differences).
- FLAG = noticeable parity gap that should be filed but not blocking (e.g., spacing, font weight).
- BLOCK = functional parity break (missing content, wrong state, broken navigation).
- Ignore: browser URL bar, iOS status bar, scrollbar, font smoothing.
- Call out: missing seeded data ("Sample todo 1" must appear on /todos in both), composer placeholder "What can I do for you today?" on /c.

Images: [web.png, native.png, optional diff.png (red pixels = mismatches)]
Diff ratio from pixelmatch: {diffRatio:.4f} (threshold {threshold})
```

### 7b. API call shapes

**Anthropic Claude (vision):**

```js
const b64 = (p) => fs.readFileSync(p).toString("base64");
const res = await anthropic.messages.create({
  model: "claude-sonnet-4-20250514",
  max_tokens: 1024,
  messages: [{
    role: "user",
    content: [
      { type: "text", text: promptWithDiffRatio },
      { type: "image", source: { type: "base64", media_type: "image/png", data: b64(webPath) } },
      { type: "image", source: { type: "base64", media_type: "image/png", data: b64(nativePath) } },
      ...(diffPath ? [{ type: "image", source: { type: "base64", media_type: "image/png", data: b64(diffPath) } }] : []),
    ]
  }]
});
console.log(JSON.parse(res.content[0].text));
```

**OpenAI GPT-4o:**

```js
const toDataUrl = (p) => `data:image/png;base64,${fs.readFileSync(p).toString("base64")}`;
const res = await openai.chat.completions.create({
  model: "gpt-4o",
  response_format: { type: "json_object" },
  messages: [{
    role: "user",
    content: [
      { type: "text", text: promptWithDiffRatio },
      { type: "image_url", image_url: { url: toDataUrl(webPath) } },
      { type: "image_url", image_url: { url: toDataUrl(nativePath) } },
    ]
  }]
});
```

**Pi agent shorthand (if vision is built-in):** The agent can call `automation_take_screenshot` + `take_screenshot` (chrome-devtools) and the returned `image/jpeg` blocks are automatically in its vision context — no manual base64 needed. Just paste the prompt above and the two images.

### 7c. Threshold + vision decision matrix

| pixelmatch `diffRatio` | Vision verdict | Action |
|---|---|---|
| `< 0.02` | `PASS` | Auto-pass. Log report. |
| `0.02–0.10` | `PASS` or `FLAG` | LLM decides — usually `FLAG` if layout shift > 4px. |
| `> 0.10` | `FLAG` or `BLOCK` | Always flag; `BLOCK` if content missing. |
| Any + `BLOCK` from LLM | `BLOCK` | Fail CI / assign to parity board. |

---

## 8. Reusable Script

Bundled at `scripts/vision-compare.mjs` (Node 22, ESM).

```bash
# Install deps once:
pnpm add -D pixelmatch@^7.2.0 pngjs@^7.0.0 sharp@^0.33.5 playwright@^1.62.1

# Usage:
node scripts/vision-compare.mjs --help
node scripts/vision-compare.mjs --web ./screenshots/web-c.png --native ./screenshots/native-c.png --out ./screenshots/diff-c.png --threshold 0.1 --vision
node scripts/vision-compare.mjs --all-routes --web-base http://localhost:3000 --platform ios --threshold 0.12 --vision
node scripts/vision-compare.mjs --all-routes --strict  # CI: exit 1 on BLOCK/FLAG
```

Full source: see `scripts/vision-compare.mjs`. Key env vars:

```bash
export OPENAI_API_KEY=sk-...        # for --vision via OpenAI
export ANTHROPIC_API_KEY=sk-ant-... # for --vision via Claude
export WEB_BASE_URL=http://localhost:3000
export EXPO_DEV_URL=http://localhost:8081
export PLATFORM=ios                 # ios | android
```

**What the script does:**

1. Captures web screenshot via Playwright (or reuses existing `--web` file).
2. Captures native screenshot via `xcrun simctl` / `adb` / Expo web fallback (or reuses `--native` file).
3. Normalizes both to 390×844 with `sharp`, writes to `./screenshots/.normalized/`.
4. Runs `pixelmatch` → `diff.png` + `report.json` entry.
5. If `--vision`, sends both images + diff to Anthropic/OpenAI with the prompt from §7a, appends `visionVerdict`.
6. Emits `report.json` + `report.html` for triage.

---

## 9. Commands Cheat Sheet

Copy-paste for a fresh checkout:

```bash
# 0. Prerequisites
mise install && pnpm install
npx playwright install chromium --with-deps
brew install pngjs 2>/dev/null || true   # pngjs comes via npm; no brew needed
# Xcode (iOS sim): install from App Store, then:
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
xcrun simctl list devices

# 1. Start harness (one-time seed, then dev servers)
mise dev --sim   # api:8000 + web:3000 + sim stub (requires docker + DEV_AUTH_BYPASS_EMAIL)
# Verify seed:
curl -s http://localhost:8000/api/v1/dev/me | jq .  # should return dev@gaia.local

# 2. Start Metro
cd apps/mobile && npx expo start --port 8081 --clear &
# Wait for "Metro waiting on exp://..." then:

# 3. Register MCP (edit .mcp.json) — see §3 snippet — then restart agent

# 4. Single manual visual check:
mkdir -p ./screenshots
npx playwright screenshot --viewport-size "390,844" http://localhost:3000/c ./screenshots/web-c.png
xcrun simctl io booted screenshot ./screenshots/native-c.png  # or `automation_take_screenshot` via MCP
node scripts/vision-compare.mjs --web ./screenshots/web-c.png --native ./screenshots/native-c.png --out ./screenshots/diff-c.png --threshold 0.12 --vision

# 5. Full parity loop:
node scripts/vision-compare.mjs --all-routes --web-base http://localhost:3000 --platform ios --threshold 0.12 --vision --output-dir ./screenshots
open ./screenshots/report.html

# 6. CI (no vision, strict pixel gate):
node scripts/vision-compare.mjs --all-routes --threshold 0.08 --strict
```

---

## 10. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `xcrun: error: unable to find utility "simctl"` | Xcode not installed (only CLI tools) | `xcode-select -p` shows `/Library/Developer/CommandLineTools`. Install Xcode from App Store, then `sudo xcode-select -s /Applications/Xcode.app/Contents/Developer` and `sudo xcodebuild -runFirstLaunch`. |
| `No booted simulator devices found` | Simulator not booted | `open -a Simulator` → `xcrun simctl boot "iPhone 15"` + install app via `npx expo run:ios` or `xcrun simctl install booted <app.app>` |
| `expo-mcp: Error: required option '--dev-server-url'` | `.mcp.json` args missing URL | Ensure `args` includes `"--dev-server-url", "http://localhost:8081"` — Metro must already be running. |
| Screenshots are blank / white | App not yet loaded or wrong `appId` | Check `npx expo config --type public --json | jq .ios.bundleIdentifier` matches `io.heygaia.gaiamobile`; boot with `npx expo run:ios` first launch. |
| `pixelmatch: Image sizes do not match` | Web vs native dimensions differ | Script auto-resizes via `sharp` to 390×844. If you diff manually, resize first: `sharp(input).resize(390,844).toFile(...)`. |
| `ANDROID_HOME` path wrong | Hardcoded to `dhruvmaradiya` in repo's `.mcp.json` | Update to ` $HOME/Library/Android/sdk` on your machine, or `brew install --cask android-commandlinetools`. |
| Vision returns flag for expected platform chrome | Prompt not dismissing browser vs tab bar | Use the prompt's `expectedDiffsDismissed` list; or raise `--threshold` to 0.15 for that route. |
| `mcp-cache.json` doesn't show `expo-mcp` | Agent not reloaded | Restart Pi session (`:restart` or quit/reopen) — `mcp-cache.json` repopulates on startup. |

---

## 11. Next Steps (for agent 9+)

- Wire `scripts/vision-compare.mjs --strict` into CI (`scripts/ci/visual-parity.yml`).
- Add `testID`s to top 10 screens (search `grep -R "testID" apps/mobile` vs sitemap).
- Publish `report.html` to Vercel preview per PR.
- Graduate `loki` story snapshots once single-route loop is green.

