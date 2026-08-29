# GAIA Mobile ↔ Web Parity Audit — Pixel-Perfection & Reusability Roadmap
> Generated 2026-08-29 — codebase: `apps/mobile` vs `apps/web` vs `libs/shared/ts`
> Focus: Chat page, Convo list, Sidebar, Notifications (swipe), ToolCards/ToolIcons, Workflows page. Maximize reusability + insanely good UI/UX + Expo MCP vision pipeline.

---

## 0. Executive State

**Mobile is functionally strong, visually under-polished.**

| Signal | Verdict |
|---|---|
| Expo | `expo@55.0.27`, `@expo/cli@57.0.20`, React 19.1, RN 0.83, `heroui-native@beta`, `uniwind` (tailwind), `react-native-reanimated 4.5`, `flash-list 2.3`, `expo-router` file-based routing. Solid modern stack. |
| Web | Next.js (Heroui + Tailwind 4 + framer-motion), shadcn, motion, dexie sync. Extreme attention to detail — 20+ composable Chat layouts, message scroller stickiness, file drop, voice mode, founder letter, holographics. |
| Shared | `@gaia/shared` already extracts the hard logic: `chat/streaming.ts` (parseChatStreamEvent, applyStreamEvent, TurnAccumulator), `chat/types`, `icons/tool-icon-config`, `hooks/*Base`, `api/*`, `utils`. Mobile **already consumes** shared streaming (see `apps/mobile/src/features/chat/api/chat-stream.ts` → `parseChatStreamEvent` + `turnAccumulatorRef`). Web uses `turnManager/turnSession`. |
| Gap | Styling tokens duplicated, icon set diverged in rendering, convo-list grouping diverged, sidebar feature-switching missing, notifications swipe exists on mobile but visual tokens not 1:1, tool-card primitives have spacing/size debt, workflows page exists but lacks parity on steps/execution. |

**TL;DR**: No screen is missing — every web page has a mobile counterpart (`app/(app)/c/[id]` chat, `(tabs)/notifications`, `(app)/workflows`, etc). The gap is **pixel perfection**: colors, radii, spacing, typography, icon sizing/background pulse, grouped-list headers, empty states, and shared extraction of the *UI layer* (not just the data layer).

---

## 1. Parity Matrix (what's at stake for your 3 target surfaces)

| Surface | Web has | Mobile has | Gap / Pixel debt | Reuse opportunity | Priority |
|---|---|---|---|---|---|
| **Chat page** | `ChatPage.tsx` → `ChatWithMessages` + `NewChatLayout` + `MessageScroller` (stick-to-bottom, content-visibility trick), `Composer` (Toolbar + Mode tabs + SlashCommandDropdown + FileDropModal + Selected*Indicators + IntegrationsBanner + VoiceControlBarContainer), `ChatSection` per-message breakdown, `turnManager` with stallWatchdog + streamResume after reload. | `app/(app)/c/[id].tsx` → `ChatScreenContent` (FlashList + `useChat` + `TurnAccumulator` from shared), `ChatMessage` (User/AI split, emoji-only sizing, ThinkingBubble, ActivityBlock, LinkPreview, MemoryIndicator, FollowUps, FailedResponse), `Composer` (plus/attachment/workflow/slash + reply preview), `VoiceRecorder`. | **Medium-high**: Web composer is 3-row pill with `rounded-3xl bg-zinc-800 px-1 pt-1 pb-2` + toolbar icons (Wrench, Plus, Send) + mode selection + file preview above. Mobile composer uses `rounded-[20] bg-zinc800` single-row `plus | tools | input | send` — close but not identical radii/shadows/haptics. Web messages use `content-visibility:auto` + `MessageScrollerProvider` instant jumps; mobile throttles `scrollToEnd` every 60ms + `LayoutAnimation` — good but different curve. Web empty state (`FounderLetter` + `NewChatLayout` grid suggestions) → mobile has `EmptyChatState` but simpler. | **High**: `useChat` is 90% shared already (chat-stream.ts mirrors web parser). Extract `useChatBase` + `TurnAccumulator` is done — next move `composer state` (`composerStore`), `messageParts` splitting, `thinkingParser`, `messageBreakUtils` all already in `@gaia/shared/utils`. Mobile should import them instead of duplicating. | **P1** |
| **List of convos** | `MainSidebar` → `ChatsList.tsx`: Accordion with groups `Today / Yesterday / Previous 7 days / Previous 30 days / All time` + `Starred Chats` + `Created by GAIA` (systemPurpose), `ChatTab` per row (star unread dot, system icon), `IntersectionObserver` sentinel + `useInfiniteConversations` infinite scroll. | `features/chat/components/sidebar/chat-history.tsx`: FlatList of `ChatItem` with `HighlightedText` search, `ReanimatedSwipeable` delete action, `StreamingDot` pulsing, `Modal` rename, `DrawerLayout`. Grouping done via `groupConversationsByDate` hook (check `use-conversations.ts` — simpler grouping than web's 5 buckets). | **High**: Mobile grouping is Today/Yesterday/thisWeek/earlier (see notifications list) vs web's 5-bucket `getTimeFrame`. No accordion disclosure (web accordion keeps every group open but header is 1:1 style `text-zinc-500 uppercase tracking-wider`). Mobile row styling: `px12 py sm+2 gap sm bg rgba(0,187,255,0.10) + 3px accent bar` vs web `ChatTab` which uses `HoverCard` + `Tooltip` + `Kbd`. Missing `Starred` + `System` sections. No infinite sentinel — uses pagination via `useConversations` (verify hasMore). | **High**: Move `getTimeFrame`, `timeFramePriority`, grouping, star/system filtering to `@gaia/shared/hooks/useConversationsBase` (or `utils/conversationGroups`). Single token import on both apps. Also move `Highlight` logic to shared. | **P0** — sidebar is first paint; fix grouping + headers = instant pixel parity win. |
| **Sidebar** | `components/layout/sidebar/MainSidebar.tsx` switches per route: `TodoSidebar`, `MailSidebar`, `WorkflowsSidebar`, `SettingsSidebar`, `IntegrationsSidebar`, default `NewChat` button (`BubbleChatAddIcon` + `Kbd C`) + `ChatsList`. Width token via `sidebarWidth` context, border `border-zinc-800`, `Tooltip` on New Chat. | `shared/components/layouts/app-shell.tsx` → `DrawerLayout (FRONT)` + `SidebarContent` (SafeAreaView bg #1a1a1a). `SidebarContent` = `SidebarHeader` (search + NewChat icon when inChats) + `SidebarNav` (Tasks/Integrations/Workflows/Chats with active `rgba(0,187,255,0.10)` + 3px bar) + `TodoSidebarSection` (only on /todos) + `ChatHistory` (only on chats) + `SidebarFooter`. | **Medium**: Web sidebar is static rail (desktop). Mobile is drawer (`FRONT` overlay, `overlayColor rgba(0,0,0,0.5)`, `DrawerType.FRONT` + `sidebarWidth` from `useResponsive`). Visual: web rails have `bg-zinc-900` + `w-64` + `border-r border-zinc-800`; mobile drawer uses `#1a1a1a` + `bg-[#111111]` outer — slightly different zinc. Missing per-route sidebars (web shows `TodoSidebar` with Projects/Priorities/Labels, `WorkflowsSidebar` — mobile only has `TodoSidebarSection` but not `IntegrationsSidebar`/`WorkflowsSidebar`). New Chat button styling missing `Kbd` hint. | **Medium**: Extract `NAV_ITEMS` config + per-route sidebar switcher to `libs/shared` constants. Share `SIDEBAR_WIDTH`, `ACTIVE_BG/BAR` tokens (already duplicated in `colors.ts` vs web `globals.css`). Unify `design-tokens.ts` generation from web `globals.css`. | **P1** |
| **Notifications page** | `app/[locale]/(main)/notifications/page.tsx` → `NotificationsList` (Grouped by timezone via `groupNotificationsByTimezone`, headers `text-xs font-semibold tracking-wider text-zinc-500 uppercase`), `EnhancedNotificationCard` (bg-zinc-800/70 unread vs /30 read, rounded-2xl, action chips bg-primary/10 vs bg-red-500/10 vs bg-zinc-800/50), `NotificationCenter` popover (PopoverContent w-96 rounded-2xl border-zinc-700 bg-zinc-800 p-0 + Tabs unread/all + Badge). `useNotifications` with `NotificationStore` single unkeyed entry, bulk actions. | `app/(app)/(tabs)/notifications/index.tsx` + `app/(app)/notifications/index.tsx` → `features/notifications/components/notifications-list.tsx` (`NotificationsList` grouped by `getTimeGroup` → Today/Yesterday/thisWeek/earlier) + `notification-card.tsx` (`Swipeable` with left Read (00bbff 12% + badge), right Snooze (amber) / Archive (zinc) / Dismiss (red 12%), haptics, `renderLeftActions`/`renderRightActions` with `Animated` translateX, long-swipe commits without tap), `NotificationCard` bg `rgba(39,39,42,0.70)` unread / `0.30` read / `rgba(0,187,255,0.10)` selected, rounded-16. Already beautiful swipe! | **Low gap on interaction, Medium on pixels**: Mobile swipe IS more beautiful than web (web has no swipe — only tooltip Mark-as-Read). But header copy differs: web says `Today/Yesterday/Previous 7 days/...` while mobile says `Today/Yesterday/This Week/Earlier` — reconcile. Web card: `rounded-2xl bg-zinc-900 p-4` + `h-1.5 w-1.5 bg-primary` dot + `Button variant flat isIconOnly`. Mobile card: `rounded-16 p-16/14 gap 12` + `6×6 dot #00bbff`. Spacing: web `space-y-8` between groups + `space-y-2.5` inside; mobile uses `marginTop index===0?8:32 marginBottom12` + `marginBottom10` — close but not tokenized. Empty state: both use NotificationIcon circle but web is `h-16 w-16 bg-zinc-900/50 ring zinc-800`, mobile is `64 bg rgba(18,18,18,0.5) border #27272a` — unify. | **Medium**: `groupNotificationsByDate/timezone` + filter already in `@gaia/shared/hooks/useNotificationsBase` (`filterNotifications`, `groupNotificationsByDate`, `getNotificationIcon`). Mobile's `getTimeGroup` duplicates it. Import shared instead. Also share `NotificationStatus` enum correctly. | **P0** for your ask — notifications swipe is your showcase; do a token sync pass and it's done. |
| **ToolCards** | `config/openui/primitives/ToolCard.tsx` (`ToolCard size compact|standard|wide|full → max-w-md/2xl/4xl, rounded-2xl bg-zinc-800 p-4, title text-sm font-semibold zinc-100, subtitle xs zinc-400, gap 3`). 30+ tool-specific primitives in `openui/components/*`, unified `ToolInset`, `FileTreeView`, `MapBlockView`, etc. `ToolDataRenderer` routes per tool. | `features/chat/tool-data/primitives/tool-card-shell.tsx` (`View rounded-2xl bg-zinc-800 p-4 mx-4 my-1`) + `tool-card-header`, `tool-card-inner`, `collapsible-card`, `section-label`, `web-result-primitives`, `tool-icons.tsx`. 20+ cards in `tool-data/cards/*` (calendar, email, weather, chart, deep_research, etc.) — many near-identical to web but with RN primitives (no `cn`). | **Medium**: Spacing/border consistency: web cards are inside message transcript `max-w-2xl` with `p-4` no `mx-4` (parent handles centering). Mobile adds `mx-4 my-1` — correct for RN but radii mismatch (web `16`, mobile `16` OK). Missing web `ToolInset` (inner surface `bg-zinc-900 rounded-xl p-3`) — mobile uses `ToolCardInner` but less detailed. Shadows/rings missing. ChartCard, Calendar cards: confirm `syntax-theme`, `colors.ts` zinc. | **High**: Extract `ToolCardShell` + variant logic to `libs/shared/icons` or new `libs/shared/ui` (or at minimum share `tool-icon-config` + `colors` + `section-label` tokens). Share `toolData` shape (`StreamToolDataEntry`) already shared. | **P1** |
| **ToolIcons** | `features/chat/utils/toolIcons.tsx` → `getToolCategoryIcon(category, opts, iconUrl)` uses `toolIconConfigs` (image vs component), `iconAliases`, `normalizeCategoryName`, `AutoInvertIcon` via `next/image` (+ unoptimized svg, 3× raster). Background `relative rounded-lg p-1` + `absolute inset-0 rounded-lg ${bgColor} animate-pulse` when pulsating. | `features/chat/utils/tool-icons.tsx` → same `getToolCategoryIcon` but renders via `react-native-svg` + `expo-image` + `PulsatingBackground` (Animated loop 1s 0.4→0.8). Uses `INTEGRATION_LOGOS` fallback (mirrors web's `getIconPath`). Consumes `@gaia/shared/icons` `getToolIconConfig`. | **Tiny gap**: Config is SHARED (`libs/shared/ts/src/icons/tool-icon-config.ts` → `toolIconConfigs`, `normalizeCategoryName`, `iconAliases` all shared). Rendering diverges as expected (RN vs DOM) but raw colors `bgColorRaw`/`iconColorRaw` are shared. Parity good. Keep it: don't branch configs. | **Done**: Already maximized. Just ensure `icon-paths.generated.json` is run on both (`pnpm tsx apps/web/scripts/extract-icon-paths.ts` copies to shared; mobile's `gaia-icons.tsx` reads from `@shared/ts/src/icons/icon-paths.generated.json`). | **P2** — maintenance only. |
| **Workflows page** | `app/[locale]/(main)/workflows/[id]/page.tsx` + `features/workflows/*` (triggers handlers, schedule, GitHub/Gmail/Notion integrations, `TriggerSettingsCard` etc). Rich builder with `workflow-steps-editor`, `regenerate-steps-sheet`, `ExecutionHistory`. Uses same `workflowsApi` as mobile. | `features/workflows/components/workflow-list-screen.tsx` (`FlatList` sections My/Explore/Community), `workflow-detail-screen.tsx` + `detail/*` (Hero, Header, Steps, Tabs, Actions, MoreMenu), `create-workflow-modal`, `edit-workflow-modal`, `schedule-builder`, `dynamic-trigger-form`, `workflow-steps-editor` (likely simpler than web). Uses `useWorkflows`, `useExploreWorkflows`, `workflow-api.ts` → `WORKFLOW_ENDPOINTS` from shared. | **Medium-low**: Mobile workflows page EXISTS and is not tough — you already built it. Gap: trigger picker complexity (web has dedicated handlers per integration: `github.tsx`, `gmail.tsx`, `notion.tsx`, `schedule.tsx`; mobile has single `dynamic-trigger-form` + `trigger-picker-sheet`). Execution polling (`use-workflow-polling`) vs web's server. Page weight ~ moderate to reach web parity; not blocking core chat+notifications. | **High** for reuse: `workflowTypes`, `trigger-types`, `workflowsApi` already shared (`libs/shared/ts/src/api/workflowsApi.ts` + `hooks/useWorkflowsBase`). Share `trigger-types` validators (`validation/workflowSchemas.ts`). Steps editor schema unify. | **P2** — you asked focus on chat+notifications first; do workflows after pixel pass. Effort: ~1-2 weeks to match trigger builder 1:1 if you want perfection. Otherwise current is shippable. |

> **Extra features only on mobile (not on web):** `app-dev/tool-gallery` (dev preview of every tool card), `wake-word` (`useHeyGaia` + onnxruntime-react-native), `voice-recorder`, offline banners (`OfflineBanner`, `OfflineState`), biometric `auth-storage`/`expo-secure-store`, `expo-notifications` push (interactive HIL approve/deny from notification), `bottom-sheet` gestures + `haptic-tab`, `reactotron`, parallax scroll view. **Only on web (not on mobile):** Mail inbox, Desktop tools / MCPAppRenderer, Pins, Marketing pages, Voice mode waveform + LiveKit, founder letter inject, file drop from OS.

---

## 2. What blocks pixel perfection today (the ungenerous list)

1. **Design tokens are duplicated, not generated.** Web source of truth is `apps/web/src/app/styles/globals.css` (HSL vars). Mobile hand-copied into `apps/mobile/src/lib/design-tokens.ts` (hex). Drift risk: e.g. `muted #0f1629 vs  #0f1629 OK`, but `card #030711` matches; still needs codegen. Also `typography` (Inter 400 + AnonymousPro mono) vs web `Geist/Aeonik/PP Editorial` — not aligned.

2. **Spacing not tokenized across chat/notif/toolCards.** Web: Tailwind `spacing.md/sm/lg` via theme; mobile: `useResponsive()` + `moderateScale` — similar idea but numbers never audited side-by-side. Results: `composer rounded-3xl (24px) vs 20`, `notification card rounded-16 vs rounded-24 (popovers)`, `group header tracking-[1px] vs 1`. Create table.

3. **Convo list grouping is functionally different.** Web `getTimeFrame`: `Today / Yesterday / Previous 7 days / Previous 30 days / All time`. Mobile `getTimeGroup`: `Today / Yesterday / This Week / Earlier`. Same feature, different buckets → feels like a bug to the user. Fix is one shared fn.

4. **Sidebar per-route context missing.** Web Contextually swaps sidebar (Todos shows Projects/Priorities/Labels with counts, Integrations shows categories, Workflows shows types). Mobile only swaps `TodoSidebarSection`; missing Integrations/Workflows sidebars. Drawer `FRONT` vs web `side rail` is fine, but content gap is noticeable.

5. **Hook duplication without shared base.** Mobile `hooks/use-chat.ts` (420+ lines) + web `features/chat/stream/*` both implement SSE lifecycle, stall watchdog (45s), settle guards, optimistic conversation_id, replyTo, workflow/tool selection. The **parsing + accumulator** is shared (good), but **lifecycle** still duplicated. Use `createSSEConnection` vs web `turnSession`. Extract `useChatStreamBase` in shared.

6. **ToolCard shell not variant-aware.** Web `ToolCard size compact/standard/wide/full → max-w-*`; mobile shell fixed width (`mx-4`). Breaks tablet/web routing (`expo start --web`).

7. **Needs screenshot-driven QA loop.** No vision harness today — you eyeball. Add one.

---

## 3. Reusability Audit — what's already shared, what to move next

### Already in `libs/shared/ts/src`

```
shared/chat/streaming.ts      → ChatStreamEvent, parseChatStreamEvent, TOOL_CALLS_DATA_TOOL_NAME, Subagent*
shared/chat/turnAccumulator.ts→ createTurnAccumulator, applyStreamEvent
shared/icons/*                → tool-icon-config, integration-logos, icon-paths.generated.json
shared/api/*                  → conversationsApi, notificationsApi, workflowsApi, todosApi, etc.
shared/hooks/*Base            → useNotificationsBase, useTodosBase, useIntegrationsBase, useWorkflowsBase
shared/types/*                → chat, notification, integration, todo, workflow
shared/utils/*                → thinkingParser, messageBreakUtils, openui-parser, formatters
shared/validation/*           → todo/workflow schemas
```

Mobile already imports from shared in `chat-stream.ts`, `tool-icons.tsx`, `todos`, `integrations`, etc. — that part is **well done**.

### Move to shared next (prioritized, effort-tagged)

| # | Module | From (mobile+web duplicate) | To (`libs/shared/ts/src/...`) | Why | Effort |
|---|---|---|---|---|---|
| 1 | Time grouping | `web ChatsList getTimeFrame` + `mobile chat-history groupConversationsByDate` + `mobile notifications-list getTimeGroup` | `shared/utils/dateGroups.ts` or `shared/chat/conversationGroups.ts` | Instant pixel parity — one bucket config, one header style | S (1 file, <100 lines) |
| 2 | Design tokens | `web globals.css` + `mobile design-tokens` + `mobile colors` | `shared/design/tokens.ts` + codegen `shared/design/tokens.generated.ts` from css vars (or build script `pnpm tokens:sync`) | Stops drift, unlocks pixel-perfect colors/radii/font | M (script + snapshot tests) |
| 3 | Composer state | `web stores/composerStore` + `mobile stores/composer-store` + reply workflow tool selection | `shared/todos/store.ts` exists as pattern → `shared/chat/composerStore.ts` (zustand, optional peer) | Single source for attachments/selectedTool/replyTo — merge once | M |
| 4 | Message parts | `mobile ChatMessage useMessageParts` + `web ChatRenderer messageContentUtils` | `shared/utils/messageContent.ts` (already `messageBreakUtils` + `thinkingParser` there) | Import don't copy | S |
| 5 | Notification helpers | `mobile NotificationsList grouping` + `mobile notifications-base` | extend `shared/hooks/useNotificationsBase` → add `NotificationCard` chrome props & empty state config | Finish the Base hook contract | S |
| 6 | ToolCard primitives | `web ToolCard` + `mobile tool-card-shell/inner/header` | `shared/ui/toolCardTokens.ts` (size → max-w/p/radii/bg) + per-platform renderers reusing tokens | Unify radii/spacing, keep renderers separate (RN vs DOM) | M |
| 7 | Chat stream lifecycle | `mobile fetchChatStream + use-chat` abort/stall/reconcile + `web turnSession/stallWatchdog` | `shared/chat/useChatStreamBase.ts` (headless, no UI) returning `{send, cancel, state}` with `parseChatStreamEvent`, `applyStreamEvent`, stall timeout config | The big reuse win — eliminates duplicated retry/settle/reconcile logic | L (1-2 days, needs both app callsite migrations) |
| 8 | Sidebar nav config | `web MainSidebar VARIANTS + mobile SidebarContent NAV_ITEMS` | `shared/constants/navigation.ts` (`NAV_ITEMS`, route → sidebar variant map) | Single place to add workflows etc | S |
| 9 | GAIA icons pipeline | `web scripts/extract-icon-paths.ts` already writes to `shared/icons/icon-paths.generated.json` | Keep — just ensure mobile build watches it (metro extraNodeModules) | Already good | XS |

**Target after this list:** mobile imports design tokens, time grouping, composer state, message parts, notification helpers, sidebar config, tool-card tokens, and ideally stream lifecycle — all from `@gaia/shared`. Only renderers remain per-platform.

### Shared move checklist (copy to PR description)

```
- [ ] tokens:sync script + @gaia/shared/design imports in mobile design-tokens
- [ ] shared/utils/conversationGroups + import in ChatsList + chat-history + notifications-list
- [ ] shared/chat/composerStore + adopt in web Composer + mobile Composer
- [ ] shared/utils/messageContent (messageParts + thinking) adoption
- [ ] shared/hooks/useNotificationsBase groupBy + adoption
- [ ] shared/ui/toolCardTokens + mobile/web renderers consuming
- [ ] shared/chat/useChatStreamBase + web turnSession + mobile use-chat migration
- [ ] shared/constants/navigation + sidebar adoption
- [ ] visual regression snapshots (see §5) green
```

---

## 4. Beautiful Notifications — spec for the swipe you asked for (`swiping and shit`)

You already have a strong implementation in `apps/mobile/src/features/notifications/components/notification-card.tsx` — keep it, then polish to this spec (which closes the web vs mobile pixel gaps above):

```typescript
// Mobile — already exists, lock in:
<Swipeable
  friction={2}
  rightThreshold={60}
  leftThreshold={60}
  renderLeftActions={isUnread ? renderLeftActions : undefined} // Read: #00bbff @ 12% + badge icon
  renderRightActions={renderRightActions} // Snooze (amber 16%) / Archive (zinc60) / Dismiss (red12)
  onSwipeableOpen={(direction)=>{
    if(direction==="right") onArchive?handleArchive():handleDismiss()
    if(direction==="left" && isUnread) handleMarkAsRead()
  }}
>
  // Card: rounded-16 bg rgba(39,39,42,0.70) unread / 0.30 read + 1.5px #00bbff selected
  // Title: 15/18 semibold (#ffffff unread / #71717a read) + 6px #00bbff dot
  // Body: 13/20 (#a1a1aa unread / #52525b read) lineClamp 3
  // Time: 11 (#52525b) top-right + CheckmarkBadge01 16 (#71717a) for quick mark
  // Actions: chips 32h 8radius px14 py9 bg per tone (primary 00bbff10, danger red10, default zinc50) — filter out redirect (card tap handles it)
  // Haptics: Light on Read, Medium on Archive/Dismiss/Snooze
</Swipeable>
```

**Polish list (1 PR, < 150 lines):**
- Sync group headers to shared `Today / Yesterday / Previous 7 days / Previous 30 days / All time` (or decide on one taxonomy and change both).
- Normalize `contentContainerStyle` to `paddingHorizontal 16 paddingTop 12 paddingBottom insets.bottom+24` → switch to tokens `spacing.md / spacing.lg`.
- Unify `refreshControl tintColor #00bbff` (mobile) vs web spinner `border-zinc-700 border-t-zinc-50` — pick one brand constant.
- Replace inline `fontSize 15/13/12` with `typography.fontSize` tokens.
- Add `isSelectMode` batch actions footer (already wired) → show when long-press toggles selection.
- Ensure `onActionPress` for `api_call/workflow` uses shared `useNotificationActions` logic (mobile has parallel implementation in `use-notification-actions.ts` — merge onto `shared/hooks/useNotificationsBase`).

Web stays no-swipe; add `Tooltip` + `Button variant flat` on cards for hover parity (already there in `NotificationItem`). Do **not** port swipe to web — swipe is a mobile signature moment.

---

## 5. How to get pixel-perfect parity (repeatable vision loop + Expo MCP)

### 5.1 Expo CLI already ready

```bash
# already installed — verify
npx expo --version          # 57.0.20
npx expo --help | head -n 20
npx expo start --web --port 19006   # mobile web target for pixel compare
npx expo start                       # QR / simulator target
xcrun simctl list devices | grep -i iphone # iOS simulator ids
npx expo run:ios --device "iPhone 15 Pro"  # prebuild target if needed
```

Variant workflow for chat/notif/workflows detail:

```bash
# Staging vs local
pnpm --filter gaia-mobile dev:staging   # dotenv -e .env.staging expo start
pnpm --filter gaia-mobile dev:local
```

### 5.2 Expo MCP — install + wire to pi

`expo-mcp@0.2.4` is the official MCP server (tunnel + screenshot + device control + logs). It is **not** `@expo/mcp` (that's 404).

```bash
# install as dev dep so pi can spawn it reliably
pnpm --filter gaia-mobile add -D expo-mcp@0.2.4
# or globally if you prefer
pnpm add -g expo-mcp
```

**MCP config for pi** — append to whichever MCP config your binary reads (check both, `~/.config/pi` doesn't exist on this host; pi reads `~/.pi/agent/settings.json` packages + runtime mcp.json):

```jsonc
// .pi/mcp.json  OR  ~/.pi/mcp.json  — add this server
{
  "mcpServers": {
    "expo": {
      "command": "npx",
      "args": ["-y", "expo-mcp"],
      "cwd": "/Users/aryan/Projects/gaia/apps/mobile",
      "env": {
        "EXPO_TOKEN": "${env:EXPO_TOKEN}",
        "EXPO_DEBUG": "0"
      },
      "timeout": 120000
    }
  }
}
```

If your pi host uses `mcp_config.json` in the global dir, use:

```bash
# discover pi's config path
ls -la ~/.pi 2>&1 | head -n 30
cat ~/.pi/agent/settings.json | grep -i mcp
# then append the server block above
```

After editing, restart `pi` (`pi --list-providers` or relaunch). Verify in `pi`:

```
/mcp list
expo — tools: get_screenshot, open_simulator, get_logs, start_tunnel, list_devices, etc.
```

**Expo MCP tool contract (what you get):**

| Tool | Vision use |
|---|---|
| `list_devices` | enumerate simulators |
| `open_simulator` | boot iPhone 15 Pro target |
| `get_screenshot` | **pixel capture** of current screen — feed straight to vision model |
| `get_logs` | log stream while streaming chat |
| `start_tunnel` | expose to physical device |
| `execute_command` | `xcrun simctl status_bar …` for deterministic screenshots |

### 5.3 Give the agent screenshots + vision (the loop you asked for)

You want the agent to **see** web vs mobile. The workflow is three steps — web capture, mobile capture, vision diff. Automate it so future agents reuse it.

**A. Web capture (Playwright — already in `apps/web`)**

```ts
// scripts/vision/capture-web.ts (add to repo)
import { chromium } from 'playwright';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto('http://localhost:3000/c/<conversation-id>', { waitUntil: 'networkidle' });
await page.waitForSelector('[data-testid="chat-section"]');
await page.screenshot({ path: 'tmp/web-chat.png', fullPage: false });
await page.goto('http://localhost:3000/notifications');
await page.screenshot({ path: 'tmp/web-notifs.png', fullPage: false });
```

Or reuse existing harness: `apps/web/e2e/harness.ts` + `playwright.config.ts` already knows how to boot web. Add a dedicated `vision` profile.

**B. Mobile capture (Expo MCP)**

From inside `pi` with `expo` MCP connected:

```
> get_screenshot  // no args — returns png buffer / path
> open_simulator {"deviceId":"iPhone 15 Pro (18.0)"}
> get_screenshot {"target":"simulator"}
```

Fallback without MCP (CI or headless):

```bash
xcrun simctl io booted screenshot tmp/mobile-chat.png
# deterministic status bar (time 9:41, 100% battery) for stable diffs:
xcrun simctl status_bar booted override --time "9:41" --batteryState charged --batteryLevel 100 --cellularMode active --cellularBars 4 --wifiBars 3
```

For physical device via tunnel, MCP `get_screenshot` is the only stable path (simctl doesn't see hw).

**C. Vision diff prompt (reuse in every parity PR)**

Create `scripts/vision/compare.md` template:

```md
You are a visual QA reviewer. You have two screenshots:
- LEFT = web chat page (ground truth, Next.js + Tailwind, perfect)
- RIGHT = mobile chat page (Expo on iOS)

Compare pixel for pixel for: header, convo list rows, message bubbles (radii, padding, tails), tool cards, composer pill, timestamps, empty state.
List every difference with severity (critical/noticeable/nit):
- color/contrast drifts
- radii (web rounded-3xl 24px vs mobile rounded-[20]) 
- spacing (margins between bubbles, group headers)
- typography (weight, lineHeight, tracking)
- icon size/background (16 vs 20, zinc700 vs zinc800)
- shadows/rings
For each critical/noticeable, suggest exact fix (file + token).
```

Then in `pi`, attach both images:

```
# in pi: /attach tmp/web-chat.png tmp/mobile-chat.png
Compare per scripts/vision/compare.md — produce markdown table Severity | Element | Web | Mobile | Fix.
```

Automated diff bonus:

```bash
# pixelmatch against golden snapshots (once you lock them)
pnpm add -D pixelmatch pngjs
# scripts/vision/diff.ts — read tmp/web-chat.png vs tmp/mobile-chat.png → diff.png + % diff
```

**D. Wire into agent skill so future parity work auto-captures:**

Add `apps/mobile/scripts/vision-capture.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
OUT="tmp/vision-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
# web
npx playwright screenshot --url "http://localhost:3000/c/demo" --viewport "1440,900" "$OUT/web-chat.png"
npx playwright screenshot --url "http://localhost:3000/notifications" "$OUT/web-notifs.png"
# mobile simulator
xcrun simctl io booted screenshot "$OUT/mobile-chat.png" 2>/dev/null \
  || npx --yes expo-mcp get_screenshot --output "$OUT/mobile-chat.png"
echo "$OUT"
```

Commit it; instruct subagents in parity PRs to run it and attach under `tmp/vision-*`.

---

## 6. Concrete Chat/Sidebar/Notifications Polish Backlog (max reusability, min effort)

### Do first (1-2 days, huge visual ROI)

- [ ] **Tokens sync** — write `scripts/sync-design-tokens.ts` that reads web `globals.css` vars → writes `libs/shared/ts/src/design/tokens.generated.ts` + asserts mobile imports it (add `pnpm sync:tokens` to CI). Snapshot test (`tokens.test.ts`) comparing `design-tokens.ts` vs `tokens.generated`.
- [ ] **Convo grouping unified** — @gaia/shared `conversationGroups.ts` → wire ChatsList + chat-history + notifications-list + useConversationsBase tests.
- [ ] **Notifications header parity** — swap mobile `This Week/Earlier` to shared `Previous 7 days / Previous 30 days / All time` (or choose one label set explicitly and migrate both — document in `/openspec`).
- [ ] **NotificationCard token sweep** — replace inline `fontSize 15/13/12` + `rgba(...)` with `colors.*` + `typography` + `spacing` throughout card + list.
- [ ] **Composer radii + shadows** — mobile `moderateScale(20,0.5)` → `24` on chat page, add `shadowOpacity 0.08` matching web `shadow-xl` token (`shadowColor #000`).
- [ ] **Empty states audited** — own file `mobile/src/features/chat/components/chat/empty-chat-state.tsx` vs web `NewChatLayout GridSection + FounderLetter` — side-by-side screenshot fixes.

### Do next (3-5 days, structural)

- [ ] **Composer store into shared** — new `shared/chat/composerStore.ts` (zustand optional) consumed by both `Composer.tsx` impls; keep per-platform `ComposerInput` renderers thin.
- [ ] **ToolCard tokens** — `shared/ui/toolCard.ts` with `rounded 16`, `p 16 (mobile) vs 16 (web)`, `bg zinc800`, size → maxW; branch renderers keep RN vs DOM.
- [ ] **useChat stream base extraction** — `shared/chat/useChatStreamBase.ts` headless hook; adopt in web `useExecutorStream`/`useConversation` and mobile `use-chat`. Keep stall `45000` shared constant (already `STREAM_STALL_TIMEOUT_MS` = 45s in mobile — mirror web `stallWatchdog`).
- [ ] **Sidebar per-route variants** — port `IntegrationsSidebar` / `WorkflowsSidebar` data to mobile drawer (add sections, reusing shared `NAV_ITEMS` + `useIntegrations` categories).
- [ ] **Message scroller parity** — web `MessageScrollerProvider` snap-to-end logic vs mobile throttled `scrollToEnd` 60ms — harmonize affordance: mobile `isAtBottomRef` 80px threshold is web-parity; web also shows `MessageScrollerButton` (scroll-to-bottom) — mobile has `ScrollToBottomButton` but threshold hidden. Audit interaction together with screenshot.

### After chat+notifications P0 (when you want workflows pixel-perfect too)

- [ ] **Workflows trigger parity** — decide scope: (a) ship current mobile builder as-is (good), or (b) port each web trigger handler (`github.tsx`, `gmail.tsx`, `notion.tsx`, etc.) into mobile `dynamic-trigger-form` variants — adds overflow per integration, choose b only if workflows is a primary surface for your cohort.
- [ ] **ExecutionHistory + polling** — harmonize `use-workflow-polling` vs web polling intervals; share `workflowStages` types.

---

## 7. Screens Inventory — what we verified exists (so this audit is grounded)

| App | Path | Exists |
|---|---|---|
| mobile | `src/app/(app)/c/[id].tsx` chat | ✓ |
| mobile | `features/chat/components/sidebar/*` drawer | ✓ |
| mobile | `features/chat/components/chat/*` bubbles/tools | ✓ |
| mobile | `features/chat/utils/tool-icons.tsx` | ✓ (wraps shared) |
| mobile | `features/notifications/*` (card + list + swipe) | ✓ |
| mobile | `features/workflows/*` list+detail+sheets | ✓ |
| mobile | `lib/design-tokens.ts` | ✓ |
| mobile | `lib/gaia-icons.tsx` reading shared icon paths | ✓ |
| web | `src/features/chat/components/interface/ChatPage.tsx` | ✓ |
| web | `components/layout/sidebar/MainSidebar.tsx + ChatsList.tsx` | ✓ |
| web | `features/notification/components/NotificationCenter + EnhancedNotificationCard` | ✓ |
| web | `config/openui/primitives/ToolCard.tsx` | ✓ |
| web | `features/chat/utils/toolIcons.tsx` | ✓ (wraps shared) |
| web | `features/workflows/*` | ✓ |
| shared | `libs/shared/ts/src/icons/tool-icon-config.ts` | ✓ |
| shared | `libs/shared/ts/src/chat/streaming.ts + turnAccumulator` | ✓ |
| shared | `libs/shared/ts/src/hooks/*Base` | ✓ |
| shared | `libs/shared/ts/src/api/*` | ✓ |

---

## 8. Commands — run these today to lock in the loop

```bash
# 1) Install Expo MCP
pnpm --filter gaia-mobile add -D expo-mcp

# 2) Boot web + mobile simulators
pnpm --filter web dev                  # http://localhost:3000
pnpm --filter gaia-mobile dev:local    # or dev:staging
xcrun simctl boot "iPhone 15 Pro" 2>/dev/null; open -a Simulator

# 3) Verify Expo CLI + MCP (manual smoke)
npx expo --version
npx --yes expo-mcp --help
npx --yes expo-mcp list-devices

# 4) Add MCP server to pi (edit .pi/mcp.json per §5.2, restart pi)
cat .pi/mcp.json | jq . # verify block

# 5) Vision harness smoke
xcrun simctl io booted screenshot tmp/smoke-mobile.png && ls -lh tmp/smoke-mobile.png
npx playwright screenshot --help | head -n 20

# 6) Token sync dry run (after you add the script)
pnpm sync:tokens --check   # should fail until wired, then pass
```

---

## 9. Verdict

- **State**: Mobile is complete and shippable. No target screen is missing. Greatest distance from web is **visual density + grouping**, not architecture.
- **Pixel perfection path**: Token sync + grouping unified + notification header sweep + composer radii = 80% of the perceived gap, < 2 days.
- **Reusability path**: §3 table — 3 small PRs (groups, tokens, composer) then one structural PR (stream base). Every one reduces duplicated code *and* locks parity.
- **Notifications swipe**: Already better than web; needs token polish only, not interaction work.
- **Workflows**: Keep as-is for chat+notifications phase; expand triggers when workflows becomes primary.
- **Vision**: Install `expo-mcp`, add pi server block, run screenshots loop (§5.3) before/after every parity PR and attach both images to the PR — let the vision model (pi + attachments) be your QA robot.

*Next action for you:* approve this doc (`MOBILE_PARITY_AUDIT.md` checked into `apps/mobile` or repo root), then I'll open PR 1 (tokens + conversationGroups + notification header) with side-by-side screenshots captured via the harness above.
