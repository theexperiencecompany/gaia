import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate, Img, staticFile } from "remotion";
import { COLORS, FONTS } from "../constants";
import {
  Mail01Icon,
  Calendar01Icon,
  Task01Icon,
  WorkflowSquare01Icon,
} from "@theexperiencecompany/gaia-icons/solid-rounded";

const DUMMY_EMAILS = [
  { from: "Sarah Chen", subject: "Q4 Report — needs your review", time: "2h ago" },
  { from: "David Kim", subject: "Vendor invoice due Friday", time: "3h ago" },
  { from: "GitHub", subject: "New PR: fix/auth-token-refresh", time: "5h ago" },
  { from: "Notion", subject: "Weekly digest: 12 updates", time: "6h ago" },
];

const DUMMY_EVENTS = [
  { title: "Daily Standup", time: "10:00 – 10:15 AM", color: COLORS.primary },
  { title: "Design Review", time: "2:00 – 3:00 PM", color: "#a855f7" },
  { title: "1:1 with Manager", time: "4:00 – 4:30 PM", color: "#22c55e" },
];

const DUMMY_TODOS = [
  { title: "Reply to Sarah's Q4 report", priority: "high", priorityColor: "#ef4444" },
  { title: "Follow up on vendor invoice", priority: "high", priorityColor: "#ef4444" },
  { title: "Review PR comments", priority: "medium", priorityColor: "#f59e0b" },
  { title: "Update project roadmap", priority: "low", priorityColor: "#3b82f6" },
];

const DUMMY_WORKFLOWS = [
  { title: "Daily Morning Briefing", icons: ["images/icons/gmail.svg", "images/icons/googlecalendar.webp", "images/icons/slack.svg"], runs: 127 },
  { title: "GitHub PR Tracker", icons: ["images/icons/github.svg", "images/icons/slack.svg", "images/icons/notion.webp"], runs: 43 },
];

interface DashCardProps {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  delay: number;
}

const DashCard: React.FC<DashCardProps> = ({ title, icon, children, delay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const progress = spring({ frame: frame - delay, fps, config: { damping: 22, stiffness: 100 } });
  const opacity = interpolate(progress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const y = interpolate(progress, [0, 1], [20, 0]);

  return (
    <div style={{
      background: "#1e1e21",
      borderRadius: 24,
      overflow: "hidden",
      transform: `translateY(${y}px)`,
      opacity,
      display: "flex",
      flexDirection: "column",
    }}>
      {/* Card header */}
      <div style={{
        display: "flex", alignItems: "center", gap: 12,
        padding: "24px 32px 20px",
      }}>
        {icon}
        <span style={{ color: COLORS.zinc400, fontFamily: FONTS.body, fontWeight: 500, fontSize: 22 }}>
          {title}
        </span>
      </div>
      {/* Card content */}
      <div style={{ flex: 1 }}>
        {children}
      </div>
    </div>
  );
};

export const S28_DashboardReveal: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Greeting entrance
  const greetProgress = spring({ frame, fps, config: { damping: 22 } });
  const greetOpacity = interpolate(greetProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const greetY = interpolate(greetProgress, [0, 1], [20, 0]);

  return (
    <AbsoluteFill style={{ background: COLORS.bgLight, overflowY: "hidden" }}>
      <div style={{
        position: "absolute", inset: 0,
        display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        padding: "24px 40px",
        gap: 36,
      }}>
        {/* Greeting */}
        <div style={{
          width: "100%", maxWidth: 1400,
          transform: `translateY(${greetY}px)`,
          opacity: greetOpacity,
        }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 8 }}>
            <span style={{ fontFamily: FONTS.body, fontSize: 64, fontWeight: 500, color: COLORS.zinc600 }}>
              Good morning,
            </span>
            <span style={{ fontFamily: FONTS.body, fontSize: 64, fontWeight: 500, color: COLORS.textDark }}>
              Aryan :)
            </span>
          </div>
          <div style={{ fontFamily: FONTS.body, fontSize: 36, color: COLORS.zinc600, display: "flex", gap: 6, flexWrap: "wrap" }}>
            <span>You have</span>
            <span style={{ color: COLORS.textDark, fontWeight: 600 }}>3 meetings,</span>
            <span style={{ color: COLORS.textDark, fontWeight: 600 }}>4 tasks due,</span>
            <span style={{ color: COLORS.textDark, fontWeight: 600 }}>5 unread emails,</span>
            <span>and</span>
            <span style={{ color: COLORS.textDark, fontWeight: 600 }}>2 workflows</span>
            <span>today.</span>
          </div>
        </div>

        {/* 2x2 Dashboard cards */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 28,
          width: "100%",
          maxWidth: 1400,
        }}>
          {/* Emails Card */}
          <DashCard
            title="Unread Emails"
            icon={<Mail01Icon size={26} color={COLORS.zinc400} />}
            delay={10}
          >
            {DUMMY_EMAILS.map((email, i) => (
              <div key={i} style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                padding: "16px 28px",
                borderTop: i === 0 ? "none" : "1px solid rgba(255,255,255,0.04)",
              }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ color: "#e4e4e7", fontFamily: FONTS.body, fontSize: 28, fontWeight: 600, marginBottom: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {email.from}
                  </div>
                  <div style={{ color: COLORS.zinc400, fontFamily: FONTS.body, fontSize: 22, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {email.subject}
                  </div>
                </div>
                <span style={{ color: COLORS.zinc400, fontFamily: FONTS.body, fontSize: 22, flexShrink: 0, marginLeft: 16 }}>
                  {email.time}
                </span>
              </div>
            ))}
          </DashCard>

          {/* Events Card */}
          <DashCard
            title="Upcoming Events"
            icon={<Calendar01Icon size={26} color={COLORS.zinc400} />}
            delay={22}
          >
            {DUMMY_EVENTS.map((event, i) => (
              <div key={i} style={{
                display: "flex", alignItems: "center", gap: 16,
                padding: "18px 28px",
                borderTop: i === 0 ? "none" : "1px solid rgba(255,255,255,0.04)",
              }}>
                <div style={{ width: 4, height: 52, borderRadius: 2, background: event.color, flexShrink: 0 }} />
                <div>
                  <div style={{ color: "white", fontFamily: FONTS.body, fontSize: 28, fontWeight: 600 }}>
                    {event.title}
                  </div>
                  <div style={{ color: COLORS.zinc400, fontFamily: FONTS.body, fontSize: 22, marginTop: 4 }}>
                    {event.time}
                  </div>
                </div>
              </div>
            ))}
          </DashCard>

          {/* Todos Card */}
          <DashCard
            title="Inbox Todos"
            icon={<Task01Icon size={26} color={COLORS.zinc400} />}
            delay={34}
          >
            {DUMMY_TODOS.map((todo, i) => (
              <div key={i} style={{
                display: "flex", alignItems: "center", gap: 16,
                padding: "16px 28px",
                borderTop: i === 0 ? "none" : "1px solid rgba(255,255,255,0.04)",
              }}>
                <div style={{
                  width: 18, height: 18, borderRadius: "50%",
                  border: `2.5px dashed ${todo.priorityColor}`,
                  flexShrink: 0,
                }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ color: "white", fontFamily: FONTS.body, fontSize: 28, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {todo.title}
                  </div>
                </div>
                <div style={{
                  padding: "4px 12px", borderRadius: 6,
                  background: todo.priorityColor + "22",
                  color: todo.priorityColor,
                  fontSize: 18, fontFamily: FONTS.body, fontWeight: 600,
                  textTransform: "capitalize",
                }}>
                  {todo.priority}
                </div>
              </div>
            ))}
          </DashCard>

          {/* Workflows Card */}
          <DashCard
            title="Workflows"
            icon={<WorkflowSquare01Icon size={26} color={COLORS.zinc400} />}
            delay={46}
          >
            {DUMMY_WORKFLOWS.map((wf, i) => (
              <div key={i} style={{
                display: "flex", alignItems: "center", gap: 18,
                padding: "20px 28px",
                borderTop: i === 0 ? "none" : "1px solid rgba(255,255,255,0.04)",
              }}>
                {/* Stacked icons */}
                <div style={{ display: "flex", alignItems: "center" }}>
                  {wf.icons.map((icon, j) => (
                    <div key={j} style={{
                      width: 40, height: 40, borderRadius: 10,
                      background: "#27272a",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      marginLeft: j > 0 ? -10 : 0,
                      zIndex: wf.icons.length - j,
                      position: "relative", overflow: "hidden",
                      border: "2px solid #1e1e21",
                    }}>
                      <Img src={staticFile(icon)} style={{ width: 26, height: 26, objectFit: "contain" }} />
                    </div>
                  ))}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ color: "white", fontFamily: FONTS.body, fontSize: 28, fontWeight: 600 }}>
                    {wf.title}
                  </div>
                  <div style={{ color: COLORS.zinc400, fontFamily: FONTS.body, fontSize: 22, marginTop: 4 }}>
                    {wf.runs} runs
                  </div>
                </div>
                <div style={{
                  padding: "8px 20px", borderRadius: 10,
                  background: COLORS.primary + "22",
                  color: COLORS.primary,
                  fontSize: 20, fontFamily: FONTS.body, fontWeight: 700,
                }}>
                  Run
                </div>
              </div>
            ))}
          </DashCard>
        </div>
      </div>
    </AbsoluteFill>
  );
};
