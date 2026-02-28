import {
  Clock01Icon,
  Cursor01Icon,
  FlashIcon,
} from "@theexperiencecompany/gaia-icons/solid-rounded";
import React from "react";
import {
  AbsoluteFill,
  Img,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { COLORS, FONTS } from "../constants";

// ─── Trigger data ─────────────────────────────────────────────────────────────

const SCHEDULE_TRIGGERS = [
  { label: "Every day at 8:00 AM", detail: "Daily" },
  { label: "Every Monday at 9:00 AM", detail: "Weekly" },
  { label: "Every hour", detail: "Hourly" },
  { label: "1st of every month", detail: "Monthly" },
  { label: "Custom cron expression", detail: "Advanced" },
];

const EVENT_TRIGGERS = [
  { icon: "images/icons/gmail.svg", label: "On new email", integration: "Gmail", invert: false },
  { icon: "images/icons/github.svg", label: "On new pull request", integration: "GitHub", invert: true },
  { icon: "images/icons/slack.svg", label: "On new message", integration: "Slack", invert: false },
  { icon: "images/icons/googlecalendar.webp", label: "On calendar event", integration: "Google Calendar", invert: false },
  { icon: "images/icons/notion.webp", label: "On new page", integration: "Notion", invert: false },
  { icon: "images/icons/linear.svg", label: "On new issue", integration: "Linear", invert: false },
];

const MANUAL_ITEMS = [
  { label: "Run from the dashboard" },
  { label: "Trigger from chat" },
  { label: "Call via API or webhook" },
];

// ─── Tabs ──────────────────────────────────────────────────────────────────────

const TABS = [
  { key: "schedule", label: "Schedule", icon: <Clock01Icon size={22} />, color: "#60a5fa" },
  { key: "trigger", label: "Event Trigger", icon: <FlashIcon size={22} />, color: "#f59e0b" },
  { key: "manual", label: "Manual", icon: <Cursor01Icon size={22} />, color: "#a855f7" },
];

// ─── Row components ────────────────────────────────────────────────────────────

const ScheduleRow: React.FC<{ item: (typeof SCHEDULE_TRIGGERS)[number]; delay: number }> = ({ item, delay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: { damping: 200 } });
  const opacity = interpolate(p, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const y = interpolate(p, [0, 1], [14, 0]);

  return (
    <div style={{ opacity, transform: `translateY(${y}px)`, display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 20px", borderTop: "1px solid rgba(255,255,255,0.05)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#60a5fa", flexShrink: 0 }} />
        <span style={{ fontFamily: FONTS.body, fontSize: 22, color: "#e4e4e7", fontWeight: 400 }}>{item.label}</span>
      </div>
      <span style={{ fontFamily: FONTS.body, fontSize: 18, background: "rgba(96,165,250,0.1)", padding: "3px 10px", borderRadius: 6, color: "#60a5fa" }}>{item.detail}</span>
    </div>
  );
};

const EventRow: React.FC<{ item: (typeof EVENT_TRIGGERS)[number]; delay: number }> = ({ item, delay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: { damping: 200 } });
  const opacity = interpolate(p, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const y = interpolate(p, [0, 1], [14, 0]);

  return (
    <div style={{ opacity, transform: `translateY(${y}px)`, display: "flex", alignItems: "center", gap: 14, padding: "12px 20px", borderTop: "1px solid rgba(255,255,255,0.05)" }}>
      <div style={{ width: 36, height: 36, borderRadius: 8, background: "#27272a", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, overflow: "hidden" }}>
        <Img src={staticFile(item.icon)} style={{ width: 22, height: 22, objectFit: "contain", filter: item.invert ? "invert(1)" : undefined }} />
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ fontFamily: FONTS.body, fontSize: 22, color: "#e4e4e7", fontWeight: 400 }}>{item.label}</div>
        <div style={{ fontFamily: FONTS.body, fontSize: 17, color: "#52525b", marginTop: 1 }}>{item.integration}</div>
      </div>
      <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#f59e0b", flexShrink: 0 }} />
    </div>
  );
};

const ManualRow: React.FC<{ item: (typeof MANUAL_ITEMS)[number]; delay: number }> = ({ item, delay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: { damping: 200 } });
  const opacity = interpolate(p, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const y = interpolate(p, [0, 1], [14, 0]);

  return (
    <div style={{ opacity, transform: `translateY(${y}px)`, display: "flex", alignItems: "center", gap: 12, padding: "12px 20px", borderTop: "1px solid rgba(255,255,255,0.05)" }}>
      <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#a855f7", flexShrink: 0 }} />
      <span style={{ fontFamily: FONTS.body, fontSize: 22, color: "#e4e4e7", fontWeight: 400 }}>{item.label}</span>
    </div>
  );
};

// ─── Column card ───────────────────────────────────────────────────────────────

const TriggerCard: React.FC<{
  tab: (typeof TABS)[number];
  delay: number;
  children: React.ReactNode;
  rowCount: number;
}> = ({ tab, delay, children, rowCount }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: { damping: 20, stiffness: 100 } });
  const opacity = interpolate(p, [0, 0.15], [0, 1], { extrapolateRight: "clamp" });
  const y = interpolate(p, [0, 1], [24, 0]);

  return (
    <div style={{
      flex: 1,
      background: "#18181b",
      borderRadius: 20,
      overflow: "hidden",
      opacity,
      transform: `translateY(${y}px)`,
      display: "flex",
      flexDirection: "column",
    }}>
      {/* Card header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "20px 20px 16px" }}>
        <div style={{ width: 38, height: 38, borderRadius: 10, background: `${tab.color}18`, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
          <span style={{ color: tab.color, display: "flex", alignItems: "center" }}>{tab.icon}</span>
        </div>
        <div>
          <div style={{ fontFamily: FONTS.body, fontSize: 24, fontWeight: 600, color: "#f4f4f5" }}>{tab.label}</div>
          <div style={{ fontFamily: FONTS.body, fontSize: 17, color: "#52525b", marginTop: 2 }}>
            {rowCount} option{rowCount !== 1 ? "s" : ""}
          </div>
        </div>
      </div>
      {/* Divider */}
      <div style={{ height: 1, background: "rgba(255,255,255,0.06)" }} />
      {/* Rows */}
      <div style={{ flex: 1 }}>{children}</div>
    </div>
  );
};

// ─── Scene ─────────────────────────────────────────────────────────────────────

export const S22b_WorkflowTriggers: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Top headline
  const headlineP = spring({ frame, fps, config: { damping: 200 } });
  const headlineOpacity = interpolate(headlineP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const headlineY = interpolate(headlineP, [0, 1], [-20, 0]);

  // Sub-label
  const subP = spring({ frame: frame - 8, fps, config: { damping: 200 } });
  const subOpacity = interpolate(subP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  // "When to Run" modal label
  const labelP = spring({ frame: frame - 16, fps, config: { damping: 200 } });
  const labelOpacity = interpolate(labelP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ background: COLORS.bgLight, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "0 80px" }}>

      {/* Headline */}
      <div style={{ width: "100%", maxWidth: 1760, marginBottom: 40 }}>
        <div style={{
          fontFamily: FONTS.display,
          textTransform: "uppercase" as const,
          fontSize: 88,
          fontWeight: 700,
          color: COLORS.textDark,
          lineHeight: 1.0,
          opacity: headlineOpacity,
          transform: `translateY(${headlineY}px)`,
        }}>
          Runs on any schedule.
        </div>
        <div style={{
          fontFamily: FONTS.body,
          fontSize: 32,
          color: "#52525b",
          marginTop: 12,
          opacity: subOpacity,
        }}>
          Schedule by time, react to integration events, or trigger on demand — your workflow, your rules.
        </div>
      </div>

      {/* "When to Run" label + three columns */}
      <div style={{ width: "100%", maxWidth: 1760, display: "flex", alignItems: "flex-start", gap: 20 }}>

        {/* Label column */}
        <div style={{ paddingTop: 28, minWidth: 180, opacity: labelOpacity }}>
          <div style={{ fontFamily: FONTS.body, fontSize: 20, fontWeight: 500, color: "#3f3f46", textTransform: "uppercase" as const, letterSpacing: 1.5 }}>
            When to Run
          </div>
        </div>

        {/* Schedule card */}
        <TriggerCard tab={TABS[0]} delay={20} rowCount={SCHEDULE_TRIGGERS.length}>
          {SCHEDULE_TRIGGERS.map((item, i) => (
            <ScheduleRow key={i} item={item} delay={28 + i * 7} />
          ))}
        </TriggerCard>

        {/* Event Trigger card */}
        <TriggerCard tab={TABS[1]} delay={32} rowCount={EVENT_TRIGGERS.length}>
          {EVENT_TRIGGERS.map((item, i) => (
            <EventRow key={i} item={item} delay={40 + i * 7} />
          ))}
        </TriggerCard>

        {/* Manual card */}
        <TriggerCard tab={TABS[2]} delay={44} rowCount={MANUAL_ITEMS.length}>
          {MANUAL_ITEMS.map((item, i) => (
            <ManualRow key={i} item={item} delay={52 + i * 8} />
          ))}
        </TriggerCard>
      </div>
    </AbsoluteFill>
  );
};
