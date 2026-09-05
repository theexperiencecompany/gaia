export interface FirstStepDefinition {
  key: string;
  label: string;
  href: string;
}

// Ordered activation checklist shown in the FirstStepsWidget. Each step maps to
// a real signal the backend tracks (a stated goal, an integration, a linked
// chat platform, the first Approve).
// Dismissing the whole widget is recorded as this pseudo-step, which the
// backend reports back as `dismissed` (it is not a checklist row).
export const DISMISS_ALL_STEP = "dismissed_all";

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
    key: "first_approve",
    label: "Approve your first GAIA todo",
    href: "/todos",
  },
];
