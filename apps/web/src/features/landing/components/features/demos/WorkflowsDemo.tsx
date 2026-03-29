"use client";

import { WorkflowsDemoBase } from "../../demo/WorkflowsDemoBase";
import { WORKFLOW_DEMO_CONFIGS } from "./workflowDemoData";

const config = WORKFLOW_DEMO_CONFIGS.workflows;

export default function WorkflowsDemo() {
  return (
    <WorkflowsDemoBase
      title={config.title}
      schedule={config.schedule}
      steps={config.steps}
    />
  );
}
