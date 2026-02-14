"use client";

import { ZapIcon } from "@/components";
import WorkflowDemoAnimation from "../demo/workflow-demo/WorkflowDemoAnimation";

const CONTENT_SECTIONS = [
  {
    title: "Set it once, runs forever",
    description:
      "Describe what you want automated. GAIA builds the steps, sets the trigger, and runs on repeat. Morning briefings, receipt forwarding, meeting prep: handled.",
  },
  {
    title: "Runs when you need it. Not when you remember it.",
    description:
      "Schedule it for 9 AM every morning, or trigger it from an incoming email, a Slack message, or an upcoming meeting.",
  },
  // {
  //   title: "Powered by Your Todos",
  //   description:
  //     "Every todo you add becomes its own mini-workflow. GAIA doesn't just remind you — it actually does the work. Research, drafting, scheduling — done.",
  // },
  {
    title: "One workflow. Your whole stack.",
    description:
      "Gmail, Google Docs, Slack, Calendar. One workflow connects them all. Pull from your inbox, write a doc, schedule a meeting, ping your team. Done.",
  },
];

export default function WorkflowShowcaseSection() {
  return (
    <div className="relative mx-auto mb-8 sm:mb-16 lg:mb-20 flex w-full flex-col justify-center px-6 sm:px-6">
      {/* Header */}
      <div className="mb-5 text-xl font-light text-primary sm:text-2xl text-center lg:text-left">
        Kill the Busywork
      </div>
      <div className="mb-8 font-serif text-4xl font-normal sm:text-5xl text-center lg:text-left">
        Your daily busywork, handled without lifting a finger
      </div>

      {/* 70/30 split */}
      <div className="flex flex-col gap-6 lg:flex-row lg:gap-8">
        {/* Left: 70% — Animation showcase */}
        <div className="w-full lg:w-[70%]">
          <WorkflowDemoAnimation />
        </div>

        {/* Right: 30% — Text sidebar */}
        <div className="flex w-full flex-col justify-end gap-7 lg:w-[25%] pb-[52px]">
          <div className="flex items-center text-4xl font-serif gap-2 text-foreground-400">
            <ZapIcon width={40} height={40} /> Workflows
          </div>
          {CONTENT_SECTIONS.map((section) => (
            <div key={section.title}>
              <h3 className="mb-2 text-xl font-medium text-zinc-100">
                {section.title}
              </h3>
              <p className="text-base font-light leading-relaxed text-zinc-400 text-justify">
                {section.description}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
