"use client";

import { Chip } from "@heroui/chip";
import * as m from "motion/react-m";
import Image from "next/image";
import FAQAccordion from "@/components/seo/FAQAccordion";
import ProgressiveImage from "@/components/ui/ProgressiveImage";
import { AgencySlackDemo } from "@/features/landing/components/demo/agency-demo/AgencySlackDemo";
import { AgencyWorkflowsDemo } from "@/features/landing/components/demo/agency-demo/AgencyWorkflowsDemo";
import {
  AGENCY_PROACTIVE_MESSAGES,
  BD_PIPELINE_MESSAGES,
  CLIENT_REPORT_MESSAGES,
  PORTFOLIO_BRIEF_MESSAGES,
} from "@/features/landing/components/demo/agency-demo/agencyDemoConstants";
import ChatDemo from "@/features/landing/components/demo/founders-demo/ChatDemo";
import SectionHeader from "@/features/landing/components/demo/founders-demo/SectionHeader";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import GetStartedButton from "@/features/landing/components/shared/GetStartedButton";
import { AGENCY_FAQS } from "@/features/landing/data/personaFaqs";

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

export default function AgencyClient() {
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
            For Agency Owners
          </Chip>
        </m.div>
        <m.h1
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease, delay: 0.1 }}
          className="font-serif relative z-10 mb-6 max-w-4xl text-5xl font-normal leading-[1.1] text-white sm:text-6xl md:text-7xl"
        >
          Run 10 clients
          <br />
          without losing your mind.
        </m.h1>
        <m.p
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease, delay: 0.2 }}
          className="relative z-10 mb-10 max-w-2xl text-xl font-light leading-relaxed text-white"
        >
          GAIA monitors your client portfolio, writes the status reports, and
          keeps your pipeline moving — while you focus on the work that actually
          grows the agency.
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
          headline="GAIA runs your operations. You run your agency."
          description="Client updates, project blockers, overdue invoices, and new business leads — GAIA monitors it all across your portfolio. It surfaces what needs a decision and handles everything else, so you spend your week doing billable work, not chasing status."
          integrations={[
            { id: "gmail", label: "Gmail" },
            { id: "slack", label: "Slack" },
            { id: "clickup", label: "ClickUp" },
            { id: "asana", label: "Asana" },
            { id: "hubspot", label: "HubSpot" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={AGENCY_PROACTIVE_MESSAGES} />
        </div>
      </section>

      {/* Section 2: Portfolio Brief */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Portfolio Brief"
          headline="Every client, at a glance. Every morning."
          description="GAIA scans your project management tools, email, and calendar across every active engagement — then delivers one daily brief with portfolio health, upcoming deadlines, and at-risk projects. No dashboard surfing, no status Slack messages."
          integrations={[
            { id: "clickup", label: "ClickUp" },
            { id: "asana", label: "Asana" },
            { id: "gmail", label: "Gmail" },
            { id: "googlecalendar", label: "Calendar" },
            { id: "slack", label: "Slack" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={PORTFOLIO_BRIEF_MESSAGES} />
        </div>
      </section>

      {/* Section 3: Client Reports */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Client Reports"
          headline="Reports that write themselves. On schedule."
          description="Every week, GAIA pulls project progress from ClickUp or Asana, compiles the key metrics, and drafts the client status report in your agency's format. Consistent, professional, every time."
          integrations={[
            { id: "clickup", label: "ClickUp" },
            { id: "asana", label: "Asana" },
            { id: "gmail", label: "Gmail" },
            { id: "googlesheets", label: "Sheets" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={CLIENT_REPORT_MESSAGES} />
        </div>
      </section>

      {/* Section 4: Business Development */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Business Development"
          headline="Your pipeline doesn't stop when delivery gets busy."
          description="GAIA triages inbound leads, researches prospects from LinkedIn and Perplexity, and drafts initial responses — so your new business development keeps moving even during your heaviest delivery weeks."
          integrations={[
            { id: "hubspot", label: "HubSpot" },
            { id: "gmail", label: "Gmail" },
            { id: "linkedin", label: "LinkedIn" },
            { id: "perplexity", label: "Perplexity" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={BD_PIPELINE_MESSAGES} />
        </div>
      </section>

      {/* Section 5: Ops in Slack */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Ops in Slack"
          labelIcon={<SlackIcon />}
          headline="Your whole agency. Answered in Slack."
          description="Ask @GAIA about any client, any project status, or any deadline from your Slack channel. It answers from ClickUp, Asana, Gmail, and HubSpot instantly. No tool-switching, no chasing updates."
          integrations={[
            { id: "slack", label: "Slack" },
            { id: "clickup", label: "ClickUp" },
            { id: "asana", label: "Asana" },
            { id: "gmail", label: "Gmail" },
            { id: "hubspot", label: "HubSpot" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <AgencySlackDemo />
        </div>
      </section>

      {/* Section 6: On Autopilot */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="On Autopilot"
          headline="Tell GAIA once. It runs your agency every week."
          description="Weekly client reports every Friday. Portfolio brief every Monday morning. BD pipeline review every Thursday. Tell GAIA once — it connects ClickUp, Gmail, and your sheets, and delivers every time. You never build another status email from scratch."
          integrations={[
            { id: "clickup", label: "ClickUp" },
            { id: "gmail", label: "Gmail" },
            { id: "googlesheets", label: "Sheets" },
            { id: "slack", label: "Slack" },
            { id: "hubspot", label: "HubSpot" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <AgencyWorkflowsDemo />
        </div>
      </section>

      {/* FAQ */}
      <section className="mx-auto w-full max-w-3xl px-6 py-20 sm:py-28">
        <h2 className="mb-2 text-center font-serif text-4xl font-normal text-white sm:text-5xl">
          Frequently asked questions
        </h2>
        <p className="mb-10 text-center text-zinc-400">
          Everything you need to know about GAIA for agency owners.
        </p>
        <FAQAccordion faqs={AGENCY_FAQS} />
      </section>

      <FinalSection />
    </div>
  );
}
