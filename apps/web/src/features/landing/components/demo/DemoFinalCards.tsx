import {
  CalendarIcon,
  CheckmarkBadge01Icon,
  CheckmarkBadge02Icon,
  FavouriteIcon,
  Flag02Icon,
  MessageIcon,
  RepeatIcon,
  ZapIcon,
} from "@icons";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import EmailComposeCard from "@/features/mail/components/EmailComposeCard";
import { FOUNDER_EMAIL } from "./demoConstants";
import type { FinalCardType } from "./types";

// ─── Workflow card (developer use case) ───────────────────────────────────────
function WorkflowCard() {
  const steps = [
    { icon: "github", label: "GitHub PRs fetched", count: "4 open" },
    { icon: "linear", label: "Linear tickets synced", count: "12 in-progress" },
    { icon: "slack", label: "Posted to Slack", count: "#engineering-standup" },
  ];
  return (
    <div className="w-full max-w-sm rounded-2xl bg-zinc-900 p-4">
      <div className="mb-3 flex items-center gap-2">
        <ZapIcon width={16} height={16} className="text-primary" />
        <span className="text-sm font-medium text-zinc-200">
          Workflow: Daily Standup
        </span>
        <span className="ml-auto rounded-full bg-green-500/20 px-2 py-0.5 text-[10px] text-green-400">
          Completed
        </span>
      </div>
      <div className="space-y-2">
        {steps.map((s) => (
          <div key={s.label} className="flex items-center gap-3">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center">
              {getToolCategoryIcon(s.icon, {
                width: 20,
                height: 20,
                showBackground: true,
              })}
            </div>
            <div className="flex min-w-0 flex-1 items-center justify-between">
              <span className="text-xs text-zinc-300">{s.label}</span>
              <span className="text-[10px] text-zinc-500">{s.count}</span>
            </div>
            <CheckmarkBadge01Icon
              width={14}
              height={14}
              className="text-green-400"
            />
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Social content card (marketer use case) ──────────────────────────────────
// Shows scheduled posts styled like real TwitterCard from TwitterSearchSection
function SocialContentCard() {
  const posts = [
    {
      platform: "twitter",
      platformColor: "#1d9bf0",
      handle: "@gaiaapp",
      name: "GAIA",
      verified: true,
      scheduledFor: "Mon 9:00 AM",
      text: "We analyzed 6 months of top posts: threads with data get 3× more engagement. Here's the breakdown 🧵",
      likes: "2.4K",
      replies: "312",
      retweets: "891",
    },
    {
      platform: "linkedin",
      platformColor: "#0a66c2",
      handle: "gaia-app",
      name: "GAIA",
      verified: false,
      scheduledFor: "Wed 11:00 AM",
      text: "AI assistants that actually do the work — 40% of tasks now completed autonomously. Here's what changed.",
      likes: "1.1K",
      replies: "87",
      retweets: "204",
    },
  ];

  return (
    <div className="flex w-full max-w-sm flex-col gap-2">
      <p className="px-1 text-[11px] text-zinc-500">
        2 posts scheduled · Mon–Wed
      </p>
      {posts.map((p) => (
        <div
          key={p.platform}
          className="flex w-full flex-col gap-2 rounded-xl border border-zinc-700/60 bg-zinc-900 p-4"
        >
          {/* Author row */}
          <div className="flex items-center gap-2.5">
            <div
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white"
              style={{ backgroundColor: p.platformColor }}
            >
              G
            </div>
            <div className="flex min-w-0 flex-1 flex-col">
              <div className="flex items-center gap-1">
                <span className="text-sm font-semibold text-zinc-100">
                  {p.name}
                </span>
                {p.verified && (
                  <CheckmarkBadge02Icon className="h-3.5 w-3.5 shrink-0 text-[#1d9bf0]" />
                )}
              </div>
              <span className="text-[11px] text-zinc-500">@{p.handle}</span>
            </div>
            <span className="shrink-0 rounded-full bg-green-500/15 px-2 py-0.5 text-[10px] text-green-400">
              {p.scheduledFor}
            </span>
          </div>

          {/* Post text */}
          <p className="text-xs leading-relaxed text-zinc-300">{p.text}</p>

          {/* Metrics */}
          <div className="flex items-center gap-5 pt-0.5 text-zinc-600">
            <div className="flex items-center gap-1 text-[11px]">
              <FavouriteIcon className="h-3.5 w-3.5" />
              <span>{p.likes}</span>
            </div>
            <div className="flex items-center gap-1 text-[11px]">
              <MessageIcon className="h-3.5 w-3.5" />
              <span>{p.replies}</span>
            </div>
            <div className="flex items-center gap-1 text-[11px]">
              <RepeatIcon className="h-3.5 w-3.5" />
              <span>{p.retweets}</span>
            </div>
            <div className="ml-auto flex items-center gap-1 text-[10px] text-zinc-500">
              {getToolCategoryIcon(p.platform, { width: 13, height: 13 })}
              <span className="capitalize">{p.platform}</span>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Study tasks card (student use case) ─────────────────────────────────────
// Matches real TodoSection styling exactly
function StudyTasksCard() {
  const tasks = [
    {
      label: "Review Chapter 7 — Data Structures",
      due: "Mon",
      priority: "high" as const,
    },
    {
      label: "Practice exam: Algorithms",
      due: "Tue",
      priority: "high" as const,
    },
    {
      label: "Read lecture notes: OS scheduling",
      due: "Wed",
      priority: "medium" as const,
    },
    { label: "Mock exam: Full paper", due: "Thu", priority: "medium" as const },
    { label: "Revision & weak areas", due: "Fri", priority: "low" as const },
  ];

  const priorityStyle = {
    high: { bg: "bg-red-500/10", text: "text-red-500" },
    medium: { bg: "bg-yellow-500/10", text: "text-yellow-500" },
    low: { bg: "bg-blue-500/10", text: "text-blue-500" },
  };

  return (
    <div className="w-fit min-w-[420px] rounded-2xl rounded-bl-none bg-zinc-800 p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-sm text-zinc-200">Finals Study Plan</span>
        <span className="text-xs text-zinc-500">5 tasks · Added to Todos</span>
      </div>
      <div className="space-y-2">
        {tasks.map((t) => (
          <div
            key={t.label}
            className="cursor-pointer rounded-xl bg-zinc-900 p-3 transition-colors hover:bg-zinc-900/70"
          >
            <div className="flex items-start gap-3">
              {/* Circular checkbox matching TodoSection */}
              <div className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border-2 border-zinc-600" />
              <div className="flex-1">
                <p className="text-sm font-medium text-zinc-100">{t.label}</p>
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                  <span
                    className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-xs ${priorityStyle[t.priority].bg} ${priorityStyle[t.priority].text}`}
                  >
                    <Flag02Icon className="h-3 w-3" />
                    {t.priority}
                  </span>
                  <span className="flex items-center gap-1 rounded-full bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400">
                    <CalendarIcon className="h-3 w-3" />
                    {t.due}
                  </span>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Morning briefing card (executive use case) ───────────────────────────────
// Calendar events styled like CalendarEventSection + email list
function MorningBriefingCard() {
  const calendarEvents = [
    {
      title: "Product standup",
      time: "9:30 AM",
      color: "#00bbff",
      calendar: "Work",
    },
    {
      title: "1:1 with Engineering Lead",
      time: "11:00 AM",
      color: "#a855f7",
      calendar: "Work",
    },
    {
      title: "Board call — Q4 review",
      time: "3:00 PM",
      color: "#f97316",
      calendar: "Work",
    },
    {
      title: "Investor sync: Sequoia",
      time: "5:00 PM",
      color: "#22c55e",
      calendar: "Personal",
    },
  ];

  const emails = [
    { from: "Alex Chen", subject: "Re: Series A term sheet — action needed" },
    { from: "Sarah (Sequoia)", subject: "Prep materials for today's call" },
    { from: "Board <board@>", subject: "Q4 metrics deck — please review" },
  ];

  return (
    <div className="flex w-full max-w-sm flex-col gap-2">
      {/* Calendar section — matches CalendarEventSection styling */}
      <div className="w-full rounded-3xl bg-zinc-800 p-4 text-white">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-medium text-zinc-400">
            Today's meetings
          </span>
          <span className="text-[10px] text-zinc-500">4 events</span>
        </div>
        <div className="space-y-1.5">
          {calendarEvents.map((ev) => (
            <div
              key={ev.title}
              className="relative flex items-start gap-2 rounded-lg p-3 pl-5 transition-colors hover:bg-zinc-700/50"
              style={{ backgroundColor: `${ev.color}18` }}
            >
              <div className="absolute left-1 top-0 flex h-full items-center">
                <div
                  className="h-[80%] w-1 flex-shrink-0 rounded-full"
                  style={{ backgroundColor: ev.color }}
                />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-sm leading-tight text-white">
                  {ev.title}
                </div>
                <div className="mt-0.5 flex items-center gap-2 text-xs text-zinc-400">
                  <span>{ev.time}</span>
                  <span className="text-zinc-600">·</span>
                  <span>{ev.calendar}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Urgent emails — matches EmailListCard item styling */}
      <div className="w-full overflow-hidden rounded-2xl bg-zinc-800">
        <div className="flex items-center justify-between px-4 py-2.5">
          <span className="text-xs font-medium text-zinc-400">
            Urgent emails
          </span>
          <span className="rounded-full bg-red-500/15 px-2 py-0.5 text-[10px] text-red-400">
            3 unread
          </span>
        </div>
        <div className="divide-y divide-zinc-700/50">
          {emails.map((em) => (
            <div
              key={em.subject}
              className="flex cursor-pointer items-start gap-3 px-4 py-3 transition-colors hover:bg-zinc-700/30"
            >
              <div className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium text-zinc-200">{em.from}</p>
                <p className="mt-0.5 truncate text-[11px] text-zinc-500">
                  {em.subject}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Router ────────────────────────────────────────────────────────────────────
export function DemoFinalCard({ type }: { type: FinalCardType }) {
  switch (type) {
    case "email":
      return <EmailComposeCard emailData={FOUNDER_EMAIL} onSent={() => {}} />;
    case "workflow":
      return <WorkflowCard />;
    case "tools":
      return <SocialContentCard />;
    case "tasks":
      return <StudyTasksCard />;
    case "briefing":
      return <MorningBriefingCard />;
    default:
      return null;
  }
}
