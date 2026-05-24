"use client";

import { WorkflowsDemoBase } from "../../demo/WorkflowsDemoBase";
import { WORKFLOW_DEMO_CONFIGS } from "./workflowDemoData";

const config = WORKFLOW_DEMO_CONFIGS["scheduled-automation"];

export default function ScheduledAutomationDemo() {
  return (
    <WorkflowsDemoBase
      title={config.title}
      schedule={config.schedule}
      steps={config.steps}
    />
  );
}
