"use client";

import { Chip } from "@heroui/chip";
import { m } from "motion/react";
import Image from "next/image";
import FAQAccordion from "@/components/seo/FAQAccordion";
import ProgressiveImage from "@/components/ui/ProgressiveImage";
import ChatDemo from "@/features/landing/components/demo/founders-demo/ChatDemo";
import SectionHeader from "@/features/landing/components/demo/founders-demo/SectionHeader";
import { SoftwareDevSlackDemo } from "@/features/landing/components/demo/software-dev-demo/SoftwareDevSlackDemo";
import { SoftwareDevWorkflowsDemo } from "@/features/landing/components/demo/software-dev-demo/SoftwareDevWorkflowsDemo";
import {
  INCIDENT_MESSAGES,
  PR_MESSAGES,
  PROACTIVE_MESSAGES,
  STANDUP_MESSAGES,
} from "@/features/landing/components/demo/software-dev-demo/softwareDevDemoConstants";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import GetStartedButton from "@/features/landing/components/shared/GetStartedButton";
import { SOFTWARE_DEV_FAQS } from "@/features/landing/data/personaFaqs";

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

export default function SoftwareDevClient() {
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
            For Developers
          </Chip>
        </m.div>
        <m.h1
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease, delay: 0.1 }}
          className="font-serif relative z-10 mb-6 max-w-4xl text-5xl font-normal leading-[1.1] text-white sm:text-6xl md:text-7xl"
        >
          Ship code.
          <br />
          Not status updates.
        </m.h1>
        <m.p
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease, delay: 0.2 }}
          className="relative z-10 mb-10 max-w-2xl text-xl font-light leading-relaxed text-white"
        >
          GAIA monitors GitHub, Linear, and Slack in the background — triages
          what needs you, handles the rest, and delivers your standup before
          your first commit.
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

      {/* Section 1: Proactive AI */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Proactive AI"
          headline="GAIA works while you ship."
          description="Stop losing deep work sessions to GitHub noise, stale tickets, and Slack threads you should have seen hours ago. GAIA runs silently in the background — surfaces what actually matters, handles the rest, and reports back when you surface."
          integrations={[
            { id: "github", label: "GitHub" },
            { id: "linear", label: "Linear" },
            { id: "slack", label: "Slack" },
            { id: "gmail", label: "Gmail" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={PROACTIVE_MESSAGES} minHeight={340} />
        </div>
      </section>

      {/* Section 2: Daily Standup */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Daily Standup"
          headline="Your standup, written before your first commit."
          description="Every morning GAIA compiles your merged PRs, completed Linear tickets, and blocked work from GitHub and Slack — and formats it as a ready-to-post standup update. Just show up to standup."
          integrations={[
            { id: "github", label: "GitHub" },
            { id: "linear", label: "Linear" },
            { id: "slack", label: "Slack" },
            { id: "googlecalendar", label: "Calendar" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={STANDUP_MESSAGES} minHeight={380} />
        </div>
      </section>

      {/* Section 3: PR Review */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="PR Review"
          headline="No PR goes stale on your watch."
          description="GAIA tracks every open PR across your repositories, flags reviews going cold, and summarizes what changed — so you unblock your team in 2 minutes, not 20."
          integrations={[
            { id: "github", label: "GitHub" },
            { id: "slack", label: "Slack" },
            { id: "linear", label: "Linear" },
            { id: "notion", label: "Notion" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={PR_MESSAGES} minHeight={400} />
        </div>
      </section>

      {/* Section 4: Team Q&A */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Team Q&A"
          labelIcon={<SlackIcon />}
          headline="Your team gets answers in Slack. Without pulling you in."
          description="Ask @GAIA anything in your Slack channel and it answers from GitHub, Linear, Notion, and your docs — instantly. No DMs, no interruptions, no meetings about meetings."
          integrations={[
            { id: "slack", label: "Slack" },
            { id: "github", label: "GitHub" },
            { id: "linear", label: "Linear" },
            { id: "notion", label: "Notion" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <SoftwareDevSlackDemo />
        </div>
      </section>

      {/* Section 5: Incident Response */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Incident Response"
          headline="First to know. Never the last to respond."
          description="GAIA monitors Sentry errors, GitHub alerts, and Datadog anomalies — and pages you in Slack the moment something breaks, with context already pulled so you can triage in seconds."
          integrations={[
            { id: "github", label: "GitHub" },
            { id: "slack", label: "Slack" },
            { id: "sentry", label: "Sentry" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={INCIDENT_MESSAGES} minHeight={340} />
        </div>
      </section>

      {/* Section 6: On Autopilot */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="On Autopilot"
          headline="Set it once. It ships while you sleep."
          description="Daily standup at 9am. Weekly sprint reports. PR review reminders every 24 hours. Tell GAIA once — it builds the workflow, connects the tools, and runs every time. You never touch it again."
          integrations={[
            { id: "github", label: "GitHub" },
            { id: "linear", label: "Linear" },
            { id: "slack", label: "Slack" },
            { id: "googlecalendar", label: "Calendar" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <SoftwareDevWorkflowsDemo />
        </div>
      </section>

      {/* FAQ */}
      <section className="mx-auto w-full max-w-3xl px-6 py-20 sm:py-28">
        <h2 className="mb-2 text-center font-serif text-4xl font-normal text-white sm:text-5xl">
          Frequently asked questions
        </h2>
        <p className="mb-10 text-center text-zinc-400">
          Everything you need to know about GAIA for developers.
        </p>
        <FAQAccordion faqs={SOFTWARE_DEV_FAQS} />
      </section>

      <FinalSection />
    </div>
  );
}
