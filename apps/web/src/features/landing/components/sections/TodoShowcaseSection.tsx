"use client";

import TodoDemoAnimation from "../demo/todo-demo/TodoDemoAnimation";

const CONTENT_SECTIONS = [
  {
    title: "Describe it once, skip the setup",
    description:
      "Type a task and GAIA understands the full scope — priority, deadline, who to loop in. No forms, no menus, just describe what you need done.",
  },
  {
    title: "Every todo becomes a workflow",
    description:
      "GAIA doesn't just remind you. It suggests a step-by-step workflow for each task — pulling data, creating docs, notifying teammates — and runs it when you say so.",
  },
  {
    title: "Close the loop automatically",
    description:
      "When the workflow finishes, the todo is marked done. No chasing tabs, no copy-pasting — the task and the work are one thing.",
  },
];

export default function TodoShowcaseSection() {
  return (
    <div className="relative mx-auto mb-20 flex w-full flex-col justify-center px-[4em]">
      <div className="mb-2 text-xl font-light text-primary sm:text-2xl">
        Your Tasks, Actually Done
      </div>
      <div className="mb-8 font-serif text-4xl font-normal sm:text-5xl">
        Todos that work for you
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
