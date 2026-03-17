# Video2: GAIA for Founders Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `apps/video2` — a 75-second Remotion motion design video for founders, showing GAIA proactively handling a VC reply overnight: researching the VC, updating a pitch deck, cleaning the data room, creating a prep doc, notifying the co-founder, sorting the calendar, and drafting the reply — all without being asked.

**Architecture:** New Nx app at `apps/video2/` mirroring `apps/video/` structure. Public assets symlinked from `apps/video/public`. One main composition `GaiaFounders.tsx` using `TransitionSeries`. Each scene is a self-contained TSX file. New reusable UI card components live in `src/components/`.

**Tech Stack:** Remotion 4.0.429, React 19, TypeScript, @remotion/transitions, @remotion/fonts, @remotion/google-fonts

---

## Video Script Summary

| Scene | Duration | Description |
|-------|----------|-------------|
| S01_Notification | 180f (6s) | WhatsApp notification from GAIA slides in |
| S02_TheReply | 240f (8s) | Chat thread — GAIA message + email thread card shows VC reply |
| S03_Research | 240f (8s) | VC profile card builds — recent deals, thesis, overlaps |
| S04_DeckUpdated | 240f (8s) | Slides fan out, live metrics swap in, narrative tailored to VC |
| S05_DataRoom | 180f (6s) | Spreadsheet fills itself — MRR, growth, runway |
| S06_PrepDoc | 210f (7s) | Google Doc assembles — 5 questions + talking points type in |
| S07_SlackNotify | 120f (4s) | Slack card slides in — co-founder notified |
| S08_CalendarSlots | 180f (6s) | Calendar shows 3 open slots + 30min prep block inserted before each |
| S09_ReplyDrafted | 150f (5s) | Email compose fills — body, time slots, attachments, CRM flips |
| S10_TheBeat | 240f (8s) | Full chat thread, all checkmarks, GAIA asks, user says "Send it." |
| S11_Close | 360f (12s) | Typography payoff + logo + CTA |

**Transitions (10 total):**
- S01→S02: fade, 8f
- S02→S03: slide from-right, 12f
- S03→S04: slide from-right, 12f
- S04→S05: slide from-right, 12f
- S05→S06: slide from-right, 12f
- S06→S07: slide from-right, 12f
- S07→S08: slide from-right, 12f
- S08→S09: slide from-right, 12f
- S09→S10: fade, 8f
- S10→S11: slide from-right, 12f

**Total durationInFrames = (180+240+240+240+180+210+120+180+150+240+360) - (8+12+12+12+12+12+12+12+8+12) = 2340 - 112 = 2228 frames ≈ 74s**

---

## File Structure

```
apps/video2/
├── package.json
├── project.json
├── remotion.config.ts
├── tsconfig.json
├── public -> ../video/public  (symlink — shared fonts, icons, sounds)
└── src/
    ├── index.ts
    ├── Root.tsx
    ├── GaiaFounders.tsx          # Main TransitionSeries composition
    ├── constants.ts              # Copy of video1 constants (identical)
    ├── sfx.ts                    # Copy of video1 sfx (identical)
    ├── fonts.ts                  # Copy of video1 fonts (identical)
    ├── components/
    │   ├── TypingText.tsx        # Copy from video1 (identical)
    │   ├── ChatThread.tsx        # NEW: WhatsApp-style chat thread spine
    │   ├── ChatBubble.tsx        # NEW: Individual GAIA message bubble with timestamp + checkmark
    │   ├── EmailThreadCard.tsx   # NEW: Shows email thread (original + reply)
    │   ├── ResearchCard.tsx      # NEW: VC profile/research card
    │   ├── DeckSlidesCard.tsx    # NEW: Presentation slides fanning out
    │   ├── SpreadsheetCard.tsx   # NEW: Spreadsheet with cells filling in
    │   ├── PrepDocCard.tsx       # NEW: Google Doc with questions typing in
    │   ├── SlackMessageCard.tsx  # NEW: Slack message card
    │   ├── CalendarSlotsCard.tsx # NEW: Calendar with slots + prep blocks
    │   └── EmailComposeCard.tsx  # NEW: Email compose with body typing, attachments, CRM status
    └── scenes/
        ├── S01_Notification.tsx
        ├── S02_TheReply.tsx
        ├── S03_Research.tsx
        ├── S04_DeckUpdated.tsx
        ├── S05_DataRoom.tsx
        ├── S06_PrepDoc.tsx
        ├── S07_SlackNotify.tsx
        ├── S08_CalendarSlots.tsx
        ├── S09_ReplyDrafted.tsx
        ├── S10_TheBeat.tsx
        └── S11_Close.tsx
```

---

## Task 1: Bootstrap app/video2 structure

**Files:**
- Create: `apps/video2/package.json`
- Create: `apps/video2/project.json`
- Create: `apps/video2/remotion.config.ts`
- Create: `apps/video2/tsconfig.json`
- Create: `apps/video2/src/index.ts`

- [ ] **Step 1: Create package.json**

```json
{
  "name": "@gaia/video2",
  "version": "0.0.1",
  "scripts": {
    "start": "remotion studio src/index.ts",
    "build": "remotion bundle src/index.ts",
    "render": "remotion render src/index.ts GaiaFounders out/founders.mp4"
  },
  "dependencies": {
    "@remotion/cli": "4.0.429",
    "@remotion/fonts": "4.0.429",
    "@remotion/google-fonts": "4.0.429",
    "@remotion/transitions": "4.0.429",
    "@theexperiencecompany/gaia-icons": "^1.9.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "remotion": "4.0.429",
    "zod": "4.3.6"
  },
  "devDependencies": {
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "typescript": "^5.0.0"
  }
}
```

- [ ] **Step 2: Create project.json**

```json
{
  "name": "video2",
  "$schema": "../../node_modules/nx/schemas/project-schema.json",
  "projectType": "application",
  "sourceRoot": "apps/video2/src",
  "targets": {
    "start": {
      "command": "remotion studio src/index.ts",
      "options": { "cwd": "apps/video2" }
    },
    "render": {
      "command": "remotion render src/index.ts GaiaFounders out/founders.mp4",
      "options": { "cwd": "apps/video2" }
    },
    "build": {
      "command": "remotion bundle src/index.ts",
      "options": { "cwd": "apps/video2" }
    }
  }
}
```

- [ ] **Step 3: Create remotion.config.ts**

```ts
import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
```

- [ ] **Step 4: Create tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "lib": ["ES2020", "DOM"],
    "jsx": "react-jsx",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "strict": true,
    "skipLibCheck": true
  },
  "include": ["src"]
}
```

- [ ] **Step 5: Create src/index.ts**

```ts
import { registerRoot } from "remotion";
import { RemotionRoot } from "./Root";

registerRoot(RemotionRoot);
```

- [ ] **Step 6: Symlink public assets**

```bash
cd apps/video2 && ln -sf ../video/public public
```

Verify: `ls apps/video2/public` should show fonts/, images/, sounds/

- [ ] **Step 7: Install dependencies**

```bash
cd apps/video2 && pnpm install
```

---

## Task 2: Foundation files (constants, sfx, fonts)

**Files:**
- Create: `apps/video2/src/constants.ts`
- Create: `apps/video2/src/sfx.ts`
- Create: `apps/video2/src/fonts.ts`

- [ ] **Step 1: Create constants.ts** (identical to video1)

```ts
export const WIDTH = 1920;
export const HEIGHT = 1080;
export const FPS = 30;

export const COLORS = {
  bg: "#111111",
  bgLight: "#111111",
  secondaryBg: "#1a1a1a",
  surface: "#27272a",
  primary: "#00bbff",
  white: "#ffffff",
  textDark: "#ffffff",
  zinc400: "#a1a1aa",
  zinc500: "#71717a",
  zinc600: "#a1a1aa",
  zinc700: "#3f3f46",
  zinc800: "#27272a",
  zinc900: "#18181b",
} as const;

export const FONTS = {
  display: '"Aeonik", "Helvetica Neue", Helvetica, sans-serif',
  body: '"Inter", system-ui, sans-serif',
  mono: '"Anonymous Pro", "Cascadia Code", monospace',
} as const;

export const TRANSITIONS = {
  fast: 8,
  normal: 12,
  slow: 15,
  reveal: 20,
} as const;

export const SPRINGS = {
  smooth: { damping: 200 },
  snappy: { damping: 20, stiffness: 200 },
  natural: { damping: 18, stiffness: 120 },
  bouncy: { damping: 8, stiffness: 180 },
  cinematic: { damping: 22, stiffness: 80 },
} as const;
```

- [ ] **Step 2: Create sfx.ts** (identical to video1)

```ts
export const SFX = {
  whoosh: "https://remotion.media/whoosh.wav",
  whip: "https://remotion.media/whip.wav",
  pageTurn: "https://remotion.media/page-turn.wav",
  uiSwitch: "https://remotion.media/switch.wav",
  mouseClick: "https://remotion.media/mouse-click.wav",
} as const;
```

- [ ] **Step 3: Create fonts.ts** (identical to video1 — uses same symlinked public/)

```ts
import { loadFont } from "@remotion/fonts";
import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { continueRender, delayRender, staticFile } from "remotion";

const { fontFamily: interFamily } = loadInter("normal", {
  weights: ["400", "500", "600", "700"],
  subsets: ["latin"],
});

export const FONT_FAMILIES = {
  inter: interFamily,
  display: '"Aeonik", "Helvetica Neue", Helvetica, sans-serif',
  mono: '"Anonymous Pro", "Cascadia Code", monospace',
};

const waitForFonts = delayRender("Loading local fonts");

Promise.all([
  loadFont({
    family: "Aeonik",
    url: staticFile("fonts/AeonikExtendedProTRIAL-Bold.otf"),
    weight: "700",
  }),
  loadFont({
    family: "Aeonik",
    url: staticFile("fonts/AeonikExtendedProTRIAL-Black.otf"),
    weight: "900",
  }),
  loadFont({
    family: "Aeonik",
    url: staticFile("fonts/AeonikExtendedProTRIAL-Air.otf"),
    weight: "400",
  }),
  loadFont({
    family: "Anonymous Pro",
    url: staticFile("fonts/AnonymousPro-Regular.woff2"),
    weight: "400",
  }),
])
  .then(() => continueRender(waitForFonts))
  .catch((err) => {
    console.error("Font loading failed:", err);
    continueRender(waitForFonts);
  });
```

- [ ] **Step 4: Commit**

```bash
git add apps/video2/
git commit -m "feat(video2): bootstrap app structure with constants, sfx, fonts"
```

---

## Task 3: Shared components

**Files:**
- Create: `apps/video2/src/components/TypingText.tsx`
- Create: `apps/video2/src/components/ChatBubble.tsx`
- Create: `apps/video2/src/components/ChatThread.tsx`

- [ ] **Step 1: Create TypingText.tsx** (copy from video1)

```tsx
import React from "react";
import { useCurrentFrame } from "remotion";
import { COLORS } from "../constants";

interface TypingTextProps {
  text: string;
  framesPerChar?: number;
  delay?: number;
  cursorColor?: string;
  showCursor?: boolean;
  style?: React.CSSProperties;
}

export const TypingText: React.FC<TypingTextProps> = ({
  text,
  framesPerChar = 1,
  delay = 0,
  cursorColor = COLORS.primary,
  showCursor = true,
  style,
}) => {
  const frame = useCurrentFrame();
  const charIndex = Math.min(
    Math.floor(Math.max(0, frame - delay) / framesPerChar),
    text.length,
  );
  const displayText = text.slice(0, charIndex);
  const hasCursor = showCursor && frame >= delay;
  const cursorOpacity =
    hasCursor ? (Math.floor((frame - delay) / 15) % 2 === 0 ? 1 : 0) : 0;

  return (
    <span style={style}>
      {displayText}
      <span
        style={{
          display: "inline-block",
          width: 2,
          height: "1.1em",
          backgroundColor: cursorColor,
          marginLeft: 2,
          verticalAlign: "text-bottom",
          opacity: cursorOpacity,
        }}
      />
    </span>
  );
};
```

- [ ] **Step 2: Create ChatBubble.tsx**

A single GAIA message bubble with timestamp, message text, and optional checkmark.

```tsx
import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONTS } from "../constants";

interface ChatBubbleProps {
  message: string;
  timestamp: string;
  delay?: number;          // frame to start entrance animation
  showCheckmark?: boolean; // show green checkmark (task done)
  checkmarkDelay?: number; // frame to show checkmark
}

export const ChatBubble: React.FC<ChatBubbleProps> = ({
  message,
  timestamp,
  delay = 0,
  showCheckmark = false,
  checkmarkDelay = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const enterP = spring({
    frame: frame - delay,
    fps,
    config: { damping: 200 },
  });
  const opacity = interpolate(enterP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const y = interpolate(enterP, [0, 1], [20, 0]);

  const checkP = spring({
    frame: frame - checkmarkDelay,
    fps,
    config: { damping: 200 },
  });
  const checkOpacity = showCheckmark
    ? interpolate(checkP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" })
    : 0;

  return (
    <div
      style={{
        transform: `translateY(${y}px)`,
        opacity,
        display: "flex",
        alignItems: "flex-end",
        gap: 12,
        marginBottom: 18,
      }}
    >
      {/* GAIA avatar dot */}
      <div
        style={{
          width: 36,
          height: 36,
          borderRadius: "50%",
          background: COLORS.primary,
          flexShrink: 0,
          marginBottom: 4,
        }}
      />

      <div style={{ flex: 1 }}>
        {/* Timestamp */}
        <div
          style={{
            fontFamily: FONTS.body,
            fontSize: 20,
            color: COLORS.zinc500,
            marginBottom: 6,
            fontWeight: 400,
          }}
        >
          {timestamp}
        </div>

        {/* Bubble */}
        <div
          style={{
            background: COLORS.surface,
            borderRadius: "40px 40px 40px 8px",
            padding: "22px 30px",
            fontFamily: FONTS.body,
            fontSize: 28,
            fontWeight: 500,
            color: COLORS.textDark,
            lineHeight: 1.45,
            maxWidth: 700,
            display: "inline-block",
          }}
        >
          {message}
        </div>
      </div>

      {/* Checkmark */}
      <div
        style={{
          opacity: checkOpacity,
          width: 36,
          height: 36,
          borderRadius: "50%",
          background: "#22c55e",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
          marginBottom: 4,
        }}
      >
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
          <path
            d="M3 9l4 4 8-8"
            stroke="white"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </div>
    </div>
  );
};
```

- [ ] **Step 3: Create ChatThread.tsx**

The WhatsApp/Telegram-style chat spine. Accepts an array of messages to render as a scrollable thread. Used in S02 and S10.

```tsx
import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONTS } from "../constants";
import { ChatBubble } from "./ChatBubble";

export interface ThreadMessage {
  message: string;
  timestamp: string;
  delay: number;
  showCheckmark?: boolean;
  checkmarkDelay?: number;
}

interface ChatThreadProps {
  messages: ThreadMessage[];
  appName?: string; // "WhatsApp" | "Telegram"
  contactName?: string;
  enterDelay?: number;
}

export const ChatThread: React.FC<ChatThreadProps> = ({
  messages,
  appName = "Telegram",
  contactName = "GAIA",
  enterDelay = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const enterP = spring({
    frame: frame - enterDelay,
    fps,
    config: { damping: 200 },
  });
  const opacity = interpolate(enterP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        opacity,
        width: 900,
        background: COLORS.bg,
        borderRadius: 40,
        overflow: "hidden",
        border: `1px solid ${COLORS.zinc700}`,
      }}
    >
      {/* Header */}
      <div
        style={{
          background: COLORS.surface,
          padding: "24px 36px",
          display: "flex",
          alignItems: "center",
          gap: 18,
          borderBottom: `1px solid ${COLORS.zinc700}`,
        }}
      >
        <div
          style={{
            width: 52,
            height: 52,
            borderRadius: "50%",
            background: COLORS.primary,
          }}
        />
        <div>
          <div
            style={{
              fontFamily: FONTS.body,
              fontWeight: 700,
              fontSize: 28,
              color: COLORS.textDark,
            }}
          >
            {contactName}
          </div>
          <div
            style={{
              fontFamily: FONTS.body,
              fontSize: 20,
              color: COLORS.zinc500,
            }}
          >
            {appName}
          </div>
        </div>
      </div>

      {/* Messages */}
      <div style={{ padding: "30px 36px 20px" }}>
        {messages.map((msg, i) => (
          <ChatBubble
            key={i}
            message={msg.message}
            timestamp={msg.timestamp}
            delay={msg.delay}
            showCheckmark={msg.showCheckmark}
            checkmarkDelay={msg.checkmarkDelay}
          />
        ))}
      </div>
    </div>
  );
};
```

- [ ] **Step 4: Commit**

```bash
git add apps/video2/src/components/
git commit -m "feat(video2): add shared components — TypingText, ChatBubble, ChatThread"
```

---

## Task 4: UI card components

**Files:**
- Create: `apps/video2/src/components/EmailThreadCard.tsx`
- Create: `apps/video2/src/components/ResearchCard.tsx`
- Create: `apps/video2/src/components/DeckSlidesCard.tsx`
- Create: `apps/video2/src/components/SpreadsheetCard.tsx`
- Create: `apps/video2/src/components/PrepDocCard.tsx`
- Create: `apps/video2/src/components/SlackMessageCard.tsx`
- Create: `apps/video2/src/components/CalendarSlotsCard.tsx`
- Create: `apps/video2/src/components/EmailComposeCard.tsx`

### EmailThreadCard.tsx

Shows the VC's reply email and the founder's original email below it. The reply highlights as "new" with a cyan left border.

- [ ] **Step 1: Create EmailThreadCard.tsx**

```tsx
import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONTS } from "../constants";

interface EmailThreadCardProps {
  replyFrom: string;
  replySubject: string;
  replyPreview: string;
  replyTime: string;
  originalSubject: string;
  originalPreview: string;
  enterDelay?: number;
}

export const EmailThreadCard: React.FC<EmailThreadCardProps> = ({
  replyFrom,
  replySubject,
  replyPreview,
  replyTime,
  originalSubject,
  originalPreview,
  enterDelay = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const enterP = spring({ frame: frame - enterDelay, fps, config: { damping: 200 } });
  const opacity = interpolate(enterP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const y = interpolate(enterP, [0, 1], [40, 0]);
  const scale = interpolate(enterP, [0, 1], [0.95, 1]);

  // Highlight pulse on reply row
  const highlightP = spring({ frame: frame - enterDelay - 10, fps, config: { damping: 200 } });
  const highlightOpacity = interpolate(highlightP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  return (
    <div
      style={{
        opacity,
        transform: `translateY(${y}px) scale(${scale})`,
        width: 860,
        background: COLORS.surface,
        borderRadius: 28,
        overflow: "hidden",
      }}
    >
      {/* Card header */}
      <div
        style={{
          padding: "22px 32px 16px",
          fontFamily: FONTS.body,
          fontSize: 22,
          color: COLORS.zinc400,
          fontWeight: 600,
          borderBottom: `1px solid ${COLORS.zinc700}`,
        }}
      >
        Inbox
      </div>

      {/* Reply row — NEW, highlighted */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          padding: "24px 32px",
          gap: 20,
          borderLeft: `4px solid ${COLORS.primary}`,
          background: `rgba(0, 187, 255, ${0.06 * highlightOpacity})`,
          borderBottom: `1px solid ${COLORS.zinc700}`,
        }}
      >
        <div style={{ width: 44, height: 44, borderRadius: "50%", background: COLORS.zinc700, flexShrink: 0 }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
            <span style={{ fontFamily: FONTS.body, fontSize: 26, fontWeight: 700, color: COLORS.textDark }}>
              {replyFrom}
            </span>
            <span style={{ fontFamily: FONTS.body, fontSize: 22, color: COLORS.zinc500 }}>{replyTime}</span>
          </div>
          <div style={{ fontFamily: FONTS.body, fontSize: 24, color: COLORS.zinc400, marginBottom: 2 }}>
            {replySubject}
          </div>
          <div
            style={{
              fontFamily: FONTS.body,
              fontSize: 22,
              color: COLORS.zinc500,
              overflow: "hidden",
              whiteSpace: "nowrap",
              textOverflow: "ellipsis",
            }}
          >
            {replyPreview}
          </div>
        </div>
        {/* NEW badge */}
        <div
          style={{
            background: COLORS.primary,
            color: "#000",
            borderRadius: 999,
            padding: "4px 14px",
            fontFamily: FONTS.body,
            fontSize: 18,
            fontWeight: 700,
            flexShrink: 0,
          }}
        >
          NEW
        </div>
      </div>

      {/* Original email row — muted */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          padding: "20px 32px",
          gap: 20,
          opacity: 0.4,
        }}
      >
        <div style={{ width: 44, height: 44, borderRadius: "50%", background: COLORS.zinc800, flexShrink: 0 }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontFamily: FONTS.body, fontSize: 24, fontWeight: 600, color: COLORS.zinc400, marginBottom: 2 }}>
            You
          </div>
          <div style={{ fontFamily: FONTS.body, fontSize: 22, color: COLORS.zinc500, marginBottom: 2 }}>
            {originalSubject}
          </div>
          <div
            style={{
              fontFamily: FONTS.body,
              fontSize: 22,
              color: COLORS.zinc500,
              overflow: "hidden",
              whiteSpace: "nowrap",
              textOverflow: "ellipsis",
            }}
          >
            {originalPreview}
          </div>
        </div>
      </div>
    </div>
  );
};
```

### ResearchCard.tsx

Builds itself on screen — header with VC name/fund, then bullet points type in one by one.

- [ ] **Step 2: Create ResearchCard.tsx**

```tsx
import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONTS } from "../constants";
interface ResearchItem {
  label: string;
  value: string;
}

interface ResearchCardProps {
  vcName: string;
  fund: string;
  focus: string;
  items: ResearchItem[];   // list of research bullet points
  enterDelay?: number;
}

export const ResearchCard: React.FC<ResearchCardProps> = ({
  vcName,
  fund,
  focus,
  items,
  enterDelay = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const enterP = spring({ frame: frame - enterDelay, fps, config: { damping: 22, stiffness: 100 } });
  const opacity = interpolate(enterP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const y = interpolate(enterP, [0, 1], [50, 0]);
  const scale = interpolate(enterP, [0, 1], [0.94, 1]);

  return (
    <div
      style={{
        opacity,
        transform: `translateY(${y}px) scale(${scale})`,
        width: 900,
        background: COLORS.surface,
        borderRadius: 28,
        padding: "40px 48px",
      }}
    >
      {/* Header */}
      <div style={{ marginBottom: 32 }}>
        <div
          style={{
            fontFamily: FONTS.display,
            fontSize: 44,
            fontWeight: 700,
            color: COLORS.textDark,
            marginBottom: 8,
          }}
        >
          {vcName}
        </div>
        <div style={{ fontFamily: FONTS.body, fontSize: 26, color: COLORS.primary, fontWeight: 600 }}>
          {fund}
        </div>
        <div style={{ fontFamily: FONTS.body, fontSize: 24, color: COLORS.zinc400, marginTop: 4 }}>
          {focus}
        </div>
      </div>

      {/* Divider */}
      <div style={{ height: 1, background: COLORS.zinc700, marginBottom: 28 }} />

      {/* Research items — stagger in */}
      {items.map((item, i) => {
        const itemDelay = enterDelay + 15 + i * 12;
        const itemP = spring({ frame: frame - itemDelay, fps, config: { damping: 200 } });
        const itemOpacity = interpolate(itemP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
        const itemY = interpolate(itemP, [0, 1], [15, 0]);

        return (
          <div
            key={i}
            style={{
              opacity: itemOpacity,
              transform: `translateY(${itemY}px)`,
              display: "flex",
              gap: 16,
              marginBottom: 20,
              alignItems: "flex-start",
            }}
          >
            <div
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: COLORS.primary,
                marginTop: 10,
                flexShrink: 0,
              }}
            />
            <div>
              <span style={{ fontFamily: FONTS.body, fontSize: 24, fontWeight: 600, color: COLORS.zinc400 }}>
                {item.label}:{" "}
              </span>
              <span style={{ fontFamily: FONTS.body, fontSize: 24, color: COLORS.textDark }}>
                {item.value}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
};
```

### DeckSlidesCard.tsx

Shows 4 slides fanning out from a stack, then the traction slide highlights with live metrics.

- [ ] **Step 3: Create DeckSlidesCard.tsx**

```tsx
import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONTS } from "../constants";

interface DeckSlide {
  title: string;
  highlight?: boolean; // traction slide gets highlighted
  metric?: string;     // shown on highlight slide
  metricLabel?: string;
}

interface DeckSlidesCardProps {
  slides: DeckSlide[];
  enterDelay?: number;
}

export const DeckSlidesCard: React.FC<DeckSlidesCardProps> = ({
  slides,
  enterDelay = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  return (
    <div
      style={{
        position: "relative",
        width: 900,
        height: 520,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {slides.map((slide, i) => {
        const slideDelay = enterDelay + i * 6;
        const p = spring({ frame: frame - slideDelay, fps, config: { damping: 22, stiffness: 100 } });
        const opacity = interpolate(p, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

        // Fan out: slides offset from center
        const fanOffset = (i - (slides.length - 1) / 2) * 120;
        const fanRotate = (i - (slides.length - 1) / 2) * 6;
        const x = interpolate(p, [0, 1], [0, fanOffset]);
        const rotate = interpolate(p, [0, 1], [0, fanRotate]);
        const zIndex = slide.highlight ? slides.length + 1 : i;

        return (
          <div
            key={i}
            style={{
              position: "absolute",
              opacity,
              transform: `translateX(${x}px) rotate(${rotate}deg)`,
              zIndex,
              width: 400,
              height: 280,
              background: slide.highlight ? COLORS.zinc900 : COLORS.surface,
              borderRadius: 20,
              border: slide.highlight ? `2px solid ${COLORS.primary}` : "none",
              padding: "28px 32px",
              display: "flex",
              flexDirection: "column",
              justifyContent: "space-between",
            }}
          >
            <div
              style={{
                fontFamily: FONTS.body,
                fontSize: 22,
                fontWeight: 600,
                color: slide.highlight ? COLORS.primary : COLORS.zinc400,
              }}
            >
              {slide.title}
            </div>
            {slide.highlight && slide.metric && (
              <div>
                <div
                  style={{
                    fontFamily: FONTS.display,
                    fontSize: 72,
                    fontWeight: 700,
                    color: COLORS.textDark,
                    lineHeight: 1,
                  }}
                >
                  {slide.metric}
                </div>
                <div style={{ fontFamily: FONTS.body, fontSize: 22, color: COLORS.zinc400, marginTop: 8 }}>
                  {slide.metricLabel}
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};
```

### SpreadsheetCard.tsx

Grid of cells that fill in one by one with numbers.

- [ ] **Step 4: Create SpreadsheetCard.tsx**

```tsx
import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONTS } from "../constants";

interface SpreadsheetRow {
  label: string;
  values: string[];
  highlight?: boolean;
}

interface SpreadsheetCardProps {
  title: string;
  headers: string[];
  rows: SpreadsheetRow[];
  enterDelay?: number;
}

export const SpreadsheetCard: React.FC<SpreadsheetCardProps> = ({
  title,
  headers,
  rows,
  enterDelay = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const enterP = spring({ frame: frame - enterDelay, fps, config: { damping: 22, stiffness: 100 } });
  const opacity = interpolate(enterP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const y = interpolate(enterP, [0, 1], [40, 0]);
  const scale = interpolate(enterP, [0, 1], [0.95, 1]);

  const cellWidth = 180;

  return (
    <div
      style={{
        opacity,
        transform: `translateY(${y}px) scale(${scale})`,
        width: 860,
        background: COLORS.surface,
        borderRadius: 28,
        overflow: "hidden",
      }}
    >
      {/* Title */}
      <div
        style={{
          padding: "24px 32px 20px",
          fontFamily: FONTS.body,
          fontSize: 26,
          fontWeight: 700,
          color: COLORS.textDark,
          borderBottom: `1px solid ${COLORS.zinc700}`,
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}
      >
        <span style={{ fontSize: 20, color: COLORS.primary }}>⬛</span>
        {title}
      </div>

      {/* Header row */}
      <div
        style={{
          display: "flex",
          padding: "14px 32px",
          borderBottom: `1px solid ${COLORS.zinc700}`,
          background: COLORS.zinc900,
        }}
      >
        <div style={{ width: 220, fontFamily: FONTS.body, fontSize: 20, color: COLORS.zinc400, fontWeight: 600 }}>
          Metric
        </div>
        {headers.map((h, i) => (
          <div
            key={i}
            style={{ width: cellWidth, fontFamily: FONTS.body, fontSize: 20, color: COLORS.zinc400, fontWeight: 600, textAlign: "right" }}
          >
            {h}
          </div>
        ))}
      </div>

      {/* Data rows */}
      {rows.map((row, rowIdx) => {
        const rowDelay = enterDelay + 15 + rowIdx * 8;

        return (
          <div
            key={rowIdx}
            style={{
              display: "flex",
              padding: "16px 32px",
              borderBottom: rowIdx < rows.length - 1 ? `1px solid ${COLORS.zinc700}` : "none",
              background: row.highlight ? `rgba(0,187,255,0.06)` : "transparent",
            }}
          >
            <div
              style={{
                width: 220,
                fontFamily: FONTS.body,
                fontSize: 24,
                color: row.highlight ? COLORS.primary : COLORS.zinc400,
                fontWeight: row.highlight ? 600 : 400,
              }}
            >
              {row.label}
            </div>
            {row.values.map((val, colIdx) => {
              const cellDelay = rowDelay + colIdx * 4;
              const cellP = spring({ frame: frame - cellDelay, fps, config: { damping: 200 } });
              const cellOpacity = interpolate(cellP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

              return (
                <div
                  key={colIdx}
                  style={{
                    width: cellWidth,
                    fontFamily: FONTS.mono,
                    fontSize: 24,
                    color: row.highlight ? COLORS.primary : COLORS.textDark,
                    fontWeight: row.highlight ? 700 : 400,
                    textAlign: "right",
                    opacity: cellOpacity,
                  }}
                >
                  {val}
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
};
```

### PrepDocCard.tsx

Google Doc-style card with questions typing in + talking points below each.

- [ ] **Step 5: Create PrepDocCard.tsx**

```tsx
import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONTS } from "../constants";

interface PrepQuestion {
  question: string;
  talkingPoint: string;
}

interface PrepDocCardProps {
  title: string;
  questions: PrepQuestion[];
  enterDelay?: number;
}

export const PrepDocCard: React.FC<PrepDocCardProps> = ({
  title,
  questions,
  enterDelay = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const enterP = spring({ frame: frame - enterDelay, fps, config: { damping: 22, stiffness: 100 } });
  const opacity = interpolate(enterP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const y = interpolate(enterP, [0, 1], [40, 0]);
  const scale = interpolate(enterP, [0, 1], [0.95, 1]);

  return (
    <div
      style={{
        opacity,
        transform: `translateY(${y}px) scale(${scale})`,
        width: 860,
        background: "#1c1c1e",
        borderRadius: 28,
        overflow: "hidden",
        border: `1px solid ${COLORS.zinc700}`,
      }}
    >
      {/* Doc header */}
      <div
        style={{
          padding: "22px 32px",
          background: COLORS.surface,
          borderBottom: `1px solid ${COLORS.zinc700}`,
          display: "flex",
          alignItems: "center",
          gap: 14,
        }}
      >
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: 8,
            background: "#4285f4",
            flexShrink: 0,
          }}
        />
        <span style={{ fontFamily: FONTS.body, fontSize: 24, fontWeight: 600, color: COLORS.textDark }}>
          {title}
        </span>
      </div>

      {/* Questions */}
      <div style={{ padding: "28px 32px" }}>
        {questions.map((q, i) => {
          const qDelay = enterDelay + 15 + i * 18;
          const qP = spring({ frame: frame - qDelay, fps, config: { damping: 200 } });
          const qOpacity = interpolate(qP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
          const qY = interpolate(qP, [0, 1], [12, 0]);

          const tpDelay = qDelay + 8;
          const tpP = spring({ frame: frame - tpDelay, fps, config: { damping: 200 } });
          const tpOpacity = interpolate(tpP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

          return (
            <div
              key={i}
              style={{
                opacity: qOpacity,
                transform: `translateY(${qY}px)`,
                marginBottom: 24,
              }}
            >
              <div
                style={{
                  fontFamily: FONTS.body,
                  fontSize: 23,
                  fontWeight: 700,
                  color: COLORS.textDark,
                  marginBottom: 6,
                }}
              >
                {i + 1}. {q.question}
              </div>
              <div
                style={{
                  opacity: tpOpacity,
                  fontFamily: FONTS.body,
                  fontSize: 21,
                  color: COLORS.zinc400,
                  paddingLeft: 20,
                  borderLeft: `3px solid ${COLORS.zinc700}`,
                }}
              >
                {q.talkingPoint}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
```

### SlackMessageCard.tsx

Slack message notification with workspace header, channel, and message.

- [ ] **Step 6: Create SlackMessageCard.tsx**

```tsx
import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONTS } from "../constants";

interface SlackMessageCardProps {
  workspace: string;
  channel: string;
  from: string;
  message: string;
  enterDelay?: number;
}

export const SlackMessageCard: React.FC<SlackMessageCardProps> = ({
  workspace,
  channel,
  from,
  message,
  enterDelay = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const enterP = spring({ frame: frame - enterDelay, fps, config: { damping: 22, stiffness: 100 } });
  const opacity = interpolate(enterP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const y = interpolate(enterP, [0, 1], [40, 0]);
  const scale = interpolate(enterP, [0, 1], [0.94, 1]);

  return (
    <div
      style={{
        opacity,
        transform: `translateY(${y}px) scale(${scale})`,
        width: 760,
        background: "#1a1d21",
        borderRadius: 28,
        overflow: "hidden",
        border: `1px solid #2d2d2d`,
      }}
    >
      {/* Slack header */}
      <div
        style={{
          padding: "18px 28px",
          background: "#19171d",
          borderBottom: "1px solid #2d2d2d",
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}
      >
        <div
          style={{
            width: 28,
            height: 28,
            borderRadius: 8,
            background: "#4a154b",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          {/* Slack hash-like icon */}
          <div style={{ width: 14, height: 14, background: "#e01e5a", borderRadius: 2 }} />
        </div>
        <span style={{ fontFamily: FONTS.body, fontSize: 22, color: "#d1d2d3", fontWeight: 700 }}>
          {workspace}
        </span>
        <span style={{ fontFamily: FONTS.body, fontSize: 20, color: "#6b6f76", marginLeft: 4 }}>
          #{channel}
        </span>
      </div>

      {/* Message */}
      <div style={{ padding: "24px 28px", display: "flex", gap: 16 }}>
        <div
          style={{
            width: 44,
            height: 44,
            borderRadius: 8,
            background: COLORS.primary,
            flexShrink: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontFamily: FONTS.body,
            fontSize: 18,
            fontWeight: 700,
            color: "#000",
          }}
        >
          G
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
            <span style={{ fontFamily: FONTS.body, fontSize: 24, fontWeight: 700, color: "#d1d2d3" }}>
              {from}
            </span>
            <span style={{ fontFamily: FONTS.body, fontSize: 18, color: "#6b6f76" }}>
              just now
            </span>
          </div>
          <div style={{ fontFamily: FONTS.body, fontSize: 24, color: "#d1d2d3", lineHeight: 1.5 }}>
            {message}
          </div>
        </div>
      </div>
    </div>
  );
};
```

### CalendarSlotsCard.tsx

Calendar week view with 3 available slots highlighted and a prep block inserted before each.

- [ ] **Step 7: Create CalendarSlotsCard.tsx**

```tsx
import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONTS } from "../constants";

interface CalendarSlot {
  day: string;
  time: string;
  prepTime: string;
}

interface CalendarSlotsCardProps {
  slots: CalendarSlot[];
  enterDelay?: number;
}

export const CalendarSlotsCard: React.FC<CalendarSlotsCardProps> = ({
  slots,
  enterDelay = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const enterP = spring({ frame: frame - enterDelay, fps, config: { damping: 22, stiffness: 100 } });
  const opacity = interpolate(enterP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const y = interpolate(enterP, [0, 1], [40, 0]);
  const scale = interpolate(enterP, [0, 1], [0.95, 1]);

  return (
    <div
      style={{
        opacity,
        transform: `translateY(${y}px) scale(${scale})`,
        width: 860,
        background: COLORS.surface,
        borderRadius: 28,
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "22px 32px",
          borderBottom: `1px solid ${COLORS.zinc700}`,
          fontFamily: FONTS.body,
          fontSize: 26,
          fontWeight: 700,
          color: COLORS.textDark,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <span>This Week</span>
        <span style={{ fontSize: 20, color: COLORS.zinc500, fontWeight: 400 }}>3 slots found</span>
      </div>

      {/* Slots */}
      <div style={{ padding: "24px 32px" }}>
        {slots.map((slot, i) => {
          const slotDelay = enterDelay + 15 + i * 10;
          const slotP = spring({ frame: frame - slotDelay, fps, config: { damping: 200 } });
          const slotOpacity = interpolate(slotP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
          const slotY = interpolate(slotP, [0, 1], [20, 0]);

          const prepDelay = slotDelay + 8;
          const prepP = spring({ frame: frame - prepDelay, fps, config: { damping: 200 } });
          const prepOpacity = interpolate(prepP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

          return (
            <div
              key={i}
              style={{
                opacity: slotOpacity,
                transform: `translateY(${slotY}px)`,
                marginBottom: 20,
              }}
            >
              {/* Prep block */}
              <div
                style={{
                  opacity: prepOpacity,
                  background: `rgba(0,187,255,0.08)`,
                  border: `1px dashed ${COLORS.primary}`,
                  borderRadius: 12,
                  padding: "10px 18px",
                  marginBottom: 6,
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                }}
              >
                <div style={{ width: 8, height: 8, borderRadius: "50%", background: COLORS.primary }} />
                <span style={{ fontFamily: FONTS.body, fontSize: 20, color: COLORS.primary }}>
                  Prep — {slot.prepTime} · 30 min
                </span>
              </div>

              {/* Meeting slot */}
              <div
                style={{
                  background: COLORS.primary,
                  borderRadius: 12,
                  padding: "14px 18px",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                }}
              >
                <span style={{ fontFamily: FONTS.body, fontSize: 24, fontWeight: 700, color: "#000" }}>
                  {slot.day}
                </span>
                <span style={{ fontFamily: FONTS.body, fontSize: 22, fontWeight: 600, color: "#000" }}>
                  {slot.time}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
```

### EmailComposeCard.tsx

Email compose window with To field, subject, body typing, attachment chips, and a CRM status pill.

- [ ] **Step 8: Create EmailComposeCard.tsx**

```tsx
import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONTS } from "../constants";
import { TypingText } from "./TypingText";

interface EmailComposeCardProps {
  to: string;
  subject: string;
  body: string;
  attachments: string[];
  enterDelay?: number;
  bodyTypingDelay?: number;
  crmStatus?: string; // shown as a flipping chip e.g. "Replied"
}

export const EmailComposeCard: React.FC<EmailComposeCardProps> = ({
  to,
  subject,
  body,
  attachments,
  enterDelay = 0,
  bodyTypingDelay = 0,
  crmStatus,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const enterP = spring({ frame: frame - enterDelay, fps, config: { damping: 22, stiffness: 100 } });
  const opacity = interpolate(enterP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const y = interpolate(enterP, [0, 1], [40, 0]);
  const scale = interpolate(enterP, [0, 1], [0.95, 1]);

  // Attachments stagger in
  const attachDelay = bodyTypingDelay + Math.ceil(body.length * 0.5) + 10;

  // CRM chip appears last
  const crmDelay = attachDelay + attachments.length * 8 + 10;
  const crmP = spring({ frame: frame - crmDelay, fps, config: { damping: 200 } });
  const crmOpacity = crmStatus
    ? interpolate(crmP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" })
    : 0;

  return (
    <div
      style={{
        opacity,
        transform: `translateY(${y}px) scale(${scale})`,
        width: 860,
        background: COLORS.surface,
        borderRadius: 28,
        overflow: "hidden",
      }}
    >
      {/* Compose header */}
      <div
        style={{
          padding: "22px 32px",
          borderBottom: `1px solid ${COLORS.zinc700}`,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span style={{ fontFamily: FONTS.body, fontSize: 26, fontWeight: 700, color: COLORS.textDark }}>
          New Message
        </span>
        {crmStatus && (
          <div
            style={{
              opacity: crmOpacity,
              background: "#22c55e22",
              border: "1px solid #22c55e",
              borderRadius: 999,
              padding: "6px 18px",
              fontFamily: FONTS.body,
              fontSize: 20,
              color: "#22c55e",
              fontWeight: 600,
            }}
          >
            CRM: {crmStatus}
          </div>
        )}
      </div>

      {/* Fields */}
      <div style={{ padding: "0 32px" }}>
        {/* To */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            padding: "18px 0",
            borderBottom: `1px solid ${COLORS.zinc700}`,
            gap: 16,
          }}
        >
          <span style={{ fontFamily: FONTS.body, fontSize: 22, color: COLORS.zinc500, width: 80 }}>To</span>
          <span style={{ fontFamily: FONTS.body, fontSize: 24, color: COLORS.textDark }}>{to}</span>
        </div>

        {/* Subject */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            padding: "18px 0",
            borderBottom: `1px solid ${COLORS.zinc700}`,
            gap: 16,
          }}
        >
          <span style={{ fontFamily: FONTS.body, fontSize: 22, color: COLORS.zinc500, width: 80 }}>Subject</span>
          <span style={{ fontFamily: FONTS.body, fontSize: 24, color: COLORS.textDark, fontWeight: 600 }}>
            {subject}
          </span>
        </div>

        {/* Body */}
        <div style={{ padding: "24px 0 20px" }}>
          <TypingText
            text={body}
            framesPerChar={0.5}
            delay={bodyTypingDelay}
            showCursor={false}
            style={{
              fontFamily: FONTS.body,
              fontSize: 24,
              color: COLORS.textDark,
              lineHeight: "1.65",
              whiteSpace: "pre-wrap",
            }}
          />
        </div>

        {/* Attachments */}
        <div style={{ display: "flex", gap: 10, paddingBottom: 28, flexWrap: "wrap" }}>
          {attachments.map((att, i) => {
            const attDelay = attachDelay + i * 6;
            const attP = spring({ frame: frame - attDelay, fps, config: { damping: 200 } });
            const attOpacity = interpolate(attP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
            const attScale = interpolate(attP, [0, 1], [0.8, 1]);

            return (
              <div
                key={i}
                style={{
                  opacity: attOpacity,
                  transform: `scale(${attScale})`,
                  background: COLORS.zinc900,
                  borderRadius: 12,
                  padding: "10px 18px",
                  fontFamily: FONTS.body,
                  fontSize: 20,
                  color: COLORS.zinc400,
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                }}
              >
                <div style={{ width: 8, height: 8, borderRadius: 2, background: COLORS.primary }} />
                {att}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
```

- [ ] **Step 9: Commit all UI card components**

```bash
git add apps/video2/src/components/
git commit -m "feat(video2): add UI card components — EmailThread, Research, DeckSlides, Spreadsheet, PrepDoc, Slack, Calendar, EmailCompose"
```

---

## Task 5: Scene files

Each scene follows the same pattern: `AbsoluteFill` with dark background, entrance spring animation, content centered, optional SFX via `<Sequence>/<Audio>`. The "full-screen takeover" mechanic is handled by scaling up the card to fill the screen using an interpolated scale/position animation triggered mid-scene.

**Full-screen takeover pattern** used in S03–S09:
```
0-10f:   Chat thread visible with new GAIA message appearing
10-20f:  Card slides up from bottom (spring, damping 18)
20-[scene end - 15f]: Card fills screen, content animates
[scene end - 15f] to end: Card compresses back down (spring, damping 200)
```

**Files:**
- Create: all 11 scene files in `apps/video2/src/scenes/`

### S01_Notification.tsx

- [ ] **Step 1: Create S01_Notification.tsx**

```tsx
import type React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { COLORS, FONTS } from "../constants";
import { SFX } from "../sfx";

export const S01_Notification: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Notification slides in from top
  const notifP = spring({ frame: frame - 15, fps, config: { damping: 18, stiffness: 120 } });
  const notifY = interpolate(notifP, [0, 1], [-200, 0]);
  const notifOpacity = interpolate(notifP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ background: COLORS.bgLight, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <Sequence from={15}>
        <Audio src={SFX.uiSwitch} volume={0.35} />
      </Sequence>

      {/* App icon + notification card */}
      <div
        style={{
          transform: `translateY(${notifY}px)`,
          opacity: notifOpacity,
          display: "flex",
          alignItems: "flex-start",
          gap: 20,
          background: "rgba(30, 30, 32, 0.97)",
          borderRadius: 35,
          padding: "30px 40px 30px 25px",
          width: 860,
        }}
      >
        {/* Telegram/WhatsApp icon placeholder */}
        <div
          style={{
            width: 88,
            height: 88,
            borderRadius: 20,
            background: "#229ed9",
            flexShrink: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontFamily: FONTS.body,
            fontSize: 36,
            fontWeight: 700,
            color: "#fff",
          }}
        >
          T
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
            <span style={{ color: COLORS.zinc400, fontSize: 24, fontFamily: FONTS.body, fontWeight: 500 }}>
              Telegram · GAIA
            </span>
            <span style={{ color: COLORS.zinc500, fontSize: 20, fontFamily: FONTS.body }}>now</span>
          </div>
          <div style={{ color: COLORS.textDark, fontSize: 34, fontFamily: FONTS.body, fontWeight: 700, marginBottom: 6 }}>
            The VC replied.
          </div>
          <div style={{ color: COLORS.zinc400, fontSize: 26, fontFamily: FONTS.body, lineHeight: 1.4 }}>
            I've handled everything overnight.
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
```

### S02_TheReply.tsx

- [ ] **Step 2: Create S02_TheReply.tsx**

```tsx
import type React from "react";
import { AbsoluteFill, Audio, Sequence, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS } from "../constants";
import { SFX } from "../sfx";
import { ChatThread } from "../components/ChatThread";
import { EmailThreadCard } from "../components/EmailThreadCard";

export const S02_TheReply: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Email card slides up below the thread
  const cardP = spring({ frame: frame - 50, fps, config: { damping: 22, stiffness: 100 } });
  const cardY = interpolate(cardP, [0, 1], [60, 0]);
  const cardOpacity = interpolate(cardP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 36,
      }}
    >
      <Sequence from={8}>
        <Audio src={SFX.uiSwitch} volume={0.25} />
      </Sequence>
      <Sequence from={50}>
        <Audio src={SFX.uiSwitch} volume={0.2} />
      </Sequence>

      <ChatThread
        appName="Telegram"
        contactName="GAIA"
        enterDelay={0}
        messages={[
          {
            message: "Sarah Chen at Sequoia replied. She wants your deck, latest metrics, and a time to meet.",
            timestamp: "11:52 PM",
            delay: 8,
          },
        ]}
      />

      <div style={{ opacity: cardOpacity, transform: `translateY(${cardY}px)` }}>
        <EmailThreadCard
          replyFrom="Sarah Chen"
          replySubject="Re: Quick question about your Series A"
          replyPreview="Hi — interesting timing, we've been looking at this space. Can you send over your current deck and..."
          replyTime="11:52 PM"
          originalSubject="Quick question about your Series A"
          originalPreview="Hi Sarah, following up on my note from last week..."
          enterDelay={50}
        />
      </div>
    </AbsoluteFill>
  );
};
```

### S03_Research.tsx through S09_ReplyDrafted.tsx

Each scene shows: GAIA chat bubble with the timestamp message + the full-screen takeover card.

- [ ] **Step 3: Create S03_Research.tsx**

```tsx
import type React from "react";
import { AbsoluteFill, Audio, Sequence, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS } from "../constants";
import { SFX } from "../sfx";
import { ChatThread } from "../components/ChatThread";
import { ResearchCard } from "../components/ResearchCard";

export const S03_Research: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Card takeover: starts at frame 40, scales up to fill more of screen
  const takeoverP = spring({ frame: frame - 40, fps, config: { damping: 22, stiffness: 100 } });
  const cardScale = interpolate(takeoverP, [0, 1], [1, 1.08]);

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 36,
      }}
    >
      <Sequence from={8}>
        <Audio src={SFX.whoosh} volume={0.25} />
      </Sequence>
      <Sequence from={40}>
        <Audio src={SFX.uiSwitch} volume={0.25} />
      </Sequence>

      <ChatThread
        appName="Telegram"
        contactName="GAIA"
        enterDelay={0}
        messages={[
          {
            message: "Looked her up. Found what she cares about.",
            timestamp: "11:58 PM",
            delay: 8,
          },
        ]}
      />

      <div style={{ transform: `scale(${cardScale})` }}>
        <ResearchCard
          vcName="Sarah Chen"
          fund="Sequoia Capital"
          focus="Series A · B2B SaaS · $8–15M rounds"
          items={[
            { label: "Recent deals", value: "Notion, Linear, Loom — all productivity-layer SaaS" },
            { label: "Thesis", value: "Bets on tools that remove friction from knowledge work" },
            { label: "Portfolio overlap", value: "3 companies adjacent to your space" },
            { label: "Avg check size", value: "$10M, typically leads the round" },
          ]}
          enterDelay={30}
        />
      </div>
    </AbsoluteFill>
  );
};
```

- [ ] **Step 4: Create S04_DeckUpdated.tsx**

```tsx
import type React from "react";
import { AbsoluteFill, Audio, Sequence, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS } from "../constants";
import { SFX } from "../sfx";
import { ChatThread } from "../components/ChatThread";
import { DeckSlidesCard } from "../components/DeckSlidesCard";

export const S04_DeckUpdated: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const takeoverP = spring({ frame: frame - 40, fps, config: { damping: 22, stiffness: 100 } });
  const cardScale = interpolate(takeoverP, [0, 1], [1, 1.08]);

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 36,
      }}
    >
      <Sequence from={8}>
        <Audio src={SFX.whoosh} volume={0.25} />
      </Sequence>
      <Sequence from={40}>
        <Audio src={SFX.uiSwitch} volume={0.25} />
      </Sequence>
      <Sequence from={80}>
        <Audio src={SFX.whip} volume={0.5} />
      </Sequence>

      <ChatThread
        appName="Telegram"
        contactName="GAIA"
        enterDelay={0}
        messages={[
          {
            message: "Updated your deck. Metrics current, narrative tailored to her thesis.",
            timestamp: "12:20 AM",
            delay: 8,
          },
        ]}
      />

      <div style={{ transform: `scale(${cardScale})` }}>
        <DeckSlidesCard
          enterDelay={30}
          slides={[
            { title: "Company Overview" },
            { title: "Market Opportunity" },
            { title: "Traction", highlight: true, metric: "$47K", metricLabel: "MRR · +18% MoM" },
            { title: "The Ask" },
          ]}
        />
      </div>
    </AbsoluteFill>
  );
};
```

- [ ] **Step 5: Create S05_DataRoom.tsx**

```tsx
import type React from "react";
import { AbsoluteFill, Audio, Sequence, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS } from "../constants";
import { SFX } from "../sfx";
import { ChatThread } from "../components/ChatThread";
import { SpreadsheetCard } from "../components/SpreadsheetCard";

export const S05_DataRoom: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const takeoverP = spring({ frame: frame - 35, fps, config: { damping: 22, stiffness: 100 } });
  const cardScale = interpolate(takeoverP, [0, 1], [1, 1.08]);

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 36,
      }}
    >
      <Sequence from={8}>
        <Audio src={SFX.whoosh} volume={0.25} />
      </Sequence>
      <Sequence from={35}>
        <Audio src={SFX.uiSwitch} volume={0.2} />
      </Sequence>

      <ChatThread
        appName="Telegram"
        contactName="GAIA"
        enterDelay={0}
        messages={[
          {
            message: "Data room cleaned up. Every number she'll dig into is there.",
            timestamp: "1:15 AM",
            delay: 8,
          },
        ]}
      />

      <div style={{ transform: `scale(${cardScale})` }}>
        <SpreadsheetCard
          title="Data Room · Q1 2026"
          headers={["Jan", "Feb", "Mar"]}
          rows={[
            { label: "MRR", values: ["$38K", "$43K", "$47K"], highlight: true },
            { label: "Growth MoM", values: ["14%", "13%", "18%"], highlight: true },
            { label: "Runway", values: ["—", "—", "14mo"] },
            { label: "Customers", values: ["1.8K", "2.1K", "2.4K"] },
            { label: "Churn", values: ["2.1%", "1.9%", "1.7%"] },
          ]}
          enterDelay={25}
        />
      </div>
    </AbsoluteFill>
  );
};
```

- [ ] **Step 6: Create S06_PrepDoc.tsx**

```tsx
import type React from "react";
import { AbsoluteFill, Audio, Sequence, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS } from "../constants";
import { SFX } from "../sfx";
import { ChatThread } from "../components/ChatThread";
import { PrepDocCard } from "../components/PrepDocCard";

export const S06_PrepDoc: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const takeoverP = spring({ frame: frame - 40, fps, config: { damping: 22, stiffness: 100 } });
  const cardScale = interpolate(takeoverP, [0, 1], [1, 1.06]);

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 36,
      }}
    >
      <Sequence from={8}>
        <Audio src={SFX.whoosh} volume={0.25} />
      </Sequence>
      <Sequence from={40}>
        <Audio src={SFX.uiSwitch} volume={0.2} />
      </Sequence>

      <ChatThread
        appName="Telegram"
        contactName="GAIA"
        enterDelay={0}
        messages={[
          {
            message: "Created a prep doc — likely questions she'll ask with your talking points.",
            timestamp: "2:30 AM",
            delay: 8,
          },
        ]}
      />

      <div style={{ transform: `scale(${cardScale})` }}>
        <PrepDocCard
          title="Sequoia Meeting Prep"
          enterDelay={30}
          questions={[
            {
              question: "What's your CAC payback period?",
              talkingPoint: "Currently 4 months — below our Series A benchmark of 6.",
            },
            {
              question: "Who's your biggest competitor?",
              talkingPoint: "No direct comp. Adjacent players (Zapier, Notion AI) don't do proactive automation.",
            },
            {
              question: "Why now?",
              talkingPoint: "LLM costs down 10x in 18 months — makes real-time proactive agents viable at our price point.",
            },
            {
              question: "What does the $10M go toward?",
              talkingPoint: "40% eng hiring, 35% GTM, 25% infra scale.",
            },
          ]}
        />
      </div>
    </AbsoluteFill>
  );
};
```

- [ ] **Step 7: Create S07_SlackNotify.tsx**

```tsx
import type React from "react";
import { AbsoluteFill, Audio, Sequence, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS } from "../constants";
import { SFX } from "../sfx";
import { ChatThread } from "../components/ChatThread";
import { SlackMessageCard } from "../components/SlackMessageCard";

export const S07_SlackNotify: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const cardP = spring({ frame: frame - 35, fps, config: { damping: 22, stiffness: 100 } });
  const cardOpacity = interpolate(cardP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const cardY = interpolate(cardP, [0, 1], [30, 0]);

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 36,
      }}
    >
      <Sequence from={8}>
        <Audio src={SFX.whoosh} volume={0.25} />
      </Sequence>
      <Sequence from={35}>
        <Audio src={SFX.uiSwitch} volume={0.25} />
      </Sequence>

      <ChatThread
        appName="Telegram"
        contactName="GAIA"
        enterDelay={0}
        messages={[
          {
            message: "Slacked your co-founder.",
            timestamp: "5:00 AM",
            delay: 8,
          },
        ]}
      />

      <div style={{ opacity: cardOpacity, transform: `translateY(${cardY}px)` }}>
        <SlackMessageCard
          workspace="Company"
          channel="founders"
          from="GAIA"
          message="Heads up — Sequoia replied. Meeting likely this week. Deck updated, data room clean, prep doc ready."
          enterDelay={30}
        />
      </div>
    </AbsoluteFill>
  );
};
```

- [ ] **Step 8: Create S08_CalendarSlots.tsx**

```tsx
import type React from "react";
import { AbsoluteFill, Audio, Sequence, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS } from "../constants";
import { SFX } from "../sfx";
import { ChatThread } from "../components/ChatThread";
import { CalendarSlotsCard } from "../components/CalendarSlotsCard";

export const S08_CalendarSlots: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const takeoverP = spring({ frame: frame - 40, fps, config: { damping: 22, stiffness: 100 } });
  const cardScale = interpolate(takeoverP, [0, 1], [1, 1.06]);

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 36,
      }}
    >
      <Sequence from={8}>
        <Audio src={SFX.whoosh} volume={0.25} />
      </Sequence>
      <Sequence from={40}>
        <Audio src={SFX.uiSwitch} volume={0.2} />
      </Sequence>

      <ChatThread
        appName="Telegram"
        contactName="GAIA"
        enterDelay={0}
        messages={[
          {
            message: "Found 3 open slots. Added a 30-min prep block before each.",
            timestamp: "6:30 AM",
            delay: 8,
          },
        ]}
      />

      <div style={{ transform: `scale(${cardScale})` }}>
        <CalendarSlotsCard
          enterDelay={30}
          slots={[
            { day: "Tuesday", time: "2:00 PM", prepTime: "1:30 PM" },
            { day: "Wednesday", time: "10:00 AM", prepTime: "9:30 AM" },
            { day: "Thursday", time: "3:00 PM", prepTime: "2:30 PM" },
          ]}
        />
      </div>
    </AbsoluteFill>
  );
};
```

- [ ] **Step 9: Create S09_ReplyDrafted.tsx**

```tsx
import type React from "react";
import { AbsoluteFill, Audio, Sequence, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS } from "../constants";
import { SFX } from "../sfx";
import { ChatThread } from "../components/ChatThread";
import { EmailComposeCard } from "../components/EmailComposeCard";

export const S09_ReplyDrafted: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const takeoverP = spring({ frame: frame - 35, fps, config: { damping: 22, stiffness: 100 } });
  const cardScale = interpolate(takeoverP, [0, 1], [1, 1.06]);

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 36,
      }}
    >
      <Sequence from={8}>
        <Audio src={SFX.whoosh} volume={0.25} />
      </Sequence>

      <ChatThread
        appName="Telegram"
        contactName="GAIA"
        enterDelay={0}
        messages={[
          {
            message: "Wrote your reply. Deck, data room, and 3 time slots attached.",
            timestamp: "6:58 AM",
            delay: 8,
          },
        ]}
      />

      <div style={{ transform: `scale(${cardScale})` }}>
        <EmailComposeCard
          to="sarah.chen@sequoia.com"
          subject="Re: Quick question about your Series A"
          body={`Hi Sarah,\n\nThanks for getting back — great timing.\n\nI've attached our deck and data room below. Happy to jump on a call this week.`}
          attachments={["Series_A_Deck.pdf", "Data Room →", "Tue 2pm / Wed 10am / Thu 3pm"]}
          enterDelay={25}
          bodyTypingDelay={35}
          crmStatus="Replied"
        />
      </div>
    </AbsoluteFill>
  );
};
```

### S10_TheBeat.tsx

Full chat thread with all 7 messages + checkmarks. GAIA asks. User replies "Send it."

- [ ] **Step 10: Create S10_TheBeat.tsx**

```tsx
import type React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { COLORS, FONTS } from "../constants";
import { SFX } from "../sfx";
import { ChatThread } from "../components/ChatThread";

export const S10_TheBeat: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // GAIA's final question appears at frame 60
  const finalMsgP = spring({ frame: frame - 60, fps, config: { damping: 200 } });
  const finalMsgOpacity = interpolate(finalMsgP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const finalMsgY = interpolate(finalMsgP, [0, 1], [15, 0]);

  // Typing indicator at frame 100
  const typingP = spring({ frame: frame - 100, fps, config: { damping: 200 } });
  const typingOpacity = interpolate(typingP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  // "Send it." bubble at frame 130
  const sendP = spring({ frame: frame - 130, fps, config: { damping: 200 } });
  const sendOpacity = interpolate(sendP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const sendY = interpolate(sendP, [0, 1], [15, 0]);

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <Sequence from={130}>
        <Audio src={SFX.whip} volume={0.55} />
      </Sequence>

      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", width: 900, gap: 0 }}>
        {/* All previous messages with checkmarks */}
        <ChatThread
          appName="Telegram"
          contactName="GAIA"
          enterDelay={0}
          messages={[
            { message: "Looked her up. Found what she cares about.", timestamp: "11:58 PM", delay: 0, showCheckmark: true, checkmarkDelay: 5 },
            { message: "Updated your deck. Metrics current, narrative tailored to her thesis.", timestamp: "12:20 AM", delay: 4, showCheckmark: true, checkmarkDelay: 9 },
            { message: "Data room cleaned up. Every number she'll dig into is there.", timestamp: "1:15 AM", delay: 8, showCheckmark: true, checkmarkDelay: 13 },
            { message: "Created a prep doc with likely questions and talking points.", timestamp: "2:30 AM", delay: 12, showCheckmark: true, checkmarkDelay: 17 },
            { message: "Slacked your co-founder.", timestamp: "5:00 AM", delay: 16, showCheckmark: true, checkmarkDelay: 21 },
            { message: "Found 3 open slots. Added a 30-min prep block before each.", timestamp: "6:30 AM", delay: 20, showCheckmark: true, checkmarkDelay: 25 },
            { message: "Wrote your reply. Deck, data room, and 3 time slots attached.", timestamp: "6:58 AM", delay: 24, showCheckmark: true, checkmarkDelay: 29 },
          ]}
        />

        {/* Final GAIA question */}
        <div
          style={{
            opacity: finalMsgOpacity,
            transform: `translateY(${finalMsgY}px)`,
            padding: "0 36px 16px",
          }}
        >
          <div
            style={{
              background: COLORS.surface,
              borderRadius: "40px 40px 40px 8px",
              padding: "22px 30px",
              fontFamily: FONTS.body,
              fontSize: 28,
              fontWeight: 500,
              color: COLORS.zinc400,
              maxWidth: 680,
              lineHeight: 1.45,
            }}
          >
            Ready to send. Want to review first, or just go?
          </div>
        </div>

        {/* Typing indicator */}
        <div
          style={{
            opacity: typingOpacity,
            display: "flex",
            justifyContent: "flex-end",
            padding: "0 36px 12px",
            width: "100%",
          }}
        >
          <div style={{ display: "flex", gap: 6, padding: "14px 20px", background: COLORS.primary, borderRadius: "40px 40px 8px 40px" }}>
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: "50%",
                  background: "#000",
                  opacity: Math.sin((frame - 100) / 8 + i * 1.2) * 0.5 + 0.5,
                }}
              />
            ))}
          </div>
        </div>

        {/* "Send it." user bubble */}
        <div
          style={{
            opacity: sendOpacity,
            transform: `translateY(${sendY}px)`,
            display: "flex",
            justifyContent: "flex-end",
            padding: "0 36px",
            width: "100%",
          }}
        >
          <div
            style={{
              background: COLORS.primary,
              borderRadius: "40px 40px 8px 40px",
              padding: "22px 36px",
              fontFamily: FONTS.body,
              fontSize: 32,
              fontWeight: 700,
              color: "#000",
            }}
          >
            Send it.
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
```

### S11_Close.tsx

Three-line typography payoff + logo + CTA.

- [ ] **Step 11: Create S11_Close.tsx**

```tsx
import type React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { COLORS, FONTS } from "../constants";
import { SFX } from "../sfx";
import { TypingText } from "../components/TypingText";

const WordBeat: React.FC<{
  text: string;
  startFrame: number;
  color?: string;
  fontSize?: number;
}> = ({ text, startFrame, color = COLORS.textDark, fontSize = 120 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  if (frame < startFrame) return null;

  const p = spring({ frame: frame - startFrame, fps, config: { damping: 200 } });
  const scale = interpolate(p, [0, 0.5, 1], [1.05, 1.01, 1.0]);
  const opacity = interpolate(p, [0, 0.05], [0, 1], { extrapolateRight: "clamp" });

  return (
    <div
      style={{
        transform: `scale(${scale})`,
        opacity,
        fontFamily: FONTS.display,
        fontSize,
        fontWeight: 800,
        color,
        textTransform: "uppercase",
        textAlign: "center",
        letterSpacing: "-0.03em",
        lineHeight: 1,
      }}
    >
      {text}
    </div>
  );
};

export const S11_Close: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Logo fade in at frame 210
  const logoP = spring({ frame: frame - 210, fps, config: { damping: 200 } });
  const logoOpacity = interpolate(logoP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 20,
      }}
    >
      <Sequence from={0}>
        <Audio src={SFX.whip} volume={0.55} />
      </Sequence>
      <Sequence from={60}>
        <Audio src={SFX.whip} volume={0.5} />
      </Sequence>
      <Sequence from={120}>
        <Audio src={SFX.whip} volume={0.45} />
      </Sequence>

      {/* Radial bloom */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: `radial-gradient(ellipse at 50% 55%, ${COLORS.primary}14 0%, transparent 45%)`,
          opacity: interpolate(frame, [0, 20], [0, 1], { extrapolateRight: "clamp" }),
          pointerEvents: "none",
        }}
      />

      <WordBeat text="They replied at midnight." startFrame={0} fontSize={96} />
      <WordBeat text="You replied at 7am" startFrame={60} fontSize={96} />
      <WordBeat text="with everything." startFrame={120} color={COLORS.primary} fontSize={96} />

      {/* Logo + CTA */}
      <div
        style={{
          opacity: logoOpacity,
          marginTop: 60,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 24,
        }}
      >
        <div
          style={{
            fontFamily: FONTS.display,
            fontSize: 52,
            fontWeight: 700,
            color: COLORS.textDark,
            textTransform: "uppercase",
            letterSpacing: "-0.02em",
          }}
        >
          GAIA
        </div>
        <div
          style={{
            background: COLORS.surface,
            borderRadius: 999,
            padding: "18px 40px",
            fontFamily: FONTS.body,
            fontSize: 30,
            color: COLORS.zinc400,
            minWidth: 340,
            textAlign: "center",
          }}
        >
          <TypingText
            text="heygaia.io"
            framesPerChar={3}
            delay={220}
            cursorColor={COLORS.primary}
            style={{ fontFamily: FONTS.body, fontSize: 30, color: COLORS.textDark }}
          />
        </div>
      </div>
    </AbsoluteFill>
  );
};
```

- [ ] **Step 12: Commit all scenes**

```bash
git add apps/video2/src/scenes/
git commit -m "feat(video2): add all 11 scene files"
```

---

## Task 6: Main composition and Root

**Files:**
- Create: `apps/video2/src/GaiaFounders.tsx`
- Create: `apps/video2/src/Root.tsx`

- [ ] **Step 1: Create GaiaFounders.tsx**

```tsx
import {
  linearTiming,
  springTiming,
  TransitionSeries,
} from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { slide } from "@remotion/transitions/slide";
import type React from "react";
import { Audio, Sequence } from "remotion";
import { SPRINGS, TRANSITIONS } from "./constants";
import { S01_Notification } from "./scenes/S01_Notification";
import { S02_TheReply } from "./scenes/S02_TheReply";
import { S03_Research } from "./scenes/S03_Research";
import { S04_DeckUpdated } from "./scenes/S04_DeckUpdated";
import { S05_DataRoom } from "./scenes/S05_DataRoom";
import { S06_PrepDoc } from "./scenes/S06_PrepDoc";
import { S07_SlackNotify } from "./scenes/S07_SlackNotify";
import { S08_CalendarSlots } from "./scenes/S08_CalendarSlots";
import { S09_ReplyDrafted } from "./scenes/S09_ReplyDrafted";
import { S10_TheBeat } from "./scenes/S10_TheBeat";
import { S11_Close } from "./scenes/S11_Close";
import { SFX } from "./sfx";

const T = TRANSITIONS;
const S = SPRINGS;

// Absolute frame offsets for slide transitions (whoosh SFX sync)
// Formula: abs_N = abs_(N-1) + duration_(N-1) - transition_(N-1)
// S01→S02 and S09→S10 are fades — silent, omitted from WHOOSH_FRAMES
// Absolute starts:
// S01 starts at 0, dur 180
// transition fade 8f
// S02 starts at 180-8=172, dur 240
// transition slide 12f
// S03 starts at 172+240-12=400, dur 240
// transition slide 12f
// S04 starts at 400+240-12=628, dur 240
// transition slide 12f
// S05 starts at 628+240-12=856, dur 180
// transition slide 12f
// S06 starts at 856+180-12=1024, dur 210
// transition slide 12f
// S07 starts at 1024+210-12=1222, dur 120
// transition slide 12f
// S08 starts at 1222+120-12=1330, dur 180
// transition slide 12f
// S09 starts at 1330+180-12=1498, dur 150
// transition fade 8f
// S10 starts at 1498+150-8=1640, dur 240
// transition slide 12f
// S11 starts at 1640+240-12=1868, dur 360
// Total = 1868+360 = 2228

const WHOOSH_FRAMES = [
  400,   // S02→S03
  628,   // S03→S04
  856,   // S04→S05
  1024,  // S05→S06
  1222,  // S06→S07
  1330,  // S07→S08
  1498,  // S08→S09
  1868,  // S10→S11
] as const;

export const GaiaFounders: React.FC = () => {
  return (
    <>
      <TransitionSeries>
        {/* S01: Notification */}
        <TransitionSeries.Sequence durationInFrames={180}>
          <S01_Notification />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: T.fast })}
        />

        {/* S02: The Reply */}
        <TransitionSeries.Sequence durationInFrames={240}>
          <S02_TheReply />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={springTiming({ config: S.natural, durationInFrames: T.normal })}
        />

        {/* S03: Research */}
        <TransitionSeries.Sequence durationInFrames={240}>
          <S03_Research />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={springTiming({ config: S.natural, durationInFrames: T.normal })}
        />

        {/* S04: Deck Updated */}
        <TransitionSeries.Sequence durationInFrames={240}>
          <S04_DeckUpdated />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={springTiming({ config: S.natural, durationInFrames: T.normal })}
        />

        {/* S05: Data Room */}
        <TransitionSeries.Sequence durationInFrames={180}>
          <S05_DataRoom />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={springTiming({ config: S.natural, durationInFrames: T.normal })}
        />

        {/* S06: Prep Doc */}
        <TransitionSeries.Sequence durationInFrames={210}>
          <S06_PrepDoc />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={springTiming({ config: S.natural, durationInFrames: T.normal })}
        />

        {/* S07: Slack Notify */}
        <TransitionSeries.Sequence durationInFrames={120}>
          <S07_SlackNotify />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={springTiming({ config: S.natural, durationInFrames: T.normal })}
        />

        {/* S08: Calendar Slots */}
        <TransitionSeries.Sequence durationInFrames={180}>
          <S08_CalendarSlots />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={springTiming({ config: S.natural, durationInFrames: T.normal })}
        />

        {/* S09: Reply Drafted */}
        <TransitionSeries.Sequence durationInFrames={150}>
          <S09_ReplyDrafted />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: T.fast })}
        />

        {/* S10: The Beat */}
        <TransitionSeries.Sequence durationInFrames={240}>
          <S10_TheBeat />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={springTiming({ config: S.natural, durationInFrames: T.normal })}
        />

        {/* S11: Close */}
        <TransitionSeries.Sequence durationInFrames={360}>
          <S11_Close />
        </TransitionSeries.Sequence>
      </TransitionSeries>

      {/* Global whoosh SFX for slide transitions */}
      {WHOOSH_FRAMES.map((f) => (
        <Sequence key={f} from={f}>
          <Audio src={SFX.whoosh} volume={0.25} />
        </Sequence>
      ))}
    </>
  );
};
```

- [ ] **Step 2: Create Root.tsx**

```tsx
import type React from "react";
import { Composition } from "remotion";
import "./fonts";
import { GaiaFounders } from "./GaiaFounders";
import { FPS, HEIGHT, WIDTH } from "./constants";

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="GaiaFounders"
      component={GaiaFounders}
      durationInFrames={2228}
      fps={FPS}
      width={WIDTH}
      height={HEIGHT}
    />
  );
};
```

- [ ] **Step 3: Verify studio starts**

```bash
cd apps/video2 && pnpm start
```

Expected: Remotion Studio opens at localhost:3000, shows `GaiaFounders` composition, 2228 frames, no TypeScript errors in console.

- [ ] **Step 4: Commit**

```bash
git add apps/video2/src/GaiaFounders.tsx apps/video2/src/Root.tsx
git commit -m "feat(video2): add main composition GaiaFounders and Root"
```

---

## Task 7: Polish pass

After all scenes render correctly in Studio, do a visual polish pass.

- [ ] **Step 1: Check each scene in Studio**

Scrub through every scene. Check:
- Text is readable at 1920x1080 (nothing smaller than 20px)
- Cards don't clip at screen edges (minimum 80px padding from screen edge)
- Spring animations feel snappy but not jarring
- SFX timing matches visual beats

- [ ] **Step 2: Fix any timing issues**

Common fixes:
- If a card's content animates before the card is fully visible: increase `enterDelay` by 5-10 frames
- If a scene feels rushed: increase `durationInFrames` by 30f and update `durationInFrames` in Root.tsx accordingly (recalculate WHOOSH_FRAMES too)
- If transitions feel too slow: reduce `durationInFrames` in `TransitionSeries.Transition` to `T.fast` (8)

- [ ] **Step 3: Render test**

```bash
cd apps/video2 && pnpm render
```

Expected: `out/founders.mp4` renders without errors. ~75 seconds long.

- [ ] **Step 4: Final commit**

```bash
git add apps/video2/
git commit -m "feat(video2): complete GAIA Founders video — 75s proactivity demo"
```

---

## Duration Recalculation Reference

If you change any scene duration, recalculate:

```
Total = sum(all scene durations) - sum(all transition durations)

Scene durations: 180 + 240 + 240 + 240 + 180 + 210 + 120 + 180 + 150 + 240 + 360 = 2340
Transition durations: 8 + 12 + 12 + 12 + 12 + 12 + 12 + 12 + 8 + 12 = 112
Total = 2340 - 112 = 2228

WHOOSH_FRAMES recalculation formula:
abs_start(N) = abs_start(N-1) + duration(N-1) - transition(N-1)
```

Update both `durationInFrames` in Root.tsx and `WHOOSH_FRAMES` in GaiaFounders.tsx after any duration change.
