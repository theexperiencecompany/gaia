"use client";

import { ZapIcon } from "@/components";
import WorkflowDemoAnimation from "../demo/workflow-demo/WorkflowDemoAnimation";
import ShowcaseSectionLayout from "./ShowcaseSectionLayout";
import ShowcaseSidebarContent from "./ShowcaseSidebarContent";

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
  {
    title: "One workflow. Your whole stack.",
    description:
      "Gmail, Google Docs, Slack, Calendar. One workflow connects them all. Pull from your inbox, write a doc, schedule a meeting, ping your team. Done.",
  },
];

export default function WorkflowShowcaseSection() {
  return (
    <ShowcaseSectionLayout
      header="Kill the Busywork"
      subheader="Your daily busywork, handled without lifting a finger"
      DemoComponent={<WorkflowDemoAnimation />}
      SidebarContent={
        <ShowcaseSidebarContent
          sidebarIcon={<ZapIcon width={30} height={30} />}
          sidebarTitle="Workflows"
          contentSections={CONTENT_SECTIONS}
        />
      }
    />
  );
}
