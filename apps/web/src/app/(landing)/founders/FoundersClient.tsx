"use client";

import ChatDemo from "@/features/landing/components/demo/founders-demo/ChatDemo";
import {
  BRIEFING_MESSAGES,
  INVESTOR_MESSAGES,
  PIPELINE_MESSAGES,
} from "@/features/landing/components/demo/founders-demo/foundersDemoConstants";
import Hero from "@/features/landing/components/demo/founders-demo/Hero";
import SectionHeader from "@/features/landing/components/demo/founders-demo/SectionHeader";
import SlackDemo from "@/features/landing/components/demo/founders-demo/SlackDemo";
import WorkflowsDemo from "@/features/landing/components/demo/founders-demo/WorkflowsDemo";
import FinalSection from "@/features/landing/components/sections/FinalSection";

export default function FoundersClient() {
  return (
    <div className="w-full">
      <Hero />

      {/* Morning Briefing */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Daily Briefing"
          headline="Start every day knowing exactly what matters."
          description="GAIA pulls from your inbox, calendar, Slack, and project boards overnight — so you wake up to a single brief, not 47 tabs."
          integrations={[
            { id: "gmail", label: "Gmail" },
            { id: "googlecalendar", label: "Calendar" },
            { id: "slack", label: "Slack" },
            { id: "github", label: "GitHub" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={BRIEFING_MESSAGES} minHeight={380} />
        </div>
      </section>

      {/* Investor Relations */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Investor Relations"
          headline="Never send an investor update late again."
          description="GAIA drafts your monthly update from live metrics, tracks every investor conversation, and makes sure no warm intro goes cold."
          integrations={[
            { id: "googlesheets", label: "Sheets" },
            { id: "gmail", label: "Gmail" },
            { id: "notion", label: "Notion" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={INVESTOR_MESSAGES} minHeight={400} />
        </div>
      </section>

      {/* Team Operations */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Team Ops"
          headline="Run standups, track blockers, and ship — without the meetings."
          description="GAIA lives in your Slack, syncs with GitHub and Linear, and gives your team answers from your docs — no context switching required."
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
          description="GAIA monitors your CRM, flags deals that need attention, drafts follow-ups, and surfaces churn signals — so nothing slips through the cracks."
          integrations={[
            { id: "hubspot", label: "HubSpot" },
            { id: "gmail", label: "Gmail" },
            { id: "linkedin", label: "LinkedIn" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={PIPELINE_MESSAGES} minHeight={380} />
        </div>
      </section>

      {/* On Autopilot */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="On Autopilot"
          headline="Set it once. It runs while you sleep."
          description="Daily briefings at 9am. Weekly investor digests. Monthly board prep. Tell GAIA what you need once — it builds the workflow, connects the tools, and runs on schedule."
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

      <FinalSection />
    </div>
  );
}
