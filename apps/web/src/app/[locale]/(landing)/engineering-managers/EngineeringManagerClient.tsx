"use client";

import { Chip } from "@heroui/chip";
import * as m from "motion/react-m";
import Image from "next/image";
import FAQAccordion from "@/components/seo/FAQAccordion";
import ProgressiveImage from "@/components/ui/ProgressiveImage";
import { EMSlackDemo } from "@/features/landing/components/demo/em-demo/EMSlackDemo";
import { EMWorkflowsDemo } from "@/features/landing/components/demo/em-demo/EMWorkflowsDemo";
import {
  EM_PROACTIVE_MESSAGES,
  ONE_ON_ONE_MESSAGES,
  SPRINT_REPORT_MESSAGES,
  TEAM_HEALTH_MESSAGES,
} from "@/features/landing/components/demo/em-demo/emDemoConstants";
import ChatDemo from "@/features/landing/components/demo/founders-demo/ChatDemo";
import SectionHeader from "@/features/landing/components/demo/founders-demo/SectionHeader";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import GetStartedButton from "@/features/landing/components/shared/GetStartedButton";
import { EM_FAQS } from "@/features/landing/data/personaFaqs";

const ease = [0.22, 1, 0.36, 1] as const;

const SlackIcon = () => (
  <Image
    src="/images/icons/slack.svg"
    width={14}
    height={14}
    alt="Slack"
    className="opacity-70"
  />
);

export default function EngineeringManagerClient() {
  return (
    <div className="w-full">
      {/* Hero */}
      <section className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden px-6 pb-16 pt-24 text-center">
        <div className="absolute inset-0 -z-10">
          <ProgressiveImage
            webpSrc="/images/wallpapers/bands_gradient_1.webp"
            pngSrc="/images/wallpapers/bands_gradient_1.png"
            alt="Gradient background"
            className="object-cover"
            shouldHaveInitialFade
            priority
          />
        </div>

        <m.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease }}
          className="relative z-10 mb-6"
        >
          <Chip variant="flat" color="primary" size="md">
            For Engineering Managers
          </Chip>
        </m.div>
        <m.h1
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease, delay: 0.1 }}
          className="font-serif relative z-10 mb-6 max-w-4xl text-5xl font-normal leading-[1.1] text-white sm:text-6xl md:text-7xl"
        >
          Stop watching every thread.
          <br />
          Start leading every person.
        </m.h1>
        <m.p
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease, delay: 0.2 }}
          className="relative z-10 mb-10 max-w-2xl text-xl font-light leading-relaxed text-white"
        >
          GAIA monitors GitHub, Linear, and Slack so you don&apos;t have to. It
          preps your 1:1s, surfaces blockers, and knows what&apos;s stuck before
          you have to ask.
        </m.p>
        <m.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease, delay: 0.3 }}
          className="relative z-10"
        >
          <GetStartedButton
            text="See it in action"
            btnColor="#000000"
            classname="text-white! text-base h-12 rounded-2xl"
          />
        </m.div>
      </section>

      {/* Section 1 — Proactive AI */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Proactive AI"
          headline="GAIA watches the code. You lead the team."
          description="Monitoring every repo, board, and thread isn't leadership — it's surveillance. GAIA watches so you don't have to. It surfaces the blockers, flags at-risk PRs, and prepares the context before you need it."
          integrations={[
            { id: "github", label: "GitHub" },
            { id: "linear", label: "Linear" },
            { id: "slack", label: "Slack" },
            { id: "gmail", label: "Gmail" },
            { id: "sentry", label: "Sentry" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={EM_PROACTIVE_MESSAGES} />
        </div>
      </section>

      {/* Section 2 — Team Health */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Team Health"
          headline="Know how your team is doing. Without micromanaging."
          description="Every morning, GAIA compiles sprint velocity, PR cycle times, and team blockers from GitHub and Linear — and delivers one clear brief. You lead with data, not guesswork."
          integrations={[
            { id: "github", label: "GitHub" },
            { id: "linear", label: "Linear" },
            { id: "slack", label: "Slack" },
            { id: "googlecalendar", label: "Calendar" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={TEAM_HEALTH_MESSAGES} />
        </div>
      </section>

      {/* Section 3 — 1:1 Prep */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="1:1 Prep"
          headline="Walk into every 1:1 knowing what matters."
          description="Before each 1:1, GAIA compiles your team member's recent PRs, completed tickets, open blockers, and relevant Slack context — in one briefing doc. Every conversation starts with clarity."
          integrations={[
            { id: "github", label: "GitHub" },
            { id: "linear", label: "Linear" },
            { id: "slack", label: "Slack" },
            { id: "googlecalendar", label: "Calendar" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={ONE_ON_ONE_MESSAGES} />
        </div>
      </section>

      {/* Section 4 — Sprint Reports */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Sprint Reports"
          headline="Retro docs that write themselves."
          description="GAIA compiles sprint velocity, PR cycle times, and completed tickets from Linear and GitHub into a formatted report — then posts it to Notion and Slack. No spreadsheets, no manual aggregation. Ready before retro starts."
          integrations={[
            { id: "linear", label: "Linear" },
            { id: "github", label: "GitHub" },
            { id: "notion", label: "Notion" },
            { id: "slack", label: "Slack" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={SPRINT_REPORT_MESSAGES} />
        </div>
      </section>

      {/* Section 5 — Team Ops (Slack) */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Team Ops"
          labelIcon={<SlackIcon />}
          headline="Your team finds answers without pinging you."
          description="Ask @GAIA about any blocker, PR status, or sprint metric in Slack — it answers from GitHub, Linear, and your docs instantly. Your team gets unblocked. You stay in flow."
          integrations={[
            { id: "slack", label: "Slack" },
            { id: "github", label: "GitHub" },
            { id: "linear", label: "Linear" },
            { id: "notion", label: "Notion" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <EMSlackDemo />
        </div>
      </section>

      {/* Section 6 — On Autopilot */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="On Autopilot"
          headline="Run your team without running yourself ragged."
          description="Weekly sprint reports every Friday. 1:1 briefs 30 minutes before each meeting. PR stale alerts every 48 hours. Tell GAIA once — it connects GitHub, Linear, and Slack and runs on schedule."
          integrations={[
            { id: "github", label: "GitHub" },
            { id: "linear", label: "Linear" },
            { id: "slack", label: "Slack" },
            { id: "googlecalendar", label: "Calendar" },
            { id: "notion", label: "Notion" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <EMWorkflowsDemo />
        </div>
      </section>

      {/* FAQ */}
      <section className="mx-auto w-full max-w-3xl px-6 py-20 sm:py-28">
        <h2 className="mb-2 text-center font-serif text-4xl font-normal text-white sm:text-5xl">
          Frequently asked questions
        </h2>
        <p className="mb-10 text-center text-zinc-400">
          Everything you need to know about GAIA for engineering managers.
        </p>
        <FAQAccordion faqs={EM_FAQS} />
      </section>

      <FinalSection />
    </div>
  );
}
