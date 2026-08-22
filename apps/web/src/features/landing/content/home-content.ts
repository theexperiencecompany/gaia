/**
 * Single source of truth for homepage copy.
 *
 * Every string here is rendered verbatim by the live homepage components
 * (which import it back), and is consumed by non-DOM variants of the page
 * (e.g. the markdown mirror) — so keep it plain text: no markup, no JSX,
 * no trailing whitespace. When homepage copy changes, change it HERE and
 * let the components pick it up.
 */
export interface HomeCta {
  label: string;
  href: string;
}

export interface HomeSection {
  id: string;
  heading: string;
  description: string;
}

export interface HomeContent {
  metaTitle: string;
  heroEyebrow: string;
  heroTitle: string;
  heroSubtitle: string;
  heroCtas: HomeCta[];
  sections: HomeSection[];
}

/**
 * The hero headline is designed as a fixed two-line lockup
 * ("Get a workday back" / "every week"). `heroTitle` holds the canonical
 * single-line sentence; this array holds its display lines. Kept adjacent
 * on purpose — `join(" ")` must equal `HOME_CONTENT.heroTitle` (test-enforced).
 */
export const HERO_TITLE_LINES = ["Get a workday back", "every week"] as const;

export const HOME_CONTENT: HomeContent = {
  // Mirrors `siteConfig.name` (the <title>) without importing SEO config
  // into a pure-content module.
  metaTitle: "GAIA - Your Personal AI Assistant",
  // The hero has no statically rendered kicker (the release pill above the
  // headline is dynamic); this is the brand descriptor used for text-only
  // variants of the page.
  heroEyebrow: "Your Personal AI Assistant",
  heroTitle: "Get a workday back every week",
  heroSubtitle:
    "GAIA watches your inbox, calendar, and tools and acts before you ask.",
  heroCtas: [{ label: "Sign Up", href: "/signup" }],
  sections: [
    {
      id: "runs-your-day",
      heading: "Your day runs itself",
      description:
        "One briefing in the morning, one tap to approve. GAIA works through your inbox, calendar, and tasks while you do the real work.",
    },
    {
      id: "integrations",
      heading: "Every tool. One assistant.",
      description:
        "Plug in your stack once. GAIA takes action across Gmail, Slack, Notion, Calendar and 100+ more.",
    },
    {
      id: "workflows",
      heading: "Put your life on autopilot.",
      description:
        "Tell GAIA what to automate in plain language. Set a schedule or a trigger and it runs the steps across your tools. No code.",
    },
    {
      id: "memory",
      heading: "It remembers, so you don't",
      description:
        "Say something once and GAIA files it away, then acts on it at exactly the right moment, even weeks later.",
    },
    {
      id: "bots",
      heading: "Reach GAIA from anywhere",
      description:
        "No new app to learn. Just open the one you already have open.",
    },
    {
      id: "use-cases",
      heading: "If you do it, GAIA can automate it",
      description:
        "Browse real examples of the work GAIA automates across roles and tools.",
    },
    {
      id: "open-source",
      heading: "Your data stays yours",
      description:
        "GAIA is fully open source. Run it on your own server, audit every line of code, and never worry about your data being sold or misused.",
    },
    {
      id: "pricing",
      heading: "$1 a day to never work again.",
      description: "Free to start. The cheapest hire you'll ever make.",
    },
    {
      id: "faq",
      heading: "FAQ",
      description: "Answers to the most common questions about using GAIA.",
    },
    {
      id: "get-started",
      heading: "Stop doing everything yourself",
      description:
        "Join thousands of professionals who gave their grunt work to GAIA.",
    },
  ],
};

/** Look up a homepage section by id. Throws on unknown ids — fail loud. */
export function getHomeSection(id: string): HomeSection {
  const section = HOME_CONTENT.sections.find((s) => s.id === id);
  if (!section) {
    throw new Error(`Unknown home section id: "${id}"`);
  }
  return section;
}
