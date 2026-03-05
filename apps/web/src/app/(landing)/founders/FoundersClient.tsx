"use client";

import Image from "next/image";
import FAQAccordion from "@/components/seo/FAQAccordion";
import ChatDemo from "@/features/landing/components/demo/founders-demo/ChatDemo";
import {
  BRIEFING_MESSAGES,
  INVESTOR_MESSAGES,
  PIPELINE_MESSAGES,
  PROACTIVE_MESSAGES,
} from "@/features/landing/components/demo/founders-demo/foundersDemoConstants";
import Hero from "@/features/landing/components/demo/founders-demo/Hero";
import SectionHeader from "@/features/landing/components/demo/founders-demo/SectionHeader";
import SlackDemo from "@/features/landing/components/demo/founders-demo/SlackDemo";
import WorkflowsDemo from "@/features/landing/components/demo/founders-demo/WorkflowsDemo";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { FOUNDERS_FAQS } from "@/features/landing/data/personaFaqs";

const SlackIcon = () => (
  <Image
    src="/images/icons/slack.svg"
    width={14}
    height={14}
    alt="Slack"
    className="opacity-70"
  />
);

export default function FoundersClient() {
  return (
    <div className="w-full">
      <Hero />

      {/* Proactive AI — saves time, acts without being asked */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Proactive AI"
          headline="GAIA does the work before you think to ask."
          description="Stop spending hours on the same reports, updates, and follow-ups week after week. GAIA runs in the background — it notices what matters, handles the grunt work, and reports back. You focus on what only you can do."
          integrations={[
            { id: "gmail", label: "Gmail" },
            { id: "slack", label: "Slack" },
            { id: "github", label: "GitHub" },
            { id: "hubspot", label: "HubSpot" },
            { id: "notion", label: "Notion" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={PROACTIVE_MESSAGES} minHeight={480} />
        </div>
      </section>

      {/* Morning Briefing */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Daily Briefing"
          headline="Your morning brief, ready before your coffee."
          description="GAIA scans your inbox, calendar, Slack, and GitHub overnight — and delivers one crisp summary at 9am. No tabs, no scramble, no wasted hour."
          integrations={[
            { id: "gmail", label: "Gmail" },
            { id: "googlecalendar", label: "Calendar" },
            { id: "slack", label: "Slack" },
            { id: "github", label: "GitHub" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={BRIEFING_MESSAGES} minHeight={520} />
        </div>
      </section>

      {/* Investor Relations */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Investor Relations"
          headline="Never send an investor update late again."
          description="GAIA pulls your latest MRR, churn, and pipeline from Google Sheets, drafts the full update, and tracks every investor thread — so you spend 5 minutes on the update, not 2 hours."
          integrations={[
            { id: "googlesheets", label: "Sheets" },
            { id: "gmail", label: "Gmail" },
            { id: "notion", label: "Notion" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={INVESTOR_MESSAGES} minHeight={540} />
        </div>
      </section>

      {/* Team Operations */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Team Ops"
          labelIcon={<SlackIcon />}
          headline={
            <div className="relative">
              Your team gets answers in{" "}
              <Image
                src="/images/icons/macos/slack.png"
                width={65}
                height={65}
                alt="Slack"
                className="rotate-12 inline-block align-middle bottom-2 relative"
              />{" "}
              Slack — without pulling you in.
            </div>
          }
          description="Ask @GAIA anything in your Slack channel and it answers from your GitHub, Linear, and docs — instantly, accurately, without a single meeting."
          integrations={[
            { id: "slack", label: "Slack" },
            { id: "github", label: "GitHub" },
            { id: "linear", label: "Linear" },
            { id: "notion", label: "Notion" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <SlackDemo />
        </div>
      </section>

      {/* Customer & Sales Pipeline */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Sales Pipeline"
          headline="Know which deals need you before they go cold."
          description="GAIA watches your CRM around the clock, spots deals about to stall, and drafts follow-ups before you remember to check. Nothing slips."
          integrations={[
            { id: "hubspot", label: "HubSpot" },
            { id: "gmail", label: "Gmail" },
            { id: "linkedin", label: "LinkedIn" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={PIPELINE_MESSAGES} minHeight={500} />
        </div>
      </section>

      {/* On Autopilot */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="On Autopilot"
          headline="Set it once. It runs while you sleep."
          description="Daily briefings at 9am. Weekly pipeline reviews. Monthly board prep. Tell GAIA once — it builds the workflow, connects the tools, and runs every time. You never touch it again."
          integrations={[
            { id: "gmail", label: "Gmail" },
            { id: "googlecalendar", label: "Calendar" },
            { id: "googlesheets", label: "Sheets" },
            { id: "github", label: "GitHub" },
            { id: "slack", label: "Slack" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <WorkflowsDemo />
        </div>
      </section>

      {/* FAQ */}
      <section className="mx-auto w-full max-w-3xl px-6 py-20 sm:py-28">
        <h2 className="mb-2 text-center font-serif text-4xl font-normal text-white sm:text-5xl">
          Frequently asked questions
        </h2>
        <p className="mb-10 text-center text-zinc-400">
          Everything you need to know about GAIA for founders.
        </p>
        <FAQAccordion faqs={FOUNDERS_FAQS} />
      </section>

      <FinalSection />
    </div>
  );
}
