"use client";

import { Chip } from "@heroui/chip";
import { m } from "motion/react";
import Image from "next/image";
import FAQAccordion from "@/components/seo/FAQAccordion";
import ProgressiveImage from "@/components/ui/ProgressiveImage";
import ChatDemo from "@/features/landing/components/demo/founders-demo/ChatDemo";
import SectionHeader from "@/features/landing/components/demo/founders-demo/SectionHeader";
import { PMSlackDemo } from "@/features/landing/components/demo/pm-demo/PMSlackDemo";
import { PMWorkflowsDemo } from "@/features/landing/components/demo/pm-demo/PMWorkflowsDemo";
import {
  FEATURE_TRIAGE_MESSAGES,
  PM_PROACTIVE_MESSAGES,
  PRODUCT_BRIEF_MESSAGES,
  STAKEHOLDER_MESSAGES,
} from "@/features/landing/components/demo/pm-demo/pmDemoConstants";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import GetStartedButton from "@/features/landing/components/shared/GetStartedButton";
import { PM_FAQS } from "@/features/landing/data/personaFaqs";

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

export default function ProductManagerClient() {
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
            For Product Managers
          </Chip>
        </m.div>
        <m.h1
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease, delay: 0.1 }}
          className="font-serif relative z-10 mb-6 max-w-4xl text-5xl font-normal leading-[1.1] text-white sm:text-6xl md:text-7xl"
        >
          Stop managing tools.
          <br />
          Start managing your product.
        </m.h1>
        <m.p
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease, delay: 0.2 }}
          className="relative z-10 mb-10 max-w-2xl text-xl font-light leading-relaxed text-white"
        >
          GAIA handles the status updates, meeting prep, and feature triage — so
          you can spend your time on the decisions that actually matter.
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
          headline="GAIA keeps the pulse so you keep the vision."
          description="Stop spending half your day as a human status router. GAIA monitors your sprint progress, Slack threads, and customer signals in the background — and surfaces what needs a decision, not a dashboard."
          integrations={[
            { id: "linear", label: "Linear" },
            { id: "slack", label: "Slack" },
            { id: "github", label: "GitHub" },
            { id: "gmail", label: "Gmail" },
            { id: "notion", label: "Notion" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={PM_PROACTIVE_MESSAGES} minHeight={340} />
        </div>
      </section>

      {/* Section 2 — Product Brief */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Product Brief"
          headline="Your full picture. Before your first meeting."
          description="Every morning, GAIA compiles sprint progress, deployment status, and team blockers from Linear, GitHub, and Slack — and delivers one crisp brief. Walk into every meeting knowing where things stand."
          integrations={[
            { id: "linear", label: "Linear" },
            { id: "github", label: "GitHub" },
            { id: "slack", label: "Slack" },
            { id: "googlecalendar", label: "Calendar" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={PRODUCT_BRIEF_MESSAGES} minHeight={400} />
        </div>
      </section>

      {/* Section 3 — Stakeholder Updates */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Stakeholder Updates"
          headline="Write once. Never rewrite it."
          description="GAIA pulls sprint velocity, deployment status, and key wins from Linear and GitHub — then drafts your stakeholder update in the format your audience expects. One review, done."
          integrations={[
            { id: "linear", label: "Linear" },
            { id: "github", label: "GitHub" },
            { id: "gmail", label: "Gmail" },
            { id: "notion", label: "Notion" },
            { id: "slack", label: "Slack" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={STAKEHOLDER_MESSAGES} minHeight={420} />
        </div>
      </section>

      {/* Section 4 — Feature Triage */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Feature Triage"
          headline="Every customer signal. Captured and categorized."
          description="Feature requests scatter across Slack, email, and support tickets. GAIA captures every signal, groups by theme, and creates structured Linear tickets with full context — before your next roadmap review."
          integrations={[
            { id: "slack", label: "Slack" },
            { id: "gmail", label: "Gmail" },
            { id: "linear", label: "Linear" },
            { id: "notion", label: "Notion" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ChatDemo messages={FEATURE_TRIAGE_MESSAGES} minHeight={400} />
        </div>
      </section>

      {/* Section 5 — Product Ops (Slack) */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Product Ops"
          labelIcon={<SlackIcon />}
          headline="Your team gets product answers. You stay in flow."
          description="Ask @GAIA about any ticket, sprint status, or roadmap question in Slack — it answers from Linear, GitHub, and Notion instantly. No DMs, no interruptions, no meetings to answer simple questions."
          integrations={[
            { id: "slack", label: "Slack" },
            { id: "linear", label: "Linear" },
            { id: "github", label: "GitHub" },
            { id: "notion", label: "Notion" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <PMSlackDemo />
        </div>
      </section>

      {/* Section 6 — On Autopilot */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="On Autopilot"
          headline="Your product operations. Running themselves."
          description="Weekly stakeholder updates every Friday. Sprint status to Slack every Monday morning. Feature digest after every sprint. Tell GAIA once — it connects Linear, GitHub, and Notion, and runs the workflow every time."
          integrations={[
            { id: "linear", label: "Linear" },
            { id: "github", label: "GitHub" },
            { id: "notion", label: "Notion" },
            { id: "slack", label: "Slack" },
            { id: "gmail", label: "Gmail" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <PMWorkflowsDemo />
        </div>
      </section>

      {/* FAQ */}
      <section className="mx-auto w-full max-w-3xl px-6 py-20 sm:py-28">
        <h2 className="mb-2 text-center font-serif text-4xl font-normal text-white sm:text-5xl">
          Frequently asked questions
        </h2>
        <p className="mb-10 text-center text-zinc-400">
          Everything you need to know about GAIA for product managers.
        </p>
        <FAQAccordion faqs={PM_FAQS} />
      </section>

      <FinalSection />
    </div>
  );
}
