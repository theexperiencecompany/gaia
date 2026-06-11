/*
 * Self-contained port of the GAIA landing "Reach GAIA from anywhere" iPhone
 * chat demos for Mintlify. Faithful copy of apps/web ChatDemo + IPhoneMockup +
 * useStaggeredMessages (WhatsApp / Telegram / Slack / Discord), with TypeScript
 * stripped, the `cn` util inlined, and asset paths repointed to /images/demos/.
 *
 * Mintlify only exposes the single exported component to the page; top-level
 * non-exported `const`s are NOT in scope at render time. So everything pure
 * (components + data) is defined inside the exported component, memoized once
 * with empty deps so the staggered re-renders never remount the tree.
 * Hooks (useState/useEffect/useRef/useMemo) are pre-injected.
 */

export const PlatformDemo = ({ platform }) => {
  const ui = useMemo(() => {
const cn = (...args) => args.filter(Boolean).join(" ");

const SF_STACK =
  '-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", Helvetica, Arial, sans-serif';
const SLACK_STACK =
  '"Slack-Lato", "Lato", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';
const DISCORD_STACK =
  '"gg sans", "Noto Sans", "Helvetica Neue", Helvetica, Arial, sans-serif';

const DEFAULT_AVATAR = "/images/demos/gaia-avatar.webp";
const AVATAR_ARYAN = "/images/demos/aryan-avatar.webp";

/* =========================================================================
 * Demo data (from BotsShowcaseSection PLATFORMS)
 * ========================================================================= */

const PLATFORMS = {
  whatsapp: {
    phone: { screenBackground: "#F6F6F6" },
    demo: {
      title: "GAIA",
      messages: [
        { from: "me", text: "what's on my plate today?", time: "9:14", status: "read" },
        { from: "them", text: "4 meetings back to back from 9.30, plus that investor draft you flagged yesterday", time: "9:14" },
        { from: "them", text: "want me to push standup to 11 so you have a coffee window?", time: "9:14" },
        { from: "me", text: "yes pls. also remind me to call mom at 8 🙏", time: "9:15", status: "read" },
        { from: "them", text: "done & done 🫡", time: "9:15" },
      ],
    },
  },
  telegram: {
    phone: { screenBackground: "#F6F6F6" },
    demo: {
      title: "GAIA",
      subtitle: "bot",
      messages: [
        { from: "me", text: "summarise my inbox", time: "14:02", status: "read" },
        { from: "them", text: "you've got 12 unread. 3 actually need you, the rest is noise", time: "14:03" },
        { from: "them", text: "drafting replies to the linear founder + the recruiter rn", time: "14:03" },
        { from: "me", text: "also book me to NYC next thursday", time: "14:04", status: "read" },
        { from: "them", text: "looking… delta has $189 out at 8am, lands 11ish. lock it in?", time: "14:04" },
      ],
    },
  },
  slack: {
    phone: {},
    demo: {
      title: "design",
      subtitle: "42 members",
      messages: [
        { author: "Aryan", avatar: AVATAR_ARYAN, text: "@GAIA standup post for design? pull from yesterday's threads", time: "10:24 AM" },
        { author: "GAIA", text: "pulled this from 4 open PRs and 6 figma comments since yesterday 🧵", time: "10:24 AM", reactions: [{ emoji: "🎉", count: 4 }, { emoji: "🔥", count: 2 }] },
        { author: "Aryan", avatar: AVATAR_ARYAN, text: "send it. also draft a reply to the PM thread in #product", time: "10:25 AM" },
        { author: "GAIA", text: "on it. DMing you the draft in 30s", time: "10:26 AM" },
      ],
    },
  },
  discord: {
    phone: { screenBackground: "#1E1F22", statusBarTone: "light" },
    demo: {
      title: "general",
      messages: [
        { author: "Aryan", avatar: AVATAR_ARYAN, authorColor: "#F47FFF", text: "@GAIA ship digest for the week?", time: "9:14 PM", reactions: [{ emoji: "👍", count: 3 }] },
        { author: "GAIA", authorColor: "#9CC3FF", text: "12 PRs merged, 4 features shipped, 2 incidents resolved 🚀", time: "9:14 PM" },
        { author: "Aryan", avatar: AVATAR_ARYAN, authorColor: "#F47FFF", text: "post it in #releases", time: "9:15 PM" },
        { author: "GAIA", authorColor: "#9CC3FF", text: "posted, ping me if anyone has follow-ups", time: "9:15 PM" },
      ],
    },
  },
};

/* =========================================================================
 * iPhone mockup (from IPhoneMockup.tsx)
 * ========================================================================= */

const isDarkColor = (color) => {
  if (!color) return false;
  const c = color.trim().toLowerCase();
  if (c === "#000" || c === "#000000" || c === "black") return true;
  const hex = c.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/);
  if (hex) {
    let h = hex[1];
    if (h.length === 3) h = h.split("").map((ch) => ch + ch).join("");
    const r = Number.parseInt(h.slice(0, 2), 16);
    const g = Number.parseInt(h.slice(2, 4), 16);
    const b = Number.parseInt(h.slice(4, 6), 16);
    return (r * 299 + g * 587 + b * 114) / 1000 < 128;
  }
  const rgb = c.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
  if (rgb) {
    const r = Number.parseInt(rgb[1], 10);
    const g = Number.parseInt(rgb[2], 10);
    const b = Number.parseInt(rgb[3], 10);
    return (r * 299 + g * 587 + b * 114) / 1000 < 128;
  }
  return false;
};

const SideButtons = () => (
  <>
    <span aria-hidden="true" className="absolute rounded-l-[2px]" style={{ left: -2, top: 105, width: 4, height: 32, background: "linear-gradient(90deg, #1a1d22 0%, #0a0c10 100%)" }} />
    <span aria-hidden="true" className="absolute rounded-l-[2px]" style={{ left: -2, top: 175, width: 4, height: 60, background: "linear-gradient(90deg, #1a1d22 0%, #0a0c10 100%)" }} />
    <span aria-hidden="true" className="absolute rounded-l-[2px]" style={{ left: -2, top: 250, width: 4, height: 60, background: "linear-gradient(90deg, #1a1d22 0%, #0a0c10 100%)" }} />
    <span aria-hidden="true" className="absolute rounded-r-[2px]" style={{ right: -2, top: 200, width: 4, height: 96, background: "linear-gradient(270deg, #1a1d22 0%, #0a0c10 100%)" }} />
  </>
);

const CellularIcon = ({ color }) => (
  <svg width="18" height="12" viewBox="185 211 139 88" fill={color} xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <path fillRule="evenodd" clipRule="evenodd" d="M323.798 219.308C323.798 214.759 320.366 211.072 316.133 211.072H308.468C304.235 211.072 300.803 214.759 300.803 219.308V290.692C300.803 295.241 304.235 298.928 308.468 298.928H316.133C320.366 298.928 323.798 295.241 323.798 290.692V219.308ZM270.378 228.643H278.042C282.276 228.643 285.707 232.419 285.707 237.077V290.494C285.707 295.152 282.276 298.928 278.042 298.928H270.378C266.144 298.928 262.713 295.152 262.713 290.494V237.077C262.713 232.419 266.144 228.643 270.378 228.643ZM239.25 247.679H231.585C227.352 247.679 223.921 251.503 223.921 256.22V290.387C223.921 295.104 227.352 298.928 231.585 298.928H239.25C243.483 298.928 246.915 295.104 246.915 290.387V256.22C246.915 251.503 243.483 247.679 239.25 247.679ZM201.16 265.25H193.495C189.262 265.25 185.83 269.02 185.83 273.67V290.509C185.83 295.159 189.262 298.928 193.495 298.928H201.16C205.393 298.928 208.825 295.159 208.825 290.509V273.67C208.825 269.02 205.393 265.25 201.16 265.25Z" />
  </svg>
);

const WifiIcon = ({ color }) => (
  <svg width="17" height="12" viewBox="370 207 132 95" fill={color} xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <path fillRule="evenodd" clipRule="evenodd" d="M435.69 228.428C453.562 228.429 470.75 235.054 483.703 246.936C484.678 247.853 486.237 247.842 487.198 246.91L496.521 237.831C497.008 237.359 497.279 236.718 497.275 236.052C497.271 235.386 496.992 234.75 496.5 234.282C462.504 202.847 408.871 202.847 374.875 234.282C374.382 234.749 374.103 235.386 374.098 236.052C374.094 236.718 374.364 237.358 374.851 237.831L384.177 246.91C385.137 247.843 386.697 247.855 387.672 246.936C400.626 235.054 417.816 228.428 435.69 228.428ZM435.666 258.754C445.419 258.753 454.825 262.431 462.054 269.071C463.032 270.014 464.573 269.993 465.526 269.025L474.776 259.545C475.263 259.048 475.533 258.373 475.526 257.672C475.519 256.971 475.236 256.302 474.739 255.815C452.723 235.042 418.628 235.042 396.612 255.815C396.114 256.302 395.831 256.971 395.824 257.673C395.818 258.374 396.089 259.048 396.577 259.545L405.824 269.025C406.778 269.993 408.318 270.014 409.296 269.071C416.521 262.435 425.919 258.758 435.666 258.754ZM453.806 278.828C453.82 279.585 453.553 280.315 453.07 280.845L437.429 298.484C436.97 299.003 436.345 299.294 435.693 299.294C435.041 299.294 434.415 299.003 433.957 298.484L418.313 280.845C417.83 280.314 417.564 279.584 417.578 278.827C417.593 278.07 417.886 277.353 418.389 276.846C428.378 267.404 443.008 267.404 452.997 276.846C453.499 277.354 453.792 278.071 453.806 278.828Z" />
  </svg>
);

const BatteryIcon = ({ color, percent = 80 }) => {
  const clamped = Math.max(0, Math.min(100, percent));
  return (
    <svg width="27" height="13" viewBox="547 204 197 101" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <rect x={550} y={207.2} width={174.4} height={95} rx={28.7432} ry={28.7432} fill="none" stroke={color} strokeOpacity="0.45" strokeWidth={5} />
      <rect x={729} y={243.9} width={11.5} height={21.6} rx={4} ry={4} fill={color} fillOpacity="0.45" />
      <rect x={559} y={216} width={156 * (clamped / 100)} height={78} rx={20} ry={20} fill={color} />
    </svg>
  );
};

const IPhoneMockup = ({
  time = "9:41",
  screenBackground,
  statusBarTone = "auto",
  hideStatusBar = false,
  homeIndicator = true,
  homeIndicatorTone = "auto",
  className,
  screenClassName,
  children,
}) => {
  const resolvedTone =
    statusBarTone === "auto" ? (isDarkColor(screenBackground) ? "light" : "dark") : statusBarTone;
  const resolvedHomeTone =
    homeIndicatorTone === "auto" ? (isDarkColor(screenBackground) ? "light" : "dark") : homeIndicatorTone;
  const fg = resolvedTone === "light" ? "#ffffff" : "#000000";

  return (
    <div
      className={cn(
        "relative inline-block rounded-[56px] bg-black p-[10px]",
        "shadow-[0_50px_100px_-20px_rgba(0,0,0,0.35),0_30px_60px_-30px_rgba(0,0,0,0.4),inset_0_0_0_1px_rgba(255,255,255,0.04)]",
        className,
      )}
      style={{ width: 390, maxWidth: "100%", aspectRatio: "390 / 815" }}
      aria-label="iPhone mockup"
      role="img"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 rounded-[56px]"
        style={{ background: "linear-gradient(135deg, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0) 30%, rgba(255,255,255,0) 70%, rgba(255,255,255,0.04) 100%)" }}
      />
      <SideButtons />
      <div
        className={cn("relative flex h-full w-full flex-col overflow-hidden rounded-[46px]", screenClassName)}
        style={{ background: screenBackground ?? "#ffffff" }}
      >
        <div
          aria-hidden="true"
          className="absolute top-[12px] left-1/2 z-20 -translate-x-1/2 rounded-full bg-black"
          style={{ width: 96, height: 28, boxShadow: "inset 0 0 0 0.5px rgba(255,255,255,0.06), 0 1px 2px rgba(0,0,0,0.3)" }}
        >
          <div
            className="absolute top-1/2 right-[9px] -translate-y-1/2 rounded-full"
            style={{ width: 8, height: 8, background: "radial-gradient(circle at 30% 30%, #2a2f3a 0%, #0b0e14 60%, #000 100%)", boxShadow: "inset 0 0 0 0.5px rgba(255,255,255,0.08)" }}
          >
            <span className="absolute top-[2px] left-[2px] rounded-full" style={{ width: 2, height: 2, background: "rgba(120,200,255,0.55)" }} />
          </div>
        </div>

        {!hideStatusBar && (
          <div className="relative z-10 flex shrink-0 items-center justify-between" style={{ height: 54, padding: "0 26px" }}>
            <span style={{ width: 80, fontSize: 17, lineHeight: 1, fontWeight: 600, letterSpacing: "-0.01em", color: fg, fontFamily: SF_STACK }}>
              {time}
            </span>
            <div className="flex items-center justify-end" style={{ width: 80, gap: 5, color: fg }}>
              <CellularIcon color={fg} />
              <WifiIcon color={fg} />
              <BatteryIcon color={fg} />
            </div>
          </div>
        )}

        <div className="relative z-0 flex min-h-0 flex-1 flex-col" style={{ paddingBottom: homeIndicator ? 22 : 0 }}>
          {children}
        </div>

        {homeIndicator && (
          <div
            aria-hidden="true"
            className="pointer-events-none absolute bottom-[8px] left-1/2 z-30 -translate-x-1/2 rounded-full"
            style={{ width: 134, height: 5, background: resolvedHomeTone === "light" ? "rgba(255,255,255,0.85)" : "rgba(0,0,0,0.85)" }}
          />
        )}
      </div>
    </div>
  );
};

/* =========================================================================
 * Shared curved bubble + helpers (from ChatDemo.tsx)
 * ========================================================================= */

const TAIL_THEM = "M 20 0 L 20 2 A 16 16 0 0 1 4 18 L 0 18 L 0 17.54 A 10 10 0 0 0 7 8 L 7 0 Z";
const TAIL_ME = "M 0 0 L 0 2 A 16 16 0 0 0 16 18 L 20 18 L 20 17.54 A 10 10 0 0 1 13 8 L 13 0 Z";

const CurvedBubble = ({ from, tail, background, tailColor, color, children, meta, maxWidthPct = 78, className }) => {
  const isMe = from === "me";
  return (
    <div className={cn("relative", className)} style={{ maxWidth: `${maxWidthPct}%` }}>
      <div
        style={{
          background, color, padding: "7px 13px 8px", borderRadius: 18, fontSize: 15.5,
          lineHeight: "20px", letterSpacing: "-0.01em", wordBreak: "break-word",
          position: "relative", whiteSpace: "pre-wrap",
        }}
      >
        {children}
        {meta && (
          <span style={{ display: "inline-block", verticalAlign: "bottom", marginLeft: 6, marginRight: -2, marginBottom: -1, fontSize: 11, lineHeight: "14px", letterSpacing: "-0.01em", whiteSpace: "nowrap", opacity: 0.95 }}>
            {meta}
          </span>
        )}
      </div>
      {tail && (
        <span
          aria-hidden="true"
          style={{ position: "absolute", bottom: 0, [isMe ? "right" : "left"]: -7, width: 20, height: 18, background: tailColor, clipPath: `path('${isMe ? TAIL_ME : TAIL_THEM}')` }}
        />
      )}
    </div>
  );
};

const curvedThread = (messages) => {
  const out = [];
  for (const m of messages) {
    const from = m.from ?? "them";
    const last = out[out.length - 1];
    if (last && last.from === from) last.items.push(m);
    else out.push({ from, items: [m] });
  }
  return out;
};

const groupByAuthor = (messages) => {
  const out = [];
  for (const m of messages) {
    const last = out[out.length - 1];
    if (last && last.author?.name === m.author) {
      last.items.push(m);
    } else {
      out.push({ author: { name: m.author ?? "Unknown", avatar: m.avatar, color: m.authorColor }, items: [m] });
    }
  }
  return out;
};

const TypingDots = ({ color }) => (
  <span aria-label="typing" style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "2px 0" }}>
    {[0, 1, 2].map((i) => (
      <span
        key={i}
        style={{ width: 6, height: 6, borderRadius: 9999, background: color, opacity: 0.6, animation: `chat-demo-typing 1.2s ${i * 0.15}s infinite ease-in-out`, display: "inline-block" }}
      />
    ))}
  </span>
);

const MicIcon = ({ size = 22 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M19 10V12C19 15.866 15.866 19 12 19M5 10V12C5 15.866 8.13401 19 12 19M12 19V22M8 22H16M12 15C10.3431 15 9 13.6569 9 12V5C9 3.34315 10.3431 2 12 2C13.6569 2 15 3.34315 15 5V12C15 13.6569 13.6569 15 12 15Z" />
  </svg>
);

const AttachmentIcon = ({ size = 22 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21.1525 10.8995L12.1369 19.9151C10.0866 21.9653 6.7625 21.9653 4.71225 19.9151C2.662 17.8648 2.662 14.5407 4.71225 12.4904L13.7279 3.47483C15.0947 2.108 17.3108 2.108 18.6776 3.47483C20.0444 4.84167 20.0444 7.05775 18.6776 8.42458L10.0156 17.0866C9.33213 17.7701 8.22409 17.7701 7.54068 17.0866C6.85726 16.4032 6.85726 15.2952 7.54068 14.6118L15.1421 7.01037" />
  </svg>
);

const CameraIcon = ({ size = 22 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M2 8.37722C2 8.0269 2 7.85174 2.01462 7.70421C2.1556 6.28127 3.28127 5.1556 4.70421 5.01462C4.85174 5 5.03636 5 5.40558 5C5.54785 5 5.61899 5 5.67939 4.99634C6.45061 4.94963 7.12595 4.46288 7.41414 3.746C7.43671 3.68986 7.45781 3.62657 7.5 3.5C7.54219 3.37343 7.56329 3.31014 7.58586 3.254C7.87405 2.53712 8.54939 2.05037 9.32061 2.00366C9.38101 2 9.44772 2 9.58114 2H14.4189C14.5523 2 14.619 2 14.6794 2.00366C15.4506 2.05037 16.126 2.53712 16.4141 3.254C16.4367 3.31014 16.4578 3.37343 16.5 3.5C16.5422 3.62657 16.5633 3.68986 16.5859 3.746C16.874 4.46288 17.5494 4.94963 18.3206 4.99634C18.381 5 18.4521 5 18.5944 5C18.9636 5 19.1483 5 19.2958 5.01462C20.7187 5.1556 21.8444 6.28127 21.9854 7.70421C22 7.85174 22 8.0269 22 8.37722V16.2C22 17.8802 22 18.7202 21.673 19.362C21.3854 19.9265 20.9265 20.3854 20.362 20.673C19.7202 21 18.8802 21 17.2 21H6.8C5.11984 21 4.27976 21 3.63803 20.673C3.07354 20.3854 2.6146 19.9265 2.32698 19.362C2 18.7202 2 17.8802 2 16.2V8.37722Z" />
    <path d="M12 16.5C14.2091 16.5 16 14.7091 16 12.5C16 10.2909 14.2091 8.5 12 8.5C9.79086 8.5 8 10.2909 8 12.5C8 14.7091 9.79086 16.5 12 16.5Z" />
  </svg>
);

const EmojiIcon = ({ size = 22 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M8 14C8 14 9.5 16 12 16C14.5 16 16 14 16 14M15 9H15.01M9 9H9.01M22 12C22 17.5228 17.5228 22 12 22C6.47715 22 2 17.5228 2 12C2 6.47715 6.47715 2 12 2C17.5228 2 22 6.47715 22 12ZM15.5 9C15.5 9.27614 15.2761 9.5 15 9.5C14.7239 9.5 14.5 9.27614 14.5 9C14.5 8.72386 14.7239 8.5 15 8.5C15.2761 8.5 15.5 8.72386 15.5 9ZM9.5 9C9.5 9.27614 9.27614 9.5 9 9.5C8.72386 9.5 8.5 9.27614 8.5 9C8.5 8.72386 8.72386 8.5 9 8.5C9.27614 8.5 9.5 8.72386 9.5 9Z" />
  </svg>
);

/* =========================================================================
 * Shared: CurvedMessageThread — used by WhatsApp and Telegram
 * ========================================================================= */

const CurvedMessageThread = ({ grouped, myBubble, theirBubble, textColor, metaColor, myMeta, TicksComponent }) => (
  <>
    {grouped.map((group, gi) => {
      const isMe = group.from === "me";
      return (
        <div key={gi} className={cn("flex flex-col", isMe ? "items-end" : "items-start")} style={{ gap: 2 }}>
          {group.items.map((m, i) => {
            const isLast = i === group.items.length - 1;
            const showMeta = !m.typing && (m.time || (isMe && m.status));
            const resolvedMetaColor = isMe && myMeta ? myMeta : metaColor;
            return (
              <CurvedBubble
                key={m.id ?? `${gi}-${i}`}
                className="chat-bubble-pop"
                from={group.from}
                tail={isLast}
                background={isMe ? myBubble : theirBubble}
                tailColor={isMe ? myBubble : theirBubble}
                color={textColor}
                meta={showMeta ? (
                  <span style={{ color: resolvedMetaColor, display: "inline-flex", alignItems: "center", gap: 3 }}>
                    {m.time ?? ""}
                    {isMe && m.status && TicksComponent && <TicksComponent status={m.status} color={resolvedMetaColor} />}
                  </span>
                ) : undefined}
              >
                {m.typing ? <TypingDots color={isMe && myMeta ? myMeta : metaColor} /> : m.text}
              </CurvedBubble>
            );
          })}
        </div>
      );
    })}
  </>
);

/* =========================================================================
 * Shared: ChatComposer — used by WhatsApp and Telegram
 * ========================================================================= */

const ChatComposer = ({ chromeBg, iconColor, borderColor, LeftIcon, leftLabel, buttonSize }) => (
  <div className="flex shrink-0 items-center gap-2 px-2 pt-2 pb-1.5" style={{ background: chromeBg }}>
    <button type="button" aria-label={leftLabel} className="flex cursor-pointer items-center justify-center rounded-full transition-colors hover:bg-black/[0.06]" style={{ width: buttonSize, height: buttonSize, color: iconColor }}>
      <LeftIcon />
    </button>
    <div className="flex flex-1 items-center justify-between gap-2" style={{ background: "#FFFFFF", border: `0.5px solid ${borderColor}`, borderRadius: 16, padding: "0 6px 0 17px", height: 32, color: "#8E8E93" }}>
      <span style={{ fontSize: 15, color: "#8E8E93", letterSpacing: "-0.01em" }}>Message</span>
      <button type="button" aria-label="Emoji" className="flex shrink-0 cursor-pointer items-center justify-center rounded-full transition-colors hover:bg-black/[0.06]" style={{ color: "#8E8E93", width: 22, height: 22 }}>
        <EmojiIcon size={18} />
      </button>
    </div>
    <button type="button" aria-label="Voice message" className="flex cursor-pointer items-center justify-center rounded-full transition-colors hover:bg-black/[0.06]" style={{ width: buttonSize, height: buttonSize, color: iconColor }}>
      <MicIcon />
    </button>
  </div>
);

/* =========================================================================
 * Shared: ReactionsBar — used by Slack and Discord
 * ========================================================================= */

const ReactionsBar = ({ items, spanStyle }) => {
  const reactions = items.flatMap((m) =>
    (m.reactions ?? []).map((r, ri) => (
      <span key={`${ri}-${r.emoji}`} className="inline-flex items-center gap-1" style={spanStyle(r)}>
        <span style={{ fontSize: 13 }}>{r.emoji}</span>
        {r.count}
      </span>
    )),
  );
  if (!reactions.length) return null;
  return <div className="mt-1 flex flex-wrap gap-1">{reactions}</div>;
};

/* =========================================================================
 * Shared: IOSChatHeader — iOS-style nav bar used by WhatsApp and Telegram
 * (back chevron on the left, custom center + right slots, hairline divider)
 * ========================================================================= */

const IOSChatHeader = ({ accent, chromeBg, backLabel, center, right }) => (
  <div className="flex shrink-0 flex-col" style={{ background: chromeBg }}>
    <div className="grid items-center" style={{ gridTemplateColumns: "1fr auto 1fr", padding: "6px 12px 8px", gap: 8 }}>
      <div className="flex items-center" style={{ color: accent }}>
        <svg width="12" height="20" viewBox="0 0 12 20" aria-hidden fill="none">
          <path d="M10 2 2 10l8 8" stroke={accent} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        {backLabel && <span style={{ fontSize: 17, marginLeft: 8, letterSpacing: "-0.01em" }}>{backLabel}</span>}
      </div>
      <div className="flex flex-col items-center" style={{ minWidth: 0 }}>{center}</div>
      <div className="flex items-center justify-end" style={{ color: accent }}>{right}</div>
    </div>
    <div style={{ height: 0.5, background: "rgba(60,60,67,0.18)" }} />
  </div>
);

/* =========================================================================
 * WhatsApp
 * ========================================================================= */

const WhatsAppTicks = ({ status }) => {
  const color = status === "read" ? "#3497F9" : "rgba(0,0,0,0.4)";
  if (status === "sent") {
    return (
      <svg width="14" height="11" viewBox="0 0 14 11" aria-hidden fill="none">
        <path d="M1 6l3.5 3.5L11 2" stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  return (
    <svg width="16" height="11" viewBox="0 0 18 14" aria-hidden fill="none">
      <path d="M1 7l3.2 3.5L11 3.5" stroke={color} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M6 7l3.2 3.5L17 3.5" stroke={color} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
};

const WhatsAppDemo = ({ messages, title, headerAvatar, showComposer, showHeader, className }) => {
  const bg = "#EFEFF4";
  const chromeBg = "#F6F6F6";
  const myBubble = "#DCF7C5";
  const theirBubble = "#FFFFFF";
  const textColor = "#060606";
  const metaColor = "rgba(0,0,0,0.45)";
  const accent = "#007AFF";
  const grouped = curvedThread(messages);

  return (
    <div className={cn("flex h-full flex-col", className)} style={{ background: bg, fontFamily: SF_STACK, color: textColor }}>
      {showHeader && (
        <IOSChatHeader
          accent={accent}
          chromeBg={chromeBg}
          center={
            <>
              <div className="overflow-hidden rounded-full" style={{ width: 32, height: 32 }}>
                <img src={headerAvatar} alt="" style={{ width: 32, height: 32, objectFit: "cover" }} />
              </div>
              <span style={{ fontSize: 10, marginTop: 2, color: textColor, letterSpacing: "-0.01em", maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {title ?? "GAIA"}
              </span>
            </>
          }
          right={
            <svg width="22" height="14" viewBox="0 0 22 14" aria-hidden fill="none">
              <rect x="0.5" y="0.5" width="15" height="13" rx="3" stroke={accent} />
              <path d="M16 4l5 -3v12l-5 -3z" fill={accent} stroke={accent} strokeWidth="0.5" strokeLinejoin="round" />
            </svg>
          }
        />
      )}

      <div
        className="flex flex-1 flex-col overflow-y-auto px-3 pb-3"
        style={{ scrollbarWidth: "none", gap: 8, backgroundColor: bg, backgroundImage: 'url("/images/demos/whatsapp-doodle.png")', backgroundRepeat: "repeat", backgroundSize: "404px auto", paddingTop: 8 }}
      >
        <CurvedMessageThread
          grouped={grouped}
          myBubble={myBubble}
          theirBubble={theirBubble}
          textColor={textColor}
          metaColor={metaColor}
          myMeta={null}
          TicksComponent={WhatsAppTicks}
        />
      </div>

      {showComposer && (
        <ChatComposer
          chromeBg={chromeBg}
          iconColor="#3C3C43"
          borderColor="#8E8E93"
          LeftIcon={CameraIcon}
          leftLabel="Camera"
          buttonSize={32}
        />
      )}
    </div>
  );
};

/* =========================================================================
 * Telegram
 * ========================================================================= */

const TelegramTicks = ({ status, color }) => {
  if (status === "sent") {
    return (
      <svg width="14" height="11" viewBox="0 0 14 11" aria-hidden fill="none">
        <path d="M1 6l3.5 3.5L11 2" stroke={color} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  return (
    <svg width="16" height="11" viewBox="0 0 16 11" aria-hidden fill="none">
      <path d="M0.5 6.5l3.5 3.5L10.5 2.5" stroke={color} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M4 6.5l3.5 3.5L13.5 2.5" stroke={color} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
};

const TelegramDemo = ({ messages, title, subtitle, headerAvatar, showComposer, showHeader, className }) => {
  const chromeBg = "#F6F6F6";
  const blueOverlay = "#2B78CD";
  const myBubble = "#E1FEC6";
  const theirBubble = "#FFFFFF";
  const textColor = "#060606";
  const metaColor = "#858E99";
  const myMeta = "#3EAA3C";
  const accent = "#037EE5";
  const grouped = curvedThread(messages);

  return (
    <div className={cn("flex h-full flex-col", className)} style={{ fontFamily: SF_STACK, color: textColor, background: chromeBg }}>
      {showHeader && (
        <IOSChatHeader
          accent={accent}
          chromeBg={chromeBg}
          backLabel="Back"
          center={
            <>
              <span style={{ fontSize: 17, fontWeight: 600, letterSpacing: "-0.01em", color: textColor, maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {title ?? "GAIA"}
              </span>
              <span style={{ fontSize: 12, color: metaColor, marginTop: 1 }}>{subtitle ?? "last seen recently"}</span>
            </>
          }
          right={
            <div className="overflow-hidden rounded-full" style={{ width: 32, height: 32 }}>
              <img src={headerAvatar} alt="" style={{ width: 32, height: 32, objectFit: "cover" }} />
            </div>
          }
        />
      )}

      <div
        className="flex flex-1 flex-col overflow-y-auto px-3 pb-3"
        style={{ scrollbarWidth: "none", gap: 8, backgroundColor: blueOverlay, backgroundImage: 'linear-gradient(rgba(43,120,205,0.5), rgba(43,120,205,0.5)), url("/images/demos/telegram-doodle.png")', backgroundSize: "auto, 480px auto", backgroundRepeat: "repeat", paddingTop: 8 }}
      >
        <CurvedMessageThread
          grouped={grouped}
          myBubble={myBubble}
          theirBubble={theirBubble}
          textColor={textColor}
          metaColor={metaColor}
          myMeta={myMeta}
          TicksComponent={TelegramTicks}
        />
      </div>

      {showComposer && (
        <ChatComposer
          chromeBg={chromeBg}
          iconColor={accent}
          borderColor="#D1D1D6"
          LeftIcon={AttachmentIcon}
          leftLabel="Attach"
          buttonSize={30}
        />
      )}
    </div>
  );
};

/* =========================================================================
 * Slack
 * ========================================================================= */

const renderSlackText = (text, dark) => {
  const parts = text.split(/(@\w+|#\w+|`[^`]+`)/g);
  return parts.map((p, i) => {
    if (/^@\w+/.test(p)) {
      return (
        <span key={i} style={{ background: dark ? "rgba(29,155,209,0.18)" : "#E8F5FA", color: dark ? "#1D9BD1" : "#1264A3", padding: "1px 3px", borderRadius: 3, fontWeight: 600 }}>
          {p}
        </span>
      );
    }
    if (/^#\w+/.test(p)) {
      return <span key={i} style={{ color: dark ? "#1D9BD1" : "#1264A3", fontWeight: 600 }}>{p}</span>;
    }
    if (/^`[^`]+`$/.test(p)) {
      return (
        <code key={i} style={{ background: dark ? "#222529" : "#F8F8F8", border: `1px solid ${dark ? "#3a3d42" : "#E8E8E8"}`, borderRadius: 3, padding: "0 4px", fontFamily: 'Menlo, Consolas, "Liberation Mono", monospace', fontSize: 12, color: "#E01E5A" }}>
          {p.slice(1, -1)}
        </code>
      );
    }
    return <span key={i}>{p}</span>;
  });
};

const SlackDemo = ({ messages, title, subtitle, showHeader, theme, className }) => {
  const isDark = theme === "dark";
  const bg = isDark ? "#1A1D21" : "#FFFFFF";
  const fg = isDark ? "#D1D2D3" : "#1D1C1D";
  const muted = isDark ? "#ABABAD" : "#616061";
  const headerBorder = isDark ? "#2F3236" : "#E8E8E8";
  const groups = groupByAuthor(messages);

  return (
    <div className={cn("flex h-full flex-col", className)} style={{ background: bg, color: fg, fontFamily: SLACK_STACK }}>
      {showHeader && (
        <div className="flex shrink-0 items-center justify-between border-b px-4" style={{ borderColor: headerBorder, height: 56 }}>
          <div className="flex flex-col leading-tight">
            <div className="flex items-center gap-1" style={{ fontWeight: 700, fontSize: 16 }}>
              <span style={{ color: muted, fontWeight: 400, marginRight: 2 }}>#</span>
              {title ?? "general"}
              <svg width="12" height="12" viewBox="0 0 20 20" aria-hidden style={{ marginLeft: 4 }}>
                <path d="M5 8l5 5 5-5" fill="none" stroke={fg} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <span style={{ fontSize: 12, color: muted }}>{subtitle ?? "Add a topic"}</span>
          </div>
          <div className="flex items-center gap-2" style={{ color: muted }}>
            <button type="button" aria-label="Activity" className="flex cursor-pointer items-center justify-center rounded-full transition-colors hover:bg-black/[0.06]" style={{ width: 32, height: 32 }}>
              <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden fill="currentColor">
                <path d="M12 21a9 9 0 1 1 0-18 9 9 0 0 1 0 18Zm0-2a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm-1-10h2v4h3v2h-5V9Z" />
              </svg>
            </button>
            <button type="button" aria-label="Search" className="flex cursor-pointer items-center justify-center rounded-full transition-colors hover:bg-black/[0.06]" style={{ width: 32, height: 32 }}>
              <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="11" cy="11" r="7" />
                <path d="m20 20-4-4" strokeLinecap="round" />
              </svg>
            </button>
          </div>
        </div>
      )}
      <div className="flex flex-1 flex-col overflow-y-auto py-3" style={{ scrollbarWidth: "none", gap: 12 }}>
        {groups.map((g, gi) => (
          <div key={gi} className="chat-bubble-pop flex items-start gap-2" style={{ padding: "0 16px" }}>
            <div className="shrink-0 overflow-hidden" style={{ width: 36, height: 36, borderRadius: 6, marginTop: 4 }}>
              <img src={g.author?.avatar ?? DEFAULT_AVATAR} alt="" style={{ width: 36, height: 36, objectFit: "cover" }} />
            </div>
            <div className="flex min-w-0 flex-1 flex-col">
              <div className="flex items-baseline gap-2">
                <span style={{ fontWeight: 900, fontSize: 15, color: fg, letterSpacing: "-0.01em" }}>{g.author?.name ?? "Unknown"}</span>
                <span style={{ fontSize: 12, color: muted }}>{g.items[0].time ?? ""}</span>
              </div>
              <div className="flex flex-col" style={{ gap: 2 }}>
                {g.items.map((m, i) => (
                  <div key={m.id ?? `${gi}-${i}`} style={{ fontSize: 15, lineHeight: "22px", color: fg, wordBreak: "break-word", whiteSpace: "pre-wrap" }}>
                    {m.typing ? <TypingDots color={muted} /> : renderSlackText(m.text ?? "", isDark)}
                  </div>
                ))}
              </div>
              {g.items.some((m) => m.reactions?.length) && (
                <ReactionsBar
                  items={g.items}
                  spanStyle={(r) => ({ padding: "1px 7px", borderRadius: 12, border: `1px solid ${isDark ? "#3a3d42" : "#DDDDDD"}`, background: isDark ? "#26282C" : "#F1F4F7", fontSize: 12, fontWeight: 700, color: isDark ? "#9DB0CA" : "#1264A3" })}
                />
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

/* =========================================================================
 * Discord
 * ========================================================================= */

const renderDiscordText = (text) => {
  const parts = text.split(/(@\w+|#\w+|`[^`]+`|:\w+:)/g);
  return parts.map((p, i) => {
    if (/^@\w+/.test(p)) {
      return <span key={i} style={{ background: "rgba(88,101,242,0.3)", color: "#C9CDFB", padding: "0 2px", borderRadius: 3, fontWeight: 500 }}>{p}</span>;
    }
    if (/^#\w+/.test(p)) {
      return <span key={i} style={{ color: "#00A8FC", fontWeight: 500 }}>{p}</span>;
    }
    if (/^`[^`]+`$/.test(p)) {
      return <code key={i} style={{ background: "#2B2D31", borderRadius: 3, padding: "0 4px", fontFamily: '"Menlo", Consolas, monospace', fontSize: 13.6 }}>{p.slice(1, -1)}</code>;
    }
    return <span key={i}>{p}</span>;
  });
};

const DiscordCircleButton = ({ bg, fg, label, children }) => (
  <button type="button" aria-label={label} className="flex shrink-0 cursor-pointer items-center justify-center rounded-full transition-[filter,opacity] duration-150 hover:brightness-125 active:brightness-90" style={{ width: 36, height: 36, background: bg, color: fg }}>
    {children}
  </button>
);

const DiscordDemo = ({ messages, title, showComposer, showHeader, className }) => {
  const bg = "#1E1F22";
  const fg = "#DBDEE1";
  const muted = "#949BA4";
  const iconBg = "#2B2D31";
  const groups = groupByAuthor(messages);

  return (
    <div className={cn("flex h-full flex-col", className)} style={{ background: bg, color: fg, fontFamily: DISCORD_STACK }}>
      {showHeader && (
        <div className="flex shrink-0 items-center gap-2 px-3" style={{ background: bg, height: 48, borderBottom: "1px solid rgba(0,0,0,0.4)", zIndex: 2 }}>
          <button type="button" aria-label="Back" className="flex cursor-pointer items-center justify-center rounded-full transition-colors hover:bg-white/[0.06]" style={{ width: 28, height: 28, color: fg }}>
            <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden fill="none">
              <path d="M14 6l-6 6 6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
          <span style={{ fontSize: 18, color: muted, marginLeft: 2 }}>#</span>
          <span style={{ fontSize: 17, fontWeight: 700, color: "#FFFFFF", letterSpacing: "-0.01em" }}>{title ?? "general"}</span>
          <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden fill="none" style={{ marginLeft: 2, color: muted }}>
            <path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <div className="flex flex-1" />
          <button type="button" aria-label="Search" className="flex cursor-pointer items-center justify-center rounded-full transition-[filter] duration-150 hover:brightness-125 active:brightness-90" style={{ width: 32, height: 32, background: iconBg, color: muted }}>
            <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden fill="none">
              <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2" />
              <path d="m20 20-4-4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      )}
      <div className="flex flex-1 flex-col overflow-y-auto py-3" style={{ scrollbarWidth: "none", gap: 18 }}>
        {groups.map((g, gi) => (
          <div key={gi} className="chat-bubble-pop flex gap-3" style={{ padding: "0 12px" }}>
            <div className="shrink-0 overflow-hidden rounded-full" style={{ width: 40, height: 40 }}>
              <img src={g.author?.avatar ?? DEFAULT_AVATAR} alt="" style={{ width: 40, height: 40, objectFit: "cover", transform: "scale(1.05)" }} />
            </div>
            <div className="flex min-w-0 flex-1 flex-col">
              <div className="flex items-baseline gap-2">
                <span style={{ fontWeight: 600, fontSize: 15, color: g.author?.color ?? "#FFFFFF" }}>{g.author?.name ?? "Unknown"}</span>
                <span style={{ fontSize: 12, color: muted }}>Today at {g.items[0].time ?? ""}</span>
              </div>
              <div className="flex flex-col" style={{ gap: 4 }}>
                {g.items.map((m, i) => (
                  <div key={m.id ?? `${gi}-${i}`} style={{ fontSize: 15, lineHeight: "1.375", color: fg, wordBreak: "break-word", whiteSpace: "pre-wrap" }}>
                    {m.typing ? <TypingDots color={muted} /> : renderDiscordText(m.text ?? "")}
                  </div>
                ))}
              </div>
              {g.items.some((m) => m.reactions?.length) && (
                <ReactionsBar
                  items={g.items}
                  spanStyle={(r) => ({ padding: "2px 7px", borderRadius: 8, border: "1px solid rgba(88,101,242,0.3)", background: "rgba(88,101,242,0.15)", fontSize: 13, fontWeight: 600, color: "#A8B6FF" })}
                />
              )}
            </div>
          </div>
        ))}
      </div>
      {showComposer && (
        <div className="flex shrink-0 items-center gap-2 px-3 pt-2 pb-2" style={{ background: bg }}>
          <DiscordCircleButton bg={iconBg} fg={fg} label="Add">
            <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden fill="none">
              <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
            </svg>
          </DiscordCircleButton>
          <div className="flex flex-1 items-center" style={{ background: iconBg, borderRadius: 20, padding: "0 12px", height: 36 }}>
            <span style={{ fontSize: 15, color: "#949BA4" }}>Message</span>
          </div>
          <DiscordCircleButton bg={iconBg} fg={fg} label="Voice">
            <MicIcon size={18} />
          </DiscordCircleButton>
        </div>
      )}
    </div>
  );
};

/* =========================================================================
 * Dispatcher
 * ========================================================================= */

  const ChatDemo = ({ platform, messages, title, subtitle }) => {
    if (platform === "whatsapp") {
      return <WhatsAppDemo messages={messages} title={title} subtitle={subtitle} headerAvatar={DEFAULT_AVATAR} showComposer showHeader />;
    }
    if (platform === "telegram") {
      return <TelegramDemo messages={messages} title={title} subtitle={subtitle} headerAvatar={DEFAULT_AVATAR} showComposer showHeader />;
    }
    if (platform === "slack") {
      return <SlackDemo messages={messages} title={title} subtitle={subtitle} showComposer showHeader theme="light" />;
    }
    return <DiscordDemo messages={messages} title={title} subtitle={subtitle} showComposer showHeader />;
  };

    return { IPhoneMockup, ChatDemo, PLATFORMS };
  }, []);

  /* ----- hooks (must stay at the component's top level) ----- */
  const TYPING_DELAY_MS = 450;
  const TYPING_DURATION_MS = 850;

  const config = ui.PLATFORMS[platform] ?? ui.PLATFORMS.whatsapp;
  const baseMessages = config.demo.messages;

  const wrapperRef = useRef(null);
  const [inView, setInView] = useState(false);
  const [visibleCount, setVisibleCount] = useState(1);
  const [showTyping, setShowTyping] = useState(false);

  useEffect(() => {
    const node = wrapperRef.current;
    if (!node) return;
    if (typeof IntersectionObserver === "undefined") {
      setInView(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          setInView(true);
          observer.disconnect();
        }
      },
      { threshold: 0.3 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    setVisibleCount(1);
    setShowTyping(false);
    if (!inView) return;
    if (baseMessages.length <= 1) return;

    const timers = [];
    let elapsed = 0;
    for (let i = 1; i < baseMessages.length; i++) {
      elapsed += TYPING_DELAY_MS;
      timers.push(setTimeout(() => setShowTyping(true), elapsed));
      elapsed += TYPING_DURATION_MS;
      timers.push(
        setTimeout(() => {
          setShowTyping(false);
          setVisibleCount((c) => c + 1);
        }, elapsed),
      );
    }
    return () => {
      for (const t of timers) clearTimeout(t);
    };
  }, [inView, baseMessages]);

  const messages = useMemo(() => {
    const real = baseMessages.slice(0, visibleCount).map((m, i) => ({ ...m, id: m.id ?? `msg-${i}` }));
    if (!showTyping || visibleCount >= baseMessages.length) return real;
    const next = baseMessages[visibleCount];
    return [
      ...real,
      { id: `typing-${visibleCount}`, from: next.from, author: next.author, avatar: next.avatar, authorColor: next.authorColor, typing: true },
    ];
  }, [baseMessages, visibleCount, showTyping]);

  const { IPhoneMockup, ChatDemo } = ui;

  return (
    <div ref={wrapperRef} className="not-prose my-6 flex justify-center">
      <style>{`@keyframes chat-demo-typing { 0%, 60%, 100% { transform: translateY(0); opacity: 0.6; } 30% { transform: translateY(-3px); opacity: 1; } }`}</style>
      <IPhoneMockup screenBackground={config.phone.screenBackground} statusBarTone={config.phone.statusBarTone}>
        <div className="flex h-full flex-col">
          <ChatDemo platform={platform} title={config.demo.title} subtitle={config.demo.subtitle} messages={messages} />
        </div>
      </IPhoneMockup>
    </div>
  );
};
