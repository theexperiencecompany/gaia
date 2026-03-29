"use client";

import { WorkflowsDemoBase } from "../../demo/WorkflowsDemoBase";
import { WORKFLOW_DEMO_CONFIGS } from "./workflowDemoData";

const config = WORKFLOW_DEMO_CONFIGS["event-triggers"];

export default function EventTriggersDemo() {
  return (
    <WorkflowsDemoBase
      title={config.title}
      schedule={config.schedule}
      steps={config.steps}
    />
  );
}
