"use client";

import WorkflowDemoAnimation from "../demo/workflow-demo/WorkflowDemoAnimation";

const CONTENT_SECTIONS = [
  {
    title: "Set it once, runs forever",
    description:
      "Build a workflow once and GAIA runs it automatically — every day, every time. From forwarding receipts to your accountant, to researching every person you're meeting and sending you a briefing doc an hour before.",
  },
  {
    title: "Runs on your schedule, not a reminder",
    description:
      "Set it to run every morning at 9 AM, trigger it when you get an email, a Slack message pops up, or your next meeting's about to start.",
  },
  // {
  //   title: "Powered by Your Todos",
  //   description:
  //     "Every todo you add becomes its own mini-workflow. GAIA doesn't just remind you — it actually does the work. Research, drafting, scheduling — done.",
  // },
  {
    title: "One command moves everything",
    description:
      "Gmail, Google Docs, Slack, Calendar — they all talk to each other now. One workflow can pull info from your email, create a doc, schedule a meeting, and ping your team.",
  },
];

export default function WorkflowShowcaseSection() {
  return (
    <div className="relative mx-auto mb-20 flex w-full flex-col justify-center px-[4em]">
      {/* Header */}
      <div className="mb-2 text-xl font-light text-primary sm:text-2xl">
        Kill the Busywork
      </div>
      <div className="mb-8 font-serif text-4xl font-normal sm:text-5xl">
        Your most draining tasks, handled without you
      </div>

      {/* 70/30 split */}
      <div className="flex flex-col gap-6 lg:flex-row lg:gap-8">
        {/* Left: 70% — Animation showcase */}
        <div className="w-full lg:w-[70%]">
          <WorkflowDemoAnimation />
        </div>

        {/* Right: 30% — Text sidebar */}
        <div className="flex w-full flex-col justify-end gap-7 lg:w-[25%] pb-[52px]">
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
