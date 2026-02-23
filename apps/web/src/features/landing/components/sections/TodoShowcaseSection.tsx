"use client";

import { CheckListIcon } from "@icons";
import TodoDemoAnimation from "../demo/todo-demo/TodoDemoAnimation";
import ShowcaseSectionLayout from "./ShowcaseSectionLayout";
import ShowcaseSidebarContent from "./ShowcaseSidebarContent";

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
    <ShowcaseSectionLayout
      header="Your tasks, on autopilot"
      subheader="The to-do list that works while you don't"
      DemoComponent={<TodoDemoAnimation />}
      SidebarContent={
        <ShowcaseSidebarContent
          sidebarIcon={<CheckListIcon width={30} height={30} />}
          sidebarTitle="Todos"
          contentSections={CONTENT_SECTIONS}
        />
      }
      containerClassName="relative mx-auto mb-8 sm:mb-16 lg:mb-20 flex w-full flex-col justify-center px-6 sm:px-4"
      sidebarClassName="flex w-full flex-col justify-end gap-7 lg:w-[25%] pb-13"
    />
  );
}
