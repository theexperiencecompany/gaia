export interface FirstStepDefinition {
  key: string;
  label: string;
  href: string;
}

// Ordered activation checklist shown in the FirstStepsWidget. Each step maps to
// a real signal the backend tracks (a stated goal, an integration, a linked
// chat platform, the Today view, the first Approve).
export const FIRST_STEPS: FirstStepDefinition[] = [
  { key: "tell_gaia_goal", label: "Tell GAIA your goal", href: "/c" },
  {
    key: "connect_integration",
    label: "Connect an integration",
    href: "/integrations",
  },
  {
    key: "link_platform",
    label: "Link Telegram or WhatsApp",
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
