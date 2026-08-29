# Foundation & Discovery — Audit: Tool Cards / Icons / Date Groups
**Agent 3 — 2026-08-29 | Branch: gaia (worktree /Users/aryan/Projects/gaia)**

## 1. Files Audited (exact paths)

| Concern | Path |
|---|---|
| **Mobile Tool Card Shell** | `apps/mobile/src/features/chat/tool-data/primitives/tool-card-shell.tsx` |
| | `apps/mobile/src/features/chat/tool-data/primitives/tool-card-header.tsx` |
| | `apps/mobile/src/features/chat/tool-data/primitives/tool-card-inner.tsx` |
| | `apps/mobile/src/features/chat/tool-data/primitives/collapsible-card.tsx` |
| | `apps/mobile/src/features/chat/tool-data/primitives/section-label.tsx` |
| | `apps/mobile/src/features/chat/tool-data/primitives/web-result-primitives.tsx` |
| | `apps/mobile/src/features/chat/tool-data/primitives/index.ts` |
| **Web Tool Card** | `apps/web/src/config/openui/primitives/ToolCard.tsx` |
| | `apps/web/src/config/openui/primitives/ToolInset.tsx` |
| **Shared Icon Config (SSOT)** | `libs/shared/ts/src/icons/tool-icon-config.ts` |
| | `libs/shared/ts/src/icons/integration-logos.ts` |
| | `libs/shared/ts/src/icons/index.ts` |
| **Web Icon Layer** | `apps/web/src/config/toolIconConfig.ts` |
| | `apps/web/src/features/chat/utils/toolIcons.tsx` |
| **Mobile Icon Layer** | `apps/mobile/src/features/chat/utils/tool-icons.tsx` |
| | `apps/mobile/src/components/icons/app-icon.tsx` |
| | `apps/mobile/src/features/integrations/constants/logos.ts` |
| **Web Date Grouping** | `apps/web/src/components/layout/sidebar/ChatsList.tsx` |
| | `apps/web/src/utils/date/timezoneUtils.ts` |
| | `apps/web/src/utils/notificationUtils.ts` |
| | `apps/web/src/features/notification/components/NotificationsList.tsx` |
| **Mobile Date Grouping** | `apps/mobile/src/features/chat/hooks/use-conversations.ts` (`groupConversationsByDate`) |
| | `apps/mobile/src/features/chat/components/sidebar/chat-history.tsx` (`Section`) |
| | `apps/mobile/src/features/notifications/components/notifications-list.tsx` (`getTimeGroup`) |
| | `apps/mobile/src/features/chat/types/index.ts` (`GroupedConversations`) |

---

## 2. Tool Card Shells — Detailed Comparison

### 2.1 Web: `ToolCard` (`apps/web/src/config/openui/primitives/ToolCard.tsx`)

```tsx
export type ToolCardSize = "compact" | "standard" | "wide" | "full";
const SIZE_MAX_W: Record<ToolCardSize, string> = {
  compact:  "max-w-md",   // 28rem — AudioPlayerView
  standard: "max-w-2xl",  // 42rem — default, MapBlockView, FileTreeView, timeline, CopyableContentView
  wide:     "max-w-4xl",  // 56rem — DocumentEditor
  full:     "",           // no constraint
};

export interface ToolCardProps {
  size?: ToolCardSize;          // default "standard"
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
  children?: React.ReactNode;
}

<div className={cn("rounded-2xl bg-zinc-800 p-4 w-full", SIZE_MAX_W[size], className)}>
  {hasHeader && <div className="mb-3"><p className="text-sm font-semibold text-zinc-100">{title}</p><p className="text-xs text-zinc-400 mt-0.5">{subtitle}</p></div>}
  <div className="flex flex-col gap-3">{children}</div>
  {footer && <div className="mt-3">{footer}</div>}
</div>
```

* **Inner primitive:** `ToolInset` (`apps/web/src/config/openui/primitives/ToolInset.tsx`) — `rounded-2xl bg-white/[0.04] overflow-hidden` (+ `p-3` unless `flush`). Comment: *“Hard rule: never bg-zinc-900. The white/4 overlay is the only inner tone.”* Allows infinite nesting without shade commitment. Used in `MapBlockView` (`<ToolInset flush>` wrapping `<Map>`) and `CopyableContentView`.
* **Layout:** `w-full` + `max-w-*` lets the LLM’s `size` hint control width while staying fluid. Parent bubble centers it.

| Variant | `max-w` | Used by (openui components) |
|---|---|---|
| `compact` | `max-w-md` (448px) | `AudioPlayerView` (audio w/ controls) |
| `standard` | `max-w-2xl` (672px) | `MapBlockView`, `FileTreeView`, `TimelineView`, `CopyableContentView` (default) |
| `wide` | `max-w-4xl` (896px) | `DocumentEditor` (rich doc w/ toolbar) |
| `full` | none | not currently instantiated via openui; available for dashboards |

All share `rounded-2xl bg-zinc-800 p-4`.

---

### 2.2 Mobile: `ToolCardShell` + companions (`apps/mobile/src/features/chat/tool-data/primitives/`)

**`tool-card-shell.tsx` — 18 lines, zero size variants:**
```tsx
export function ToolCardShell({ children, className }: ToolCardShellProps) {
  return <View className={`rounded-2xl bg-zinc-800 p-4 mx-4 my-1 ${className ?? ""}`}>{children}</View>;
}
```
* No `size` prop. Every tool result is full-bleed within the chat bubble minus `mx-4` gutters. The LLM cannot hint width; parity gap vs web’s `compact/wide/full`.
* `mx-4 my-1` is baked in (web’s outer spacing is parent-controlled).

**`tool-card-header.tsx`:**
```tsx
interface ToolCardHeaderProps { icon?: AnyIcon; iconColor?: string; title: string; subtitle?: string; count?: number; trailing?: ReactNode }
<View className="flex-row items-center gap-3 mb-3">
  {icon && <View className="w-8 h-8 rounded-full bg-zinc-800 items-center justify-center"><AppIcon icon={icon} size={16} color={iconColor} /></View>}
  <View className="flex-1"><View className="flex-row items-center gap-2"><Text className="text-zinc-100 text-base font-semibold">{title}</Text>{count !== undefined && <View className="px-2 py-0.5 rounded-full bg-zinc-800"><Text className="text-zinc-200 text-xs font-medium">{count}</Text></View>}</View>{subtitle && <Text className="text-zinc-500 text-xs mt-0.5">{subtitle}</Text>}</View>
  {trailing}
</View>
```
* Differences vs web header: fixed `text-base` (16) vs web `text-sm` (14); icon is always 32×32 circular `bg-zinc-800` wrapper; supports `count` pill + `trailing` node (web has no count/trailing in `ToolCard` itself). No `subtitle` as `ReactNode` — mobile restricts to `string`.

**`tool-card-inner.tsx`:**
```tsx
interface ToolCardInnerProps { children: ReactNode; onPress?: () => void; dense?: boolean; className?: string }
const base = `${dense ? "rounded-xl p-2.5" : "rounded-2xl p-3"} bg-zinc-900 ${className ?? ""}`;
if (onPress) return <Pressable onPress={onPress} className={base} android_ripple={{color:"rgba(255,255,255,0.05)"}}>{children}</Pressable>;
return <View className={base}>{children}</View>;
```
* Mirrors web `ToolInset` but with fixed `bg-zinc-900` (violates web’s “never zinc-900” rule). `dense` collapses to `rounded-xl p-2.5`; outermost shell is never pressable, inner slices are.

**`collapsible-card.tsx`:** expandable variant (`mx-4 my-1 rounded-2xl/3xl bg-zinc-800 px-3`) with header row (`AppIcon` + `title` (string|fn) + `trailing` + `ArrowDown02Icon` chevron rotating `0deg`→`-90deg`), `defaultOpen=true`, `titleTone` (`muted` zinc-400 vs `bright` zinc-200). No web equivalent — web uses accordion elsewhere but not for tool cards.

**`section-label.tsx`:** `text-xs font-semibold uppercase tracking-wider text-zinc-400 mb-1.5` — used inside tool cards for sub-section labels.

**`web-result-primitives.tsx`:** `FaviconImage`, `WebResultRow`, `NewsResultCard`, `getHostname` — mirrors web `WebResults`/`NewsResults` list items with `Pressable + Linking.openURL`.

*Parity note:* the *other* `ToolCard` on mobile (`apps/mobile/src/features/tools/components/ToolCard.tsx`) is **not** a chat tool-data primitive — it renders the Tools marketplace list (40×40 category-tinted bag + `Settings02Icon`, name, category badge, description). Unrelated to this audit’s chat `ToolCardShell` family.

---

### 2.3 Size-Variant Summary

| Platform | Variants | Mechanism | Gutter | Inner surface |
|---|---|---|---|---|
| **Web** | 4 (`compact`/`standard`/`wide`/`full`) | `max-w-*` + `w-full` on `ToolCard`; `size` forwarded from LLM | outer chat bubble padding | `ToolInset` `bg-white/[0.04]` (additive, nest-safe) |
| **Mobile** | **0** — fixed `mx-4` | hard-coded `rounded-2xl bg-zinc-800 p-4 mx-4 my-1` | self-contained | `ToolCardInner` `bg-zinc-900` (opaque, `dense` toggle) |

**Gap:** mobile cannot honor LLM `size` hints; `full` dashboards and `compact` audio players both render at the same constrained width. Adding `size` to `ToolCardShell` with responsive `maxWidth` (or at minimum `compact` vs `wide` split) is the parity fix.

---

## 3. Icon Rendering — `next/image` vs `expo-image`

### 3.1 Shared Source of Truth (`libs/shared/ts/src/icons/tool-icon-config.ts`)

* `ToolIconConfig { icon: string; bgColor: string; iconColor: string; bgColorRaw: string; iconColorRaw: string; isImage: boolean }`
* `icon` is either a gaia-icons component name (e.g. `CheckListIcon`) or an integration key (e.g. `gmail`).
* `isImage=true` (38 entries: gmail, notion, search, weather, github, vercel, etc.) vs `isImage=false` (30 entries: todos, reminders, dev, etc. — each with `…/20 backdrop-blur` bg).
* Helpers: `normalizeCategoryName`, `iconAliases` (`calendar→googlecalendar`, `planner→plan_tasks`, `gaia_knowledge_guide→gaia`), `getToolIconConfig` (alias → normalize → exact → fuzzy), `getCategoryInitial`, `getToolDisplayName` (`TOOL_DISPLAY_NAMES` map avoids “Googlecalendar”).
* Values are identical for bg: `bg-zinc-700` (`#3f3f46`) for most images, `bg-zinc-800` (`#27272a`) for vercel/perplexity/figma, gaia `bg-[#00bbff]/15` (`#00bbff26`); category bgs are `…500/20` with matching `iconColorRaw`.
* `integration-logos.ts` is the logo-file SSOT: `INTEGRATION_LOGO_FILES` (35 files: `gmail.webp`, `slack.svg`, …), `INTEGRATION_LOGO_EXTERNAL_URLS` (`browserbase`→google s2 favicon, `agentmail`→gstatic), `MOBILE_INTEGRATION_LOGO_CDN = "https://heygaia.io/images/icons"`, `getWebIntegrationLogoPath` (`/images/icons/…`), `getMobileIntegrationLogoUrl` (CDN absolute).

### 3.2 Web Rendering (`apps/web/src/features/chat/utils/toolIcons.tsx`)

```tsx
import Image from "next/image";
const iconComponentMap: Record<string, Component> = { CheckListIcon, Clock04Icon, …, ZapIcon }; // 32 entries

iconConfigs = Object.fromEntries(Object.entries(toolIconConfigs).map(([k, cfg]) =>
  cfg.isImage
    ? [k, { icon: isRenderableIconSrc(getIconPath(k)) ? getIconPath(k) : ToolsIcon, isImage: !!getIconPath(k), bgColor: cfg.bgColor, iconColor: cfg.iconColor }]
    : [k, { icon: iconComponentMap[cfg.icon] || ToolsIcon, isImage:false }]
));

AutoInvertIcon = ({src,size,width,height}) => {
  const dw = width||size||20, dh = height||size||20;
  const cls = "aspect-square rounded-[18%] object-contain";
  if (src.endsWith(".svg")) return <Image src={src} width={dw} height={dh} className={cls} unoptimized />;
  return <Image src={src} width={dw*3} height={dh*3} style={{width:dw,height:dh}} className={cls} />;
};

export function getToolCategoryIcon(category, {size=16,width=20,height=20,strokeWidth=0, showBackground=true, iconOnly=false, pulsating=false}, iconUrl?) {
  // normalize → alias → finalCategory → exact/fuzzy lookup → fallback to iconUrl → null
  // image: <AutoInvertIcon …> ; component: <IconComponent size width height strokeWidth className=iconColor />
  // if !showBackground or (iconOnly && isImage) return iconElement;
  // else return <div className="relative rounded-lg p-1"><div className={`absolute inset-0 rounded-lg ${bgColor} ${pulsating?'animate-pulse':''}`} /><div className="relative">{iconElement}</div></div>
  // unknown + iconUrl: grey #3f3f46 bag; unknown + no url: null
}
```
* `getIconPath` (`apps/web/src/config/toolIconConfig.ts`): `webOnlyIconUrls["gaia"]→"/brand/gaia_logo.svg"` else `getWebIntegrationLogoPath(icon)`; `getOgIconPath` maps `twitter.webp→x.svg` for Satori.
* `isRenderableIconSrc` guards `/`/`http(s)`/`data:image`/`blob:`.
* SVG: `unoptimized` (Next cannot optimize SVGs without `dangerouslyAllowSVG`); raster: rendered at 3× intrinsic size, constrained via `style`, so hi-dpi stays crisp. All carry `rounded-[18%]` (scales with size) + `object-contain`.

### 3.3 Mobile Rendering (`apps/mobile/src/features/chat/utils/tool-icons.tsx`)

```tsx
import { Image } from "expo-image";
import { getToolIconConfig } from "@gaia/shared/icons";
import { getGaiaIcon, ToolsIcon } from "@icons";
import { INTEGRATION_LOGOS } from "@/features/integrations/constants/logos";

PulsatingBackground = ({bgColorRaw, pulsating}) => {
  const opacity = useRef(new Animated.Value(1)).current;
  useEffect(()=>{ if(!pulsating) {opacity.setValue(1); return;} const anim=Animated.loop(Animated.sequence([Animated.timing(opacity,{toValue:0.4,duration:1000,useNativeDriver:true}), Animated.timing(opacity,{toValue:0.8,duration:1000,useNativeDriver:true})])); anim.start(); return ()=>anim.stop(); },[pulsating]);
  return <Animated.View style={{...absoluteFill, backgroundColor:bgColorRaw, borderRadius:8, opacity}} />;
};

export function getToolCategoryIcon(category, {size=16, showBackground=true, pulsating=false, iconUrl}, iconUrl2?) {
  const cfg = getToolIconConfig(category);
  const fallback = cfg?.isImage ? INTEGRATION_LOGOS[cfg.icon] : undefined;
  const resolved = iconUrl ?? iconUrl2 ?? fallback;
  if(!cfg){
    if(resolved) return showBackground
      ? <View style={{padding:4,position:'relative'}}><PulsatingBackground bgColorRaw="#3f3f46" pulsating={pulsating}/><View style={{position:'relative'}}><Image source={{uri:resolved}} style={{width:size,height:size}} contentFit="contain"/></View></View>
      : <Image source={{uri:resolved}} style={{width:size,height:size}} contentFit="contain"/>;
    return null;
  }
  if(cfg.isImage){
    if(resolved) return …same with bgColorRaw=cfg.bgColorRaw…;
    const FallbackIcon=ToolsIcon; return showBackground ? <View …><PulsatingBackground bgColorRaw={cfg.bgColorRaw} …/><FallbackIcon size={size} color={cfg.iconColorRaw}/></View> : <FallbackIcon …/>;
  }
  const Icon = getGaiaIcon(cfg.icon) || ToolsIcon;
  return showBackground
    ? <View style={{padding:4,position:'relative'}}><PulsatingBackground bgColorRaw={cfg.bgColorRaw} pulsating={pulsating}/><View style={{position:'relative'}}><Icon size={size} color={cfg.iconColorRaw}/></View></View>
    : <Icon size={size} color={cfg.iconColorRaw}/>;
}
```
* Integration fallback: `INTEGRATION_LOGOS` (`apps/mobile/src/features/integrations/constants/logos.ts`) built from `Object.keys(INTEGRATION_LOGO_FILES) ∪ INTEGRATION_LOGO_EXTERNAL_URLS` via `getMobileIntegrationLogoUrl` — byte-for-byte mirror of web `webIconUrls`, only CDN-hosted.
* `AppIcon` (`apps/mobile/src/components/icons/app-icon.tsx`): thin wrapper `({icon, ...props}) => <Icon {...props}/>`; re-exports `@icons`.
* Search/web primitives on mobile use **RN `Image`** (`react-native`) for `FaviconImage` (Google s2 favicon `https://www.google.com/s2/favicons?domain=${hostname}&sz=64`, `style={{width:size,height:size,borderRadius:size/2}}`, `onError→globe fallback`) and `WebResultRow`/`ImageTile`, but `expo-image` (`contentFit="contain"`, `transition`) for integration icons and twitter avatars.

### 3.4 `next/image` vs `expo-image` Matrix

| Concern | Web (`next/image`) | Mobile (`expo-image` / RN `Image`) |
|---|---|---|
| **SVG** | `unoptimized` prop, `width`/`height` required, `rounded-[18%] object-contain` class | `expo-image` handles SVG via CDN WebP/PNG/SVG; `contentFit="contain"`, no optimizer |
| **Raster** | 3× width/height intrinsic, CSS `style` constrains to `dw/dh` for hi-dpi | `contentFit="contain"`, `transition={150}` on twitter `Avatar` |
| **Sizing** | `size` defaults 16/20/20, `rounded-lg p-1` bg `8px` (`iconOnly` skips bg for images) | `size` defaults 16, `padding:4` + `borderRadius:8` bg, pulsation via `Animated.Value` loop (`0.4→0.8`, 1s each) vs web CSS `animate-pulse` |
| **Bg** | Tailwind class `bg-zinc-700`/`<color>/20` | `bgColorRaw` hex (`#3f3f46`, `rgba(16,185,129,0.2)`, …) |
| **Fallback** | `ToolsIcon` when `getIconPath` null or `!isRenderableIconSrc`; unknown+`iconUrl` → grey `bg-zinc-700` | `INTEGRATION_LOGOS[icon]` fallback when `icon_url=null` (registry tools); `ToolsIcon` when no URL; unknown+`iconUrl` → `#3f3f46` bag |
| **Favicon** | (no tool-icon favicon; separate web `WebResults` stack uses `next/image` if any) | `FaviconImage` in `web-result-primitives.tsx` uses RN `Image` with Google s2 + `Globe02Icon` fallback circle `bg-zinc-700` |
| **OG** | `getOgIconPath` WebP→SVG swap for Satori (`twitter.webp→x.svg`) | not applicable |

---

## 4. Date Grouping Logic — `getTimeFrame` / `getTimeGroup` / `groupConversationsByDate`

### 4.1 `ctx_batch_execute` equivalent — all usages found

**`grep -r "getTimeFrame\|getTimeGroup" apps --include="*.ts" --include="*.tsx" -n` (excl. node_modules/.next):**

| File | Symbol | Line | Usage |
|---|---|---|---|
| `apps/web/src/components/layout/sidebar/ChatsList.tsx:21` | `const getTimeFrame = (date: Date): string => …` | 21 | **definition** — local, `date-fns` `isToday/isYesterday/subDays` |
| `apps/web/src/components/layout/sidebar/ChatsList.tsx:92` | `const timeFrame = getTimeFrame(conversation.createdAt)` | 92 | groups `regular` conversations into `acc[timeFrame]` |
| `apps/web/src/utils/date/timezoneUtils.ts:15` | `export const getTimeGroup = (createdAt: string): "Today"\|"Yesterday"\|"Earlier"` | 15 | **definition** — TZ-aware, `toZonedTime` |
| `apps/web/src/utils/notificationUtils.ts:3` | `import { getTimeGroup } from "./date/timezoneUtils"` | 3 | import |
| `apps/web/src/utils/notificationUtils.ts:20` | `const timeGroup = getTimeGroup(notification.created_at)` | 20 | `groupNotificationsByTimezone` reducer |
| `apps/mobile/src/features/notifications/components/notifications-list.tsx:57` | `function getTimeGroup(dateString: string): TimeGroupKey` | 57 | **definition** — local, date-truncation, 4-bucket |
| `apps/mobile/src/features/notifications/components/notifications-list.tsx:182` | `groups[getTimeGroup(n.created_at)].push(n)` | 182 | bucketing in `useMemo` |

**Related grouping (no `getTime*` name, but same concern):**

| File | Symbol | Notes |
|---|---|---|
| `apps/mobile/src/features/chat/hooks/use-conversations.ts:70` | `export function groupConversationsByDate(conversations: Conversation[]): GroupedConversations` | mobile chat history grouping (6-bucket + starred isolation) |
| `apps/mobile/src/features/chat/components/sidebar/chat-history.tsx: …` | `groupedChats = groupConversationsByDate(filteredConversations)` | consumed to render 6 `<Section>`s |
| `apps/web/src/features/notification/components/NotificationsList.tsx: …` | `groupedNotifications = useMemo(()=>groupNotificationsByTimezone(notifications),[notifications])` | consumed to render `space-y-8` groups |

---

### 4.2 Web — Conversation Groups (`ChatsList.tsx`)

```ts
// apps/web/src/components/layout/sidebar/ChatsList.tsx:21
const getTimeFrame = (date: Date): string => {
  if (isToday(date)) return "Today";
  if (isYesterday(date)) return "Yesterday";
  const daysAgo7 = subDays(new Date(), 7);
  const daysAgo30 = subDays(new Date(), 30);
  if (date >= daysAgo7) return "Previous 7 days";
  if (date >= daysAgo30) return "Previous 30 days";
  return "All time";
};
const timeFramePriority = (tf: string): number =>
  ({ Today:0, Yesterday:1, "Previous 7 days":2, "Previous 30 days":3, "All time":4 }[tf] ?? 5);
```

* Library: `date-fns` `isToday/isYesterday/subDays` — all compare against local `Date` (no explicit TZ lib).
* Buckets: **5** (`Today`, `Yesterday`, `Previous 7 days`, `Previous 30 days`, `All time`).
* Additional buckets rendered separately: `systemConversations` (`isSystemGenerated`) → “Created by GAIA”, `starredConversations` (`starred`) → “Starred Chats”. Regular conversations are grouped by `getTimeFrame(createdAt)`; within each group sorted `b.createdAt - a.createdAt` (desc).
* Ordering by `timeFramePriority`, rendered as `<AccordionItem value={timeFrame.toLowerCase().replace(/\s+/g,"-")}>`.
* `isLoading = conversations.length===0 && !initialSyncCompleted`; all sections default-expanded via controlled `openAccordions` state (all time frames + system/starred if non-empty). Infinite scroll via scroll listener (`distanceFromBottom<100` → `loadMoreConversations()`).
* Grouping step:
  ```ts
  const grouped = regular.reduce((acc, c) => {
    const tf = getTimeFrame(c.createdAt);
    (acc[tf] ??= []).push(c);
    return acc;
  }, {} as Record<string,IConversation[]>);
  const sorted = Object.entries(grouped).toSorted(([a],[b]) => timeFramePriority(a)-timeFramePriority(b));
  ```

### 4.3 Web — Notification Groups (`timezoneUtils.ts` + `notificationUtils.ts`)

```ts
// apps/web/src/utils/date/timezoneUtils.ts:15
export const getTimeGroup = (createdAt: string): "Today" | "Yesterday" | "Earlier" => {
  const userTimeZone = getBrowserTimezone();
  const utcTimestamp = createdAt.endsWith("Z") ? createdAt : `${createdAt}Z`;
  const utcCreated = new Date(utcTimestamp);
  const now = new Date();
  const zonedCreated = toZonedTime(utcCreated, userTimeZone);
  const zonedNow = toZonedTime(now, userTimeZone);
  const diffInHours = (zonedNow.getTime() - zonedCreated.getTime()) / (1000*60*60);
  if (diffInHours < 24) return "Today";
  if (diffInHours < 48) return "Yesterday";
  return "Earlier";
};
// apps/web/src/utils/notificationUtils.ts:20
export const groupNotificationsByTimezone = (notifications: NotificationRecord[]): Record<string,NotificationRecord[]> =>
  notifications.reduce((groups, n) => {
    const tg = getTimeGroup(n.created_at);
    (groups[tg] ??= []).push(n);
    return groups;
  }, {} as Record<string,NotificationRecord[]>);
// apps/web/src/features/notification/components/NotificationsList.tsx
const groupedNotifications = useMemo(() => groupNotificationsByTimezone(notifications), [notifications]);
// renders: <div className="space-y-8 px-6 py-6">{Object.entries(groupedNotifications).map(([tg, list]) => <div key={tg} className="space-y-3"><h3 className="px-0.5 text-xs font-semibold tracking-wider text-zinc-500 uppercase">{tg}</h3><div className="space-y-2.5">{list.map(n => <EnhancedNotificationCard …/>)}</div></div>)}</div>
```

* **3 buckets only:** `Today` / `Yesterday` / `Earlier` — coarser than chat history.
* **TZ-aware:** `date-fns-tz` `toZonedTime` + `getBrowserTimezone()`. Handles the `created_at` without trailing `Z` (API returns `2025-01-01T20:00:00.000000`) by forcing `Z`. Diff is hour-based from midnight-agnostic zoned timestamps — not calendar-day truncation.
* No `SPARSE_LIST_THRESHOLD`, no `This Week` bucket.

### 4.4 Mobile — Conversation Groups (`use-conversations.ts` + `chat-history.tsx`)

```ts
// apps/mobile/src/features/chat/hooks/use-conversations.ts:70
export function groupConversationsByDate(conversations: Conversation[]): GroupedConversations {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()); // midnight local
  const yesterday = new Date(today); yesterday.setDate(yesterday.getDate()-1);
  const lastWeek = new Date(today); lastWeek.setDate(lastWeek.getDate()-7);
  const last30Days = new Date(today); last30Days.setDate(last30Days.getDate()-30);

  const starred: Conversation[] = [];
  const todayChats: Conversation[] = [];
  const yesterdayChats: Conversation[] = [];
  const lastWeekChats: Conversation[] = [];
  const last30DaysChats: Conversation[] = [];
  const olderChats: Conversation[] = [];

  conversations.forEach((conv) => {
    const convDate = new Date(conv.created_at);
    if (conv.is_starred) starred.push(conv);
    else if (convDate >= today) todayChats.push(conv);
    else if (convDate >= yesterday) yesterdayChats.push(conv);
    else if (convDate >= lastWeek) lastWeekChats.push(conv);
    else if (convDate >= last30Days) last30DaysChats.push(conv);
    else olderChats.push(conv);
  });
  return { starred, today, yesterday, lastWeek, last30Days, older };
}
// apps/mobile/src/features/chat/types/index.ts
export interface GroupedConversations { starred: Conversation[]; today: Conversation[]; yesterday: Conversation[]; lastWeek: Conversation[]; last30Days: Conversation[]; older: Conversation[]; }
```

* Buckets: **6** (`Starred`, `Today`, `Yesterday`, `Previous 7 days`/`lastWeek`, `Previous 30 days`/`last30Days`, `Older`) — note web’s “All time” ↔ mobile’s “Older”.
* `Starred` is **exclusive**: if `is_starred`, conversation never appears in date buckets (web also separates starred, but web’s `starred` is derived from `regular` filtered; behavior equivalent).
* Date truncation: manual `new Date(y,m,d)` midnight local — no `date-fns`, no `toZonedTime`.
* Rendering (`apps/mobile/src/features/chat/components/sidebar/chat-history.tsx`): 6 `<Section>`s in fixed order (Starred→Today→Yesterday→Previous 7 days→Previous 30 days→Older), each with chevron `Animated` `rotate` (`0↔-90deg`, `withTiming 200ms`), `isExpanded` map default all `true` (controlled via `PressableFeedback`). Search mode bypasses grouping: flat `FlatList` with `HighlightedText` (search query highlighted `color #00bbff weight 600`) + result count header. Empty: `#71717a` icon + “No conversations yet / Start a new chat”.

### 4.5 Mobile — Notification Groups (`notifications-list.tsx`)

```ts
// apps/mobile/src/features/notifications/components/notifications-list.tsx:39
type TimeGroupKey = "today" | "yesterday" | "thisWeek" | "earlier";
const TIME_GROUP_LABELS: Record<TimeGroupKey,string> = { today:"Today", yesterday:"Yesterday", thisWeek:"This Week", earlier:"Earlier" };
const TIME_GROUP_ORDER: TimeGroupKey[] = ["today","yesterday","thisWeek","earlier"];
const SPARSE_LIST_THRESHOLD = 10;

function getTimeGroup(dateString: string): TimeGroupKey {
  const date = new Date(dateString);
  if (Number.isNaN(date.getTime())) return "earlier";
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today); yesterday.setDate(yesterday.getDate()-1);
  const sevenDaysAgo = new Date(today); sevenDaysAgo.setDate(sevenDaysAgo.getDate()-7);
  const notifDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  if (notifDate.getTime() >= today.getTime()) return "today";
  if (notifDate.getTime() >= yesterday.getTime()) return "yesterday";
  if (notifDate.getTime() >= sevenDaysAgo.getTime()) return "thisWeek";
  return "earlier";
}

const sections = useMemo(() => {
  const groups: Record<TimeGroupKey,InAppNotification[]> = { today:[], yesterday:[], thisWeek:[], earlier:[] };
  for (const n of notifications) groups[getTimeGroup(n.created_at)].push(n);
  const isSparse = notifications.length < SPARSE_LIST_THRESHOLD;
  const result: GroupedSection[] = [];
  for (const key of TIME_GROUP_ORDER) {
    const bucket = groups[key];
    if (bucket.length===0) continue;
    const skipHeader = key==="earlier" && isSparse;
    if (!skipHeader) result.push({ type:"header", title: TIME_GROUP_LABELS[key] });
    for (const n of bucket) result.push({ type:"notification", notification:n });
  }
  return result;
}, [notifications]);
// FlatList: header → <Text style={{fontSize:12,fontWeight:'600',letterSpacing:1,textTransform:'uppercase',color:'#71717a',marginTop:index===0?8:32,marginBottom:12,paddingHorizontal:2}}>{title}</Text>
// notification → <View style={{marginBottom:10}}><NotificationCard …/></View>
// contentContainerStyle={{paddingHorizontal:16,paddingTop:12,paddingBottom:insets.bottom+24}}
```

* Buckets: **4** (`Today`, `Yesterday`, `This Week`, `Earlier`) vs web’s 3 (`Today`, `Yesterday`, `Earlier`).
* Date truncation: calendar-day comparison (`notifDate` midnight), not hour diff. Invalid dates → `earlier`.
* `SPARSE_LIST_THRESHOLD=10`: when `notifications.length<10`, the “Earlier” header is **suppressed** (cards still render, just without ceremony) — web never suppresses.
* `TIME_GROUP_ORDER` guarantees stable key order (web’s `Object.entries(grouped)` has no guaranteed priority beyond insertion; it relies on `groupNotificationsByTimezone` reduce order, which can be non-chronological if input isn’t sorted).

### 4.6 Date-Grouping Divergence Table

| Axis | Web Conversations (`getTimeFrame`) | Mobile Conversations (`groupConversationsByDate`) | Web Notifications (`getTimeGroup`) | Mobile Notifications (`getTimeGroup`) |
|---|---|---|---|---|
| **Buckets** | 5: Today / Yesterday / Prev7 / Prev30 / All time | 6: Starred + same 5 (Older instead of All time) | 3: Today / Yesterday / Earlier | 4: Today / Yesterday / This Week / Earlier |
| **Lib** | `date-fns` `isToday/isYesterday/subDays` | manual `Date(y,m,d)` midnight | `date-fns-tz` `toZonedTime` + `getBrowserTimezone` | manual `Date(y,m,d)` midnight |
| **Metric** | calendar-day (`isToday`) / `>= subDays` | `convDate >= todayMidnight` etc. | `diffInHours <24 / <48` on zoned times | `notifDate >= todayMidnight` etc. |
| **TZ** | local `Date` (implicit) | local `Date` (implicit) | **explicit** user TZ (zoned) | local `Date` (implicit) |
| **Invalid input** | N/A (`Date` object already) | N/A (conversations always have `created_at`) | `new Date(…Z)` → `Invalid Date` still zoned; no guard | `return "earlier"` |
| **Sparse handling** | none | none | none | suppress “Earlier” header if total <10 |
| **Order guarantee** | `timeFramePriority` sort | fixed `starred→today→yesterday→lastWeek→last30Days→older` | insertion order (input-dependent) | `TIME_GROUP_ORDER` |
| **Header source** | `ChatsList` accordion `timeFrame` string | `GroupChatHistory` `Section` titles | `NotificationsList` `timeGroup` string | `TIME_GROUP_LABELS` + `GroupedSection` |

**Parity gaps:**
1. Mobile notifications’ `This Week` bucket has no web counterpart — a notification 3 days old is “Earlier” on web, “This Week” on mobile.
2. Web notifications’ TZ-aware `diffInHours` vs mobile’s midnight truncation: same UTC timestamp near midnight can classify differently (e.g., IST user 00:30 → web Today, mobile Yesterday if local midnight hasn’t been crossed in the truncation logic’s UTC-parsed `Date`).
3. Mobile chat history’s “Older” vs web’s “All time” — label mismatch; tooling/search must alias.
4. Web notification grouping has no sparse suppression — short lists show an “Earlier” header atop 1–2 cards; mobile intentionally hides it.

---

## 5. Group Headers — Styling & Interaction

### 5.1 Web — Chat List

* Container: `<Accordion type="multiple" value={openAccordions} onValueChange={setOpenAccordions}>` — all frames default-open.
* Styles (`apps/web/src/components/layout/sidebar/constants.ts`):
  ```ts
  export const accordionItemStyles = {
    item: "my-1 flex min-h-fit w-full flex-col items-start justify-start overflow-hidden border-none py-1",
    trigger: "w-full px-2 pt-0 pb-1 text-xs text-zinc-600 font-normal hover:no-underline hover:text-zinc-600",
    content: "w-full p-0!",
    chatContainer: "flex w-full flex-col gap-1",
  };
  ```
  Trigger text: `text-xs` (12) `text-zinc-600` `font-normal` (vs notifications headers `text-zinc-500 font-semibold uppercase`). Uses `AccordionTrigger` chevron (shadcn/ui).
* Item: `<ChatTab>` with left accent `w-3 bg-[#00bbff]` when active, `FavouriteIcon` amber when starred, `isUnread` dot `w-2 h-2 bg-[#00bbff]`, streaming dot via `useIsConversationStreaming`.
* System/Starred sections render above dated ones; dated sections loop `sortedTimeFrames`.

### 5.2 Web — Notifications

* No accordion — flat `space-y-8` groups, each `space-y-3` header `className="px-0.5 text-xs font-semibold tracking-wider text-zinc-500 uppercase"` with `space-y-2.5` card stack. Empty: `h-16 w-16 rounded-full bg-zinc-900/50 ring-1 ring-zinc-800` + `NotificationIcon` `text-3xl text-zinc-600` + `text-base font-semibold text-white` title + `text-sm text-zinc-500` desc.

### 5.3 Mobile — Chat History

* `Section` component (`apps/mobile/src/features/chat/components/sidebar/chat-history.tsx`):
  ```tsx
  <PressableFeedback onPress={handleToggle} hitSlop={4} style={{flexDirection:'row',alignItems:'center',paddingHorizontal:spacing.sm+4,paddingTop:8,paddingBottom:4}}>
    <Text style={{flex:1,fontSize:fontSize.md,color:'#71717a',fontWeight:'400'}}>{title}</Text>
    <Reanimated.View style={chevronStyle}><AppIcon icon={ArrowDown01Icon} size={iconSize.sm} color="#71717a"/></Reanimated.View>
  </PressableFeedback>
  {isExpanded && items.map(item => <ChatItem …/>)}
  ```
  * Trigger larger (`fontSize.md` ≈14) `color #71717a weight 400` vs web `text-xs zinc-600`. No `uppercase`/`tracking-wider`.
  * Chevron `Animated` rotation `0↔-90deg` `withTiming(200ms)`.
  * `ChatItem`: `mx-12 p12 vertical spacing.sm+2 gap spacing.sm`, active `bg rgba(0,187,255,0.10) + left 3px #00bbff strip`, unread `w8h8 #00bbff` dot, `StreamingDot` pulsing `Animated` opacity `0.4→1`, scale `1→1.3`.
  * Headers: exact titles `Starred | Today | Yesterday | Previous 7 days | Previous 30 days | Older` (web uses `All time` not `Older`; web also has `Starred Chats` not `Starred`, `Created by GAIA` not present on mobile).

### 5.4 Mobile — Notifications

* `FlatList` `contentContainerStyle={{paddingHorizontal:16,paddingTop:12,paddingBottom:insets.bottom+24}}`.
* Group header `Text style={{fontSize:12,fontWeight:'600',letterSpacing:1,textTransform:'uppercase',color:'#71717a',marginTop:index===0?8:32,marginBottom:12,paddingHorizontal:2}}`.
* Matches web `text-xs font-semibold tracking-wider uppercase zinc-500` but with explicit `32px` inter-group gap (`space-y-8`) and `12px` intra-header-to-card.
* Notification card gap: `marginBottom:10` (`space-y-2.5` on web). Skeleton: `SkeletonItem` `bg #171920 p spacing.md gap spacing.sm` with shimmer `rgba(255,255,255,0.06/0.07/0.04)`.

---

## 6. Other Notable Findings

* **Shared icon config is complete.** No variant needed for `getTime*` — the shared layer holds no date logic; divergence is intentional per surface but undocumented.
* **Tool detail parity:** `apps/mobile/src/features/chat/tool-data/cards/*` consumes `ToolCardShell/Header/Inner` consistently; web openui surfaces use `ToolCard/ToolInset`. No `size` plumbing on mobile.
* **Image rendering path split:** `FaviconImage` (RN `Image` + Google S2) vs integration icons (`expo-image` + CDN) — mobile mixes two image stacks; web centralizes on `next/image`.
* **Work wiring:** `apps/mobile/src/features/workflows/components/trigger-picker-sheet.tsx:81` uses `getMobileIntegrationLogoUrl`, confirming the CDN path is live for non-chat surfaces too.

---

## 7. Recommendation Checklist (Foundation phase)

- [ ] Add `size?: ToolCardSize` to `ToolCardShell` (map to container `maxWidth` or conditional `mx`/`max-w`); align inner `ToolCardInner` `dense` semantics with web `ToolInset flush`.
- [ ] Unify notification buckets: adopt `Today/Yesterday/This Week/Earlier` on web or collapse mobile `This Week` into `Earlier`; add `SPARSE_LIST_THRESHOLD` equivalence.
- [ ] Normalize group titles: `All time` ↔ `Older`, `Starred Chats` ↔ `Starred`.
- [ ] Make mobile chat grouping TZ-aware or document local-midnight intent; add `getTimeGroup` to shared `libs/shared/ts` instead of duplicating per app.
- [ ] Ensure `TIME_GROUP_ORDER` / `timeFramePriority` are shared constants; sort web notification groups by priority rather than insertion order.
- [ ] Consolidate header tokens: single `SectionLabel` / Tailwind set (`text-xs font-semibold uppercase tracking-wider text-zinc-500`) used by both chat list and notifications on both platforms.

---

*Generated for Foundation & Discovery agent 3 — all file reads verified this turn; no `gh pr checks` / test suite run (discovery-only phase; marked UNVERIFIED for CI lanes).*
