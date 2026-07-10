export interface FirstStepDefinition {
  key: string;
  label: string;
  href: string;
}

// Ordered activation checklist shown in the FirstStepsWidget. Order matches
// the product spec (openspec/changes/daily-briefing-self-executing-todos).
export const FIRST_STEPS: FirstStepDefinition[] = [
  { key: "explore_workflows", label: "Explore workflows", href: "/workflows" },
  {
    key: "connect_integration",
    label: "Connect an integration",
    href: "/integrations",
  },
  {
    key: "link_telegram",
    label: "Link Telegram",
    href: "/settings/linked-accounts",
  },
  {
    key: "visit_dashboard",
    label: "Check your Today view",
    href: "/dashboard",
  },
  {
    key: "first_approve",
    label: "Approve your first GAIA todo",
    href: "/todos",
  },
];
