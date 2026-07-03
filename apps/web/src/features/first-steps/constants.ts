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
  { key: "visit_dashboard", label: "Meet Mission Control", href: "/dashboard" },
  {
    key: "first_approve",
    label: "Approve your first GAIA todo",
    href: "/todos",
  },
];

// Steps whose completion is derived purely from visiting their route — handled
// by useTrackRouteVisit on the target page, not by clicking the widget's link.
export const ROUTE_VISIT_STEP_KEYS = ["explore_workflows", "visit_dashboard"];

// Special step value PATCHed to mark the entire widget dismissed, independent
// of individual step completion.
export const DISMISSED_ALL_STEP = "dismissed_all";
