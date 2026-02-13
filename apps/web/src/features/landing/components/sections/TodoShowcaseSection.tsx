"use client";

import TodoDemoAnimation from "../demo/todo-demo/TodoDemoAnimation";

const CONTENT_SECTIONS = [
  {
    title: "Type it. GAIA figures out the rest.",
    description:
      "Describe a task in plain English. GAIA breaks it into steps, sets the priority, and builds a workflow automatically. No menus, no setup.",
  },
  {
    title: "Reminders don't cut it. GAIA actually does it.",
    description:
      "For each task, GAIA generates a step-by-step workflow: researching, drafting docs, notifying teammates. Then executes it on command.",
  },
  {
    title: "Zero follow-up required",
    description:
      "When the workflow finishes, the task closes itself. No follow-up. No copy-pasting between apps.",
  },
];

export default function TodoShowcaseSection() {
  return (
    <div className="relative mx-auto mb-8 sm:mb-16 lg:mb-20 flex w-full flex-col justify-center px-6 sm:px-4">
      <div className="mb-2 text-xl font-light text-primary sm:text-2xl text-center lg:text-left">
        Your tasks, on autopilot
      </div>
      <div className="mb-8 font-serif text-4xl font-normal sm:text-5xl text-center lg:text-left">
        The to-do list that works while you don't
      </div>

      <div className="flex flex-col gap-6 lg:flex-row lg:gap-8 lg:items-end">
        <div className="w-full lg:w-[70%]">
          <TodoDemoAnimation />
        </div>

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
