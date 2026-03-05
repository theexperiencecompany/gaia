"use client";

import { Chip } from "@heroui/chip";
import { m } from "motion/react";
import Image from "next/image";
import FAQAccordion from "@/components/seo/FAQAccordion";
import ProgressiveImage from "@/components/ui/ProgressiveImage";
import ChatDemo from "@/features/landing/components/demo/founders-demo/ChatDemo";
import SectionHeader from "@/features/landing/components/demo/founders-demo/SectionHeader";
import { SalesSlackDemo } from "@/features/landing/components/demo/sales-demo/SalesSlackDemo";
import { SalesWorkflowsDemo } from "@/features/landing/components/demo/sales-demo/SalesWorkflowsDemo";
import {
  FOLLOW_UP_MESSAGES,
  MEETING_PREP_MESSAGES,
  PIPELINE_BRIEF_MESSAGES,
  SALES_PROACTIVE_MESSAGES,
} from "@/features/landing/components/demo/sales-demo/salesDemoConstants";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import GetStartedButton from "@/features/landing/components/shared/GetStartedButton";
import { SALES_FAQS } from "@/features/landing/data/personaFaqs";

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

export default function SalesClient() {
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
            For Sales
          </Chip>
        </m.div>
        <m.h1
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease, delay: 0.1 }}
          className="font-serif relative z-10 mb-6 max-w-4xl text-5xl font-normal leading-[1.1] text-white sm:text-6xl md:text-7xl"
        >
          You&apos;re paid to close deals.
          <br />
          Not to update your CRM.
        </m.h1>
        <m.p
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease, delay: 0.2 }}
          className="relative z-10 mb-10 max-w-2xl text-xl font-light leading-relaxed text-white"
        >
          GAIA monitors your pipeline around the clock, spots deals about to go
          cold, and drafts follow-ups before you remember to check. Your CRM
          stays current without you touching it.
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
          headline="GAIA watches your pipeline while you sell."
          description="Stop losing deals because you forgot to follow up. GAIA monitors every open opportunity in your CRM, tracks email threads, and surfaces the deals that need your attention — before they go cold."
          integrations={[
            { id: "hubspot", label: "HubSpot" },
            { id: "gmail", label: "Gmail" },
            { id: "linkedin", label: "LinkedIn" },
            { id: "googlecalendar", label: "Calendar" },
            { id: "slack", label: "Slack" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={SALES_PROACTIVE_MESSAGES} minHeight={340} />
        </div>
      </section>

      {/* Section 2 — Pipeline Brief */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Pipeline Brief"
          headline="Know exactly which deals need you. Every morning."
          description="GAIA scans your HubSpot pipeline, email threads, and calendar before you start your day — then delivers one prioritized brief so you spend your first hour selling, not reviewing dashboards."
          integrations={[
            { id: "hubspot", label: "HubSpot" },
            { id: "gmail", label: "Gmail" },
            { id: "googlecalendar", label: "Calendar" },
            { id: "linkedin", label: "LinkedIn" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={PIPELINE_BRIEF_MESSAGES} minHeight={380} />
        </div>
      </section>

      {/* Section 3 — Meeting Prep */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Meeting Prep"
          headline="Walk into every call prepared to close."
          description="You close, not scramble. Before each sales call, GAIA pulls your prospect's LinkedIn activity, recent email history, CRM context, and deal stage — and delivers a one-page brief so you walk in with an edge."
          integrations={[
            { id: "hubspot", label: "HubSpot" },
            { id: "gmail", label: "Gmail" },
            { id: "linkedin", label: "LinkedIn" },
            { id: "googlecalendar", label: "Calendar" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={MEETING_PREP_MESSAGES} minHeight={420} />
        </div>
      </section>

      {/* Section 4 — Follow-Ups */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Follow-Ups"
          headline="No deal goes cold because you forgot."
          description="GAIA tracks every prospect interaction, spots deals going quiet, drafts personalized follow-ups, and queues them for your review. Your cadence never breaks."
          integrations={[
            { id: "hubspot", label: "HubSpot" },
            { id: "gmail", label: "Gmail" },
            { id: "linkedin", label: "LinkedIn" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={FOLLOW_UP_MESSAGES} minHeight={380} />
        </div>
      </section>

      {/* Section 5 — Sales Ops (Slack) */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Sales Ops"
          labelIcon={<SlackIcon />}
          headline="Your whole pipeline. Answered in Slack."
          description="Ask @GAIA about any deal, any prospect, or your weekly quota in your Slack channel. It pulls from HubSpot, Gmail, and LinkedIn instantly — no CRM login required."
          integrations={[
            { id: "slack", label: "Slack" },
            { id: "hubspot", label: "HubSpot" },
            { id: "gmail", label: "Gmail" },
            { id: "linkedin", label: "LinkedIn" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <SalesSlackDemo />
        </div>
      </section>

      {/* Section 6 — On Autopilot */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="On Autopilot"
          headline="Your pipeline review runs itself."
          description="Morning pipeline brief at 8am. Weekly deal reviews every Monday. Follow-up reminders on your cadence. Tell GAIA once — it builds the workflow, connects HubSpot, Gmail, and Calendar, and runs every time. You never touch it again."
          integrations={[
            { id: "hubspot", label: "HubSpot" },
            { id: "gmail", label: "Gmail" },
            { id: "googlecalendar", label: "Calendar" },
            { id: "linkedin", label: "LinkedIn" },
            { id: "slack", label: "Slack" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <SalesWorkflowsDemo />
        </div>
      </section>

      {/* FAQ */}
      <section className="mx-auto w-full max-w-3xl px-6 py-20 sm:py-28">
        <h2 className="mb-2 text-center font-serif text-4xl font-normal text-white sm:text-5xl">
          Frequently asked questions
        </h2>
        <p className="mb-10 text-center text-zinc-400">
          Everything you need to know about GAIA for sales.
        </p>
        <FAQAccordion faqs={SALES_FAQS} />
      </section>

      <FinalSection />
    </div>
  );
}
