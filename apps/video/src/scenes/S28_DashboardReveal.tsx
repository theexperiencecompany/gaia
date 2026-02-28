import {
  CalendarUpload01Icon,
  CheckmarkCircle02Icon,
  InboxUnreadIcon,
  WorkflowSquare05Icon,
} from "@theexperiencecompany/gaia-icons/solid-rounded";
import type React from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { COLORS, FONTS } from "../constants";
import { SFX } from "../sfx";

const DUMMY_EMAILS = [
  {
    from: "Sarah Chen",
    subject: "Q4 Report — needs your review",
    time: "2h ago",
  },
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
  {
    title: "Reply to Sarah's Q4 report",
    priority: "high",
    priorityColor: "#ef4444",
  },
  {
    title: "Follow up on vendor invoice",
    priority: "high",
    priorityColor: "#ef4444",
  },
  { title: "Review PR comments", priority: "medium", priorityColor: "#f59e0b" },
  {
    title: "Update project roadmap",
    priority: "low",
    priorityColor: "#3b82f6",
  },
];

const DUMMY_WORKFLOWS = [
  {
    title: "Daily Morning Briefing",
    icons: [
      "images/icons/gmail.svg",
      "images/icons/googlecalendar.webp",
      "images/icons/slack.svg",
    ],
    runs: 127,
  },
  {
    title: "GitHub PR Tracker",
    icons: [
      "images/icons/github.svg",
      "images/icons/slack.svg",
      "images/icons/notion.webp",
    ],
    runs: 43,
  },
  {
    title: "Notion Weekly Digest",
    icons: [
      "images/icons/notion.webp",
      "images/icons/googledocs.webp",
      "images/icons/slack.svg",
    ],
    runs: 89,
  },
  {
    title: "Invoice Reminder",
    icons: [
      "images/icons/gmail.svg",
      "images/icons/notion.webp",
      "images/icons/googlecalendar.webp",
    ],
    runs: 21,
  },
];

// --- Row components with their own hooks for staggered animation ---

interface EmailRowProps {
  email: { from: string; subject: string; time: string };
  index: number;
  cardDelay: number;
}

const EmailRow: React.FC<EmailRowProps> = ({ email, index, cardDelay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const rowProgress = spring({
    frame: frame - (cardDelay + index * 6),
    fps,
    config: { damping: 200 },
  });
  const opacity = interpolate(rowProgress, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const translateY = interpolate(rowProgress, [0, 1], [16, 0]);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "14px 24px",
        borderTop: index === 0 ? "none" : "1px solid rgba(255,255,255,0.04)",
        opacity,
        transform: `translateY(${translateY}px)`,
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            color: "#e4e4e7",
            fontFamily: FONTS.body,
            fontSize: 26,
            fontWeight: 600,
            marginBottom: 2,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {email.from}
        </div>
        <div
          style={{
            color: COLORS.zinc400,
            fontFamily: FONTS.body,
            fontSize: 20,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {email.subject}
        </div>
      </div>
      <span
        style={{
          color: COLORS.zinc400,
          fontFamily: FONTS.body,
          fontSize: 20,
          flexShrink: 0,
          marginLeft: 12,
        }}
      >
        {email.time}
      </span>
    </div>
  );
};

interface EventRowProps {
  event: { title: string; time: string; color: string };
  index: number;
  cardDelay: number;
}

const EventRow: React.FC<EventRowProps> = ({ event, index, cardDelay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const rowProgress = spring({
    frame: frame - (cardDelay + index * 6),
    fps,
    config: { damping: 200 },
  });
  const opacity = interpolate(rowProgress, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const translateY = interpolate(rowProgress, [0, 1], [16, 0]);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "14px 24px",
        borderTop: index === 0 ? "none" : "1px solid rgba(255,255,255,0.04)",
        opacity,
        transform: `translateY(${translateY}px)`,
      }}
    >
      <div
        style={{
          width: 4,
          height: 32,
          borderRadius: 2,
          background: event.color,
          flexShrink: 0,
        }}
      />
      <div>
        <div
          style={{
            color: "white",
            fontFamily: FONTS.body,
            fontSize: 26,
            fontWeight: 600,
          }}
        >
          {event.title}
        </div>
        <div
          style={{
            color: COLORS.zinc400,
            fontFamily: FONTS.body,
            fontSize: 20,
            marginTop: 2,
          }}
        >
          {event.time}
        </div>
      </div>
    </div>
  );
};

interface TodoRowProps {
  todo: { title: string; priority: string; priorityColor: string };
  index: number;
  cardDelay: number;
}

const TodoRow: React.FC<TodoRowProps> = ({ todo, index, cardDelay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const rowProgress = spring({
    frame: frame - (cardDelay + index * 6),
    fps,
    config: { damping: 200 },
  });
  const opacity = interpolate(rowProgress, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const translateY = interpolate(rowProgress, [0, 1], [16, 0]);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "14px 24px",
        borderTop: index === 0 ? "none" : "1px solid rgba(255,255,255,0.04)",
        opacity,
        transform: `translateY(${translateY}px)`,
      }}
    >
      <div
        style={{
          width: 14,
          height: 14,
          borderRadius: "50%",
          border: `2px dashed ${todo.priorityColor}`,
          flexShrink: 0,
        }}
      />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            color: "white",
            fontFamily: FONTS.body,
            fontSize: 26,
            fontWeight: 500,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {todo.title}
        </div>
      </div>
      <div
        style={{
          padding: "3px 8px",
          borderRadius: 4,
          background: todo.priorityColor + "22",
          color: todo.priorityColor,
          fontSize: 16,
          fontFamily: FONTS.body,
          fontWeight: 600,
          textTransform: "capitalize",
        }}
      >
        {todo.priority}
      </div>
    </div>
  );
};

interface WorkflowRowProps {
  wf: { title: string; icons: string[]; runs: number };
  index: number;
  cardDelay: number;
}

const WorkflowRow: React.FC<WorkflowRowProps> = ({ wf, index, cardDelay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const rowProgress = spring({
    frame: frame - (cardDelay + index * 6),
    fps,
    config: { damping: 200 },
  });
  const opacity = interpolate(rowProgress, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const translateY = interpolate(rowProgress, [0, 1], [16, 0]);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "16px 24px",
        borderTop: index === 0 ? "none" : "1px solid rgba(255,255,255,0.04)",
        opacity,
        transform: `translateY(${translateY}px)`,
      }}
    >
      {/* Stacked icons */}
      <div style={{ display: "flex", alignItems: "center" }}>
        {wf.icons.map((icon, j) => {
          const rotations = [6, -5, 7];
          return (
          <div
            key={j}
            style={{
              width: 40,
              height: 40,
              borderRadius: 8,
              background: "#27272a",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              marginLeft: j > 0 ? -8 : 0,
              zIndex: wf.icons.length - j,
              position: "relative",
              overflow: "hidden",
              border: "2px solid #1e1e21",
              transform: `rotate(${rotations[j] ?? 0}deg)`,
            }}
          >
            <Img
              src={staticFile(icon)}
              style={{ width: 26, height: 26, objectFit: "contain", filter: icon.includes("github") ? "invert(1)" : undefined }}
            />
          </div>
        );
        })}
      </div>
      <div style={{ flex: 1 }}>
        <div
          style={{
            color: "white",
            fontFamily: FONTS.body,
            fontSize: 26,
            fontWeight: 600,
          }}
        >
          {wf.title}
        </div>
        <div
          style={{
            color: COLORS.zinc400,
            fontFamily: FONTS.body,
            fontSize: 20,
            marginTop: 2,
          }}
        >
          {wf.runs} runs
        </div>
      </div>
      <div
        style={{
          padding: "6px 14px",
          borderRadius: 8,
          background: COLORS.primary + "22",
          color: COLORS.primary,
          fontSize: 18,
          fontFamily: FONTS.body,
          fontWeight: 700,
        }}
      >
        Run
      </div>
    </div>
  );
};

// --- DashCard ---

interface DashCardProps {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  delay: number;
}

const DashCard: React.FC<DashCardProps> = ({
  title,
  icon,
  children,
  delay,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const progress = spring({
    frame: frame - delay,
    fps,
    config: { damping: 22, stiffness: 100 },
  });
  const opacity = interpolate(progress, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const y = interpolate(progress, [0, 1], [20, 0]);

  return (
    <div
      style={{
        background: "#1e1e21",
        borderRadius: 24,
        overflow: "hidden",
        transform: `translateY(${y}px)`,
        opacity,
        display: "flex",
        flexDirection: "column",
        height: "100%",
      }}
    >
      {/* Card header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "18px 24px 14px",
        }}
      >
        {icon}
        <span
          style={{
            color: "#d4d4d8",
            fontFamily: FONTS.body,
            fontWeight: 500,
            fontSize: 28,
          }}
        >
          {title}
        </span>
      </div>
      {/* Card content */}
      <div style={{ flex: 1, overflow: "hidden" }}>{children}</div>
    </div>
  );
};

export const S28_DashboardReveal: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Greeting entrance
  const greetProgress = spring({ frame, fps, config: { damping: 22 } });
  const greetOpacity = interpolate(greetProgress, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const greetY = interpolate(greetProgress, [0, 1], [20, 0]);

  // Staggered summary items animation
  const makeSummaryAnim = (delay: number) => {
    const p = spring({ frame: frame - delay, fps, config: { damping: 200 } });
    return {
      opacity: interpolate(p, [0, 0.1], [0, 1], { extrapolateRight: "clamp" }),
      transform: `translateY(${interpolate(p, [0, 1], [10, 0])}px)`,
      display: "inline-flex" as const,
      alignItems: "center" as const,
      gap: 6,
    };
  };
  const summaryAnims = [0, 4, 10, 16, 22].map(makeSummaryAnim);

  return (
    <AbsoluteFill style={{ background: COLORS.bgLight, overflowY: "hidden" }}>
      {/* Greeting whoosh */}
      <Sequence from={0}><Audio src={SFX.whoosh} volume={0.25} /></Sequence>
      {/* All DashCards slide in together */}
      <Sequence from={10}><Audio src={SFX.uiSwitch} volume={0.3} /></Sequence>
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: "16px 40px",
          gap: 50,
        }}
      >
        {/* Greeting */}
        <div
          style={{
            width: "100%",
            maxWidth: 1600,
            transform: `translateY(${greetY}px)`,
            opacity: greetOpacity,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: 12,
              marginBottom: 4,
            }}
          >
            <span
              style={{
                fontFamily: FONTS.body,
                fontSize: 64,
                fontWeight: 500,
                color: COLORS.zinc600,
              }}
            >
              Good morning,
            </span>
            <span
              style={{
                fontFamily: FONTS.body,
                fontSize: 64,
                fontWeight: 500,
                color: COLORS.textDark,
              }}
            >
              Aryan :)
            </span>
          </div>
          <div
            style={{
              fontFamily: FONTS.body,
              fontSize: 30,
              color: COLORS.zinc600,
              display: "flex",
              alignItems: "center",
              gap: 10,
              flexWrap: "wrap",
            }}
          >
            <span style={summaryAnims[0]}>You have</span>
            <span style={summaryAnims[1]}>
              <CalendarUpload01Icon size={28} style={{ color: "#60a5fa" }} />
              <span style={{ color: COLORS.textDark, fontWeight: 600 }}>3</span>
              <span>meetings,</span>
            </span>
            <span style={summaryAnims[2]}>
              <CheckmarkCircle02Icon size={28} style={{ color: "#34d399" }} />
              <span style={{ color: COLORS.textDark, fontWeight: 600 }}>4</span>
              <span>tasks due,</span>
            </span>
            <span style={summaryAnims[3]}>
              <InboxUnreadIcon size={28} style={{ color: "#38bdf8" }} />
              <span style={{ color: COLORS.textDark, fontWeight: 600 }}>5</span>
              <span>unread emails, and</span>
            </span>
            <span style={summaryAnims[4]}>
              <WorkflowSquare05Icon size={28} style={{ color: "#f59e0b" }} />
              <span style={{ color: COLORS.textDark, fontWeight: 600 }}>2</span>
              <span>workflows today.</span>
            </span>
          </div>
        </div>

        {/* 2x2 Dashboard cards */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gridAutoRows: "1fr",
            gap: 15,
            width: "100%",
            maxWidth: 1600,
          }}
        >
          {/* Emails Card */}
          <DashCard
            title="Unread emails"
            icon={
              <InboxUnreadIcon size={24} style={{ color: COLORS.zinc400 }} />
            }
            delay={10}
          >
            {DUMMY_EMAILS.map((email, i) => (
              <EmailRow key={i} email={email} index={i} cardDelay={10} />
            ))}
          </DashCard>

          {/* Events Card */}
          <DashCard
            title="Upcoming events"
            icon={
              <CalendarUpload01Icon
                size={24}
                style={{ color: COLORS.zinc400 }}
              />
            }
            delay={10}
          >
            {DUMMY_EVENTS.map((event, i) => (
              <EventRow key={i} event={event} index={i} cardDelay={10} />
            ))}
          </DashCard>

          {/* Todos Card */}
          <DashCard
            title="Inbox Todos"
            icon={
              <CheckmarkCircle02Icon
                size={24}
                style={{ color: COLORS.zinc400 }}
              />
            }
            delay={10}
          >
            {DUMMY_TODOS.map((todo, i) => (
              <TodoRow key={i} todo={todo} index={i} cardDelay={10} />
            ))}
          </DashCard>

          {/* Workflows Card */}
          <DashCard
            title="Workflows"
            icon={
              <WorkflowSquare05Icon
                size={24}
                style={{ color: COLORS.zinc400 }}
              />
            }
            delay={10}
          >
            {DUMMY_WORKFLOWS.map((wf, i) => (
              <WorkflowRow key={i} wf={wf} index={i} cardDelay={10} />
            ))}
          </DashCard>
        </div>
      </div>
    </AbsoluteFill>
  );
};
