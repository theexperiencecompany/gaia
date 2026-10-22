import Link from "next/link";
import { ADVERTISED_PRO_MONTHLY_PRICE } from "@/features/pricing/advertisedPrice";

interface CapabilityGroup {
  heading: string;
  items: { text: string; href: string }[];
}

const CAPABILITY_GROUPS: CapabilityGroup[] = [
  {
    heading: "Email and calendar",
    items: [
      {
        text: "Reads, searches, drafts and sends email in Gmail and Outlook, and triages new Gmail on its own",
        href: "/features/email",
      },
      {
        text: "Checks your calendar, finds free slots, creates and moves events, and preps you for meetings",
        href: "/features/calendar",
      },
      {
        text: "Sends a daily briefing of your email, calendar and todos before you ask",
        href: "/features/proactive-ai",
      },
    ],
  },
  {
    heading: "Tasks, goals and reminders",
    items: [
      {
        text: "Manages your to-do list in plain language and turns emails into tasks",
        href: "/features/todos",
      },
      {
        text: "Turns a goal into a step-by-step roadmap",
        href: "/features/goals",
      },
      {
        text: "Sets one-time and recurring reminders",
        href: "/features/reminders",
      },
    ],
  },
  {
    heading: "Workflow automation",
    items: [
      {
        text: "Builds workflows you describe in plain English",
        href: "/features/workflows",
      },
      {
        text: "Runs them on a schedule or when something happens in your tools",
        href: "/features/event-triggers",
      },
      {
        text: "Extends itself with installable skills and generates PDF, DOCX and HTML documents",
        href: "/features/skills",
      },
    ],
  },
  {
    heading: "Memory and intelligence",
    items: [
      {
        text: "Remembers your preferences, people and plans across every conversation",
        href: "/features/memory",
      },
      {
        text: "Researches the web across many sources and summarizes what it found",
        href: "/features/deep-research",
      },
      {
        text: "Generates images and runs code in a secure sandbox",
        href: "/features/code-execution",
      },
    ],
  },
  {
    heading: "Integrations",
    items: [
      {
        text: "Connects Gmail, Google Calendar, Slack, Notion, GitHub, Todoist, Linear and more",
        href: "/features/integrations",
      },
      {
        text: "Works as an MCP client: connect any Model Context Protocol server",
        href: "/features/mcp-support",
      },
      {
        text: "Lets you build, publish and install custom integrations",
        href: "/features/custom-integrations",
      },
    ],
  },
  {
    heading: "Where you use it",
    items: [
      {
        text: "The web app, and a desktop app for macOS, Windows and Linux",
        href: "/download",
      },
      {
        text: "Text it on WhatsApp, Telegram and iMessage, or use it in Slack and Discord",
        href: "/ai-assistant-whatsapp-telegram-imessage",
      },
      {
        text: "On the desktop it reads your screen, uses your clipboard and runs browser tasks in a cloud browser",
        href: "/ai-assistant-that-uses-your-computer",
      },
      {
        text: "Talk to it in real-time voice conversations",
        href: "/features/voice",
      },
    ],
  },
];

const LIMITS = [
  "No iOS or Android app: on a phone, you text GAIA in WhatsApp, Telegram or iMessage.",
  "It does not make or answer phone calls.",
  "It does not take over your mouse and keyboard to drive other desktop apps.",
];

const LINK_CLASS =
  "text-zinc-300 underline-offset-2 hover:text-white hover:underline";

export function FeaturesAtAGlance() {
  return (
    <section className="mx-auto max-w-6xl px-6 pb-16">
      <h2 className="font-serif mb-4 text-4xl font-normal text-white">
        GAIA features at a glance
      </h2>
      <p className="mb-10 max-w-3xl text-base font-light leading-relaxed text-zinc-400">
        GAIA is a proactive personal AI assistant. This is everything it does
        today, in one list.
      </p>
      <div className="grid grid-cols-1 gap-8 md:grid-cols-2 lg:grid-cols-3">
        {CAPABILITY_GROUPS.map((group) => (
          <div key={group.heading}>
            <h3 className="mb-3 text-sm font-medium text-zinc-100">
              {group.heading}
            </h3>
            <ul className="space-y-2 text-sm font-light leading-relaxed">
              {group.items.map((item) => (
                <li key={item.text}>
                  <Link href={item.href} className={LINK_CLASS}>
                    {item.text}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
        <div>
          <h3 className="mb-3 text-sm font-medium text-zinc-100">
            What GAIA does not do
          </h3>
          <ul className="space-y-2 text-sm font-light leading-relaxed text-zinc-300">
            {LIMITS.map((limit) => (
              <li key={limit}>{limit}</li>
            ))}
          </ul>
        </div>
        <div>
          <h3 className="mb-3 text-sm font-medium text-zinc-100">
            Pricing and licence
          </h3>
          <p className="text-sm font-light leading-relaxed text-zinc-300">
            Hosted GAIA is paid: Pro is ${ADVERTISED_PRO_MONTHLY_PRICE} a month
            per person, and GAIA Enterprise is priced on request. The code is
            source-available under the PolyForm Noncommercial license, so you
            can self-host it for personal, noncommercial use; for-profit
            self-hosting needs an enterprise licence.{" "}
            <Link href="/pricing" className={LINK_CLASS}>
              See pricing
            </Link>
          </p>
        </div>
      </div>
    </section>
  );
}
