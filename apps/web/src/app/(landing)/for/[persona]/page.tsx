import { Chip } from "@heroui/chip";
import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { ComponentType } from "react";
import FAQAccordion from "@/components/seo/FAQAccordion";
import JsonLd from "@/components/seo/JsonLd";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import {
  AGENCY_FAQS,
  EM_FAQS,
  FOUNDERS_FAQS,
  PM_FAQS,
  SALES_FAQS,
  SOFTWARE_DEV_FAQS,
} from "@/features/landing/data/personaFaqs";
import {
  getAllPersonaSlugs,
  getPersona,
} from "@/features/personas/data/personasData";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

interface PageProps {
  params: Promise<{ persona: string }>;
}

interface PersonaConfig {
  metaTitle: string;
  metaDescription: string;
  schemaDescription: string;
  keywords: string[];
  breadcrumbName: string;
  faqs: { question: string; answer: string }[];
  getClient: () => Promise<{ default: ComponentType }>;
}

const SPECIAL_PERSONA_CONFIGS: Record<string, PersonaConfig> = {
  "startup-founders": {
    metaTitle:
      "GAIA for Startup Founders — AI Chief of Staff & Proactive Automation",
    metaDescription:
      "GAIA connects to your email, Slack, calendar, CRM, GitHub, and 30+ tools — then handles the operational work so you can focus on building. Save 8-12 hours every week.",
    schemaDescription:
      "GAIA connects to your email, Slack, calendar, CRM, GitHub, and 30+ tools — then handles the operational work so you can focus on building.",
    keywords: [
      "AI for founders",
      "startup AI assistant",
      "AI chief of staff",
      "founder productivity",
      "investor update automation",
      "workflow automation for startups",
      "startup operations",
      "AI CRM assistant",
      "AI that writes investor updates automatically",
      "proactive AI assistant for startup founders",
      "automate morning briefing for founders",
      "startup operations automation without hiring",
      "best AI assistant for solo founders",
      "AI that monitors Slack for founders",
      "replace EA with AI startup",
      "AI for managing SaaS tool overload",
      "how to automate investor relations startup",
      "founder daily briefing automation",
      "AI personal assistant for entrepreneurs",
    ],
    breadcrumbName: "AI Assistant for Startup Founders",
    faqs: FOUNDERS_FAQS,
    getClient: () => import("@/app/(landing)/founders/FoundersClient"),
  },
  "software-developers": {
    metaTitle:
      "GAIA for Software Developers — AI Standup Generator & GitHub Automation",
    metaDescription:
      "GAIA connects to GitHub, Linear, and Slack — then writes your standup, triages your PRs, and monitors production so you stay in deep work longer.",
    schemaDescription:
      "GAIA connects to GitHub, Linear, and Slack — then writes your standup, triages your PRs, and monitors production so you stay in deep work longer.",
    keywords: [
      "AI assistant for developers",
      "developer productivity tool",
      "GitHub automation",
      "automated standup generator",
      "Linear AI integration",
      "PR review automation",
      "coding workflow AI",
      "developer daily briefing",
      "AI standup generator for developers",
      "automate GitHub PR triage",
      "daily briefing for software engineers",
      "reduce context switching developer AI",
      "GitHub Linear Slack AI integration",
      "developer workflow automation 2025",
      "AI that writes standup reports automatically",
      "production incident monitoring AI developer",
      "deep work AI assistant developer",
    ],
    breadcrumbName: "AI Assistant for Software Developers",
    faqs: SOFTWARE_DEV_FAQS,
    getClient: () =>
      import("@/app/(landing)/software-developers/SoftwareDevClient"),
  },
  "sales-professionals": {
    metaTitle:
      "GAIA for Sales Professionals — AI CRM Monitor & Follow-Up Automation",
    metaDescription:
      "GAIA monitors your HubSpot pipeline, drafts follow-ups before deals go cold, and preps you for every call — automatically. Spend more time selling.",
    schemaDescription:
      "GAIA monitors your HubSpot pipeline, drafts follow-ups before deals go cold, and preps you for every call — automatically.",
    keywords: [
      "AI assistant for sales",
      "CRM automation AI",
      "sales follow-up automation",
      "HubSpot AI integration",
      "sales meeting prep tool",
      "pipeline management AI",
      "deal intelligence tool",
      "sales productivity automation",
      "AI that monitors HubSpot pipeline automatically",
      "prevent deals going cold AI",
      "automate sales follow-up emails AI",
      "AI sales meeting prep tool",
      "CRM AI assistant for sales reps",
      "sales pipeline monitoring automation",
      "HubSpot proactive AI assistant",
      "AI for closing more deals",
      "automatic CRM logging AI",
    ],
    breadcrumbName: "AI Assistant for Sales Professionals",
    faqs: SALES_FAQS,
    getClient: () => import("@/app/(landing)/sales-professionals/SalesClient"),
  },
  "product-managers": {
    metaTitle:
      "GAIA for Product Managers — Automate Stakeholder Updates & Sprint Reports",
    metaDescription:
      "GAIA connects Linear, GitHub, Slack, and Notion — then handles stakeholder updates, feature triage, and sprint reporting so you can focus on product strategy.",
    schemaDescription:
      "GAIA connects Linear, GitHub, Slack, and Notion — then handles stakeholder updates, feature triage, and sprint reporting so you can focus on product strategy.",
    keywords: [
      "AI assistant for product managers",
      "PM productivity tool",
      "stakeholder update automation",
      "Linear AI integration",
      "feature request triage AI",
      "sprint reporting automation",
      "product brief generator",
      "roadmap management AI",
      "AI that writes stakeholder updates automatically",
      "automate sprint reports product manager",
      "feature request triage AI tool",
      "Linear GitHub AI integration PM",
      "sprint reporting automation 2025",
      "AI for product planning",
      "product manager workflow automation",
      "automated product brief generator",
    ],
    breadcrumbName: "AI Assistant for Product Managers",
    faqs: PM_FAQS,
    getClient: () =>
      import("@/app/(landing)/product-managers/ProductManagerClient"),
  },
  "engineering-managers": {
    metaTitle:
      "GAIA for Engineering Managers — 1:1 Prep, Sprint Reports & Team Analytics",
    metaDescription:
      "GAIA monitors GitHub, Linear, and Slack so you don't have to. It preps your 1:1s, builds sprint reports, and surfaces blockers — automatically.",
    schemaDescription:
      "GAIA monitors GitHub, Linear, and Slack so you don't have to. It preps your 1:1s, builds sprint reports, and surfaces blockers — automatically.",
    keywords: [
      "AI assistant for engineering managers",
      "EM productivity tool",
      "sprint reporting automation",
      "1:1 preparation AI",
      "GitHub team analytics",
      "PR cycle time tracking",
      "engineering leadership tool",
      "team velocity monitoring",
      "AI for engineering manager 1:1 prep",
      "automated sprint reporting engineering manager",
      "PR cycle time monitoring AI",
      "team velocity tracking automation",
      "GitHub analytics for engineering managers",
      "engineering team blocker detection AI",
      "AI for technical leadership",
      "engineering manager workflow automation",
    ],
    breadcrumbName: "AI Assistant for Engineering Managers",
    faqs: EM_FAQS,
    getClient: () =>
      import("@/app/(landing)/engineering-managers/EngineeringManagerClient"),
  },
  "agency-owners": {
    metaTitle:
      "GAIA for Agency Owners — Automate Client Reports & Portfolio Management",
    metaDescription:
      "GAIA monitors every client project, writes your weekly status reports, and keeps your pipeline active — automatically. Scale your agency without scaling your overhead.",
    schemaDescription:
      "GAIA monitors every client project, writes your weekly status reports, and keeps your pipeline active — automatically.",
    keywords: [
      "AI assistant for agency owners",
      "agency management automation",
      "client reporting automation",
      "ClickUp AI integration",
      "Asana AI assistant",
      "agency portfolio management",
      "automated client reports",
      "digital agency productivity tool",
      "AI for digital agency client reporting",
      "automate agency status reports AI",
      "ClickUp Asana AI assistant agency",
      "client portfolio management AI",
      "scale agency without hiring AI",
      "automated client status updates agency",
      "AI for managing multiple clients",
      "agency project management automation",
    ],
    breadcrumbName: "AI Assistant for Agency Owners",
    faqs: AGENCY_FAQS,
    getClient: () => import("@/app/(landing)/agency-owners/AgencyClient"),
  },
};

export async function generateStaticParams() {
  return getAllPersonaSlugs().map((persona) => ({ persona }));
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { persona } = await params;

  const config = SPECIAL_PERSONA_CONFIGS[persona];
  if (config) {
    return generatePageMetadata({
      title: config.metaTitle,
      description: config.metaDescription,
      path: `/for/${persona}`,
      keywords: config.keywords,
    });
  }

  const data = getPersona(persona);

  if (!data) {
    return { title: "Role Not Found" };
  }

  return generatePageMetadata({
    title: data.metaTitle,
    description: data.metaDescription,
    path: `/for/${persona}`,
    keywords: data.keywords,
  });
}

function IntegrationBadge({ name }: { name: string }) {
  const displayName = name
    .split("-")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");

  const domainMap: Record<string, string> = {
    github: "github.com",
    linear: "linear.app",
    slack: "slack.com",
    "google-calendar": "calendar.google.com",
    gmail: "gmail.com",
    notion: "notion.so",
    todoist: "todoist.com",
    perplexity: "perplexity.ai",
    deepwiki: "deepwiki.com",
    context7: "context7.com",
    figma: "figma.com",
    jira: "jira.atlassian.com",
    asana: "asana.com",
    trello: "trello.com",
    hubspot: "hubspot.com",
    salesforce: "salesforce.com",
    intercom: "intercom.com",
    zendesk: "zendesk.com",
    stripe: "stripe.com",
    quickbooks: "quickbooks.intuit.com",
    "google-docs": "docs.google.com",
    "google-sheets": "sheets.google.com",
    "google-drive": "drive.google.com",
    dropbox: "dropbox.com",
    airtable: "airtable.com",
    monday: "monday.com",
    clickup: "clickup.com",
    discord: "discord.com",
    zoom: "zoom.us",
    teams: "teams.microsoft.com",
    outlook: "outlook.com",
    twitter: "x.com",
    linkedin: "linkedin.com",
    mailchimp: "mailchimp.com",
    "google-analytics": "analytics.google.com",
    semrush: "semrush.com",
    canva: "canva.com",
    wordpress: "wordpress.com",
    shopify: "shopify.com",
    amplitude: "amplitude.com",
    mixpanel: "mixpanel.com",
    datadog: "datadoghq.com",
    sentry: "sentry.io",
    vercel: "vercel.com",
    netlify: "netlify.com",
    aws: "aws.amazon.com",
    "google-cloud": "cloud.google.com",
    confluence: "confluence.atlassian.com",
  };

  const domain = domainMap[name];

  return (
    <Chip
      variant="flat"
      size="md"
      className="bg-zinc-800 text-zinc-300"
      startContent={
        domain ? (
          <Image
            src={`https://www.google.com/s2/favicons?domain=${domain}&sz=128`}
            alt={displayName}
            width={16}
            height={16}
            className="ml-1 rounded-sm"
            unoptimized
          />
        ) : undefined
      }
    >
      {displayName}
    </Chip>
  );
}

export default async function PersonaPage({ params }: PageProps) {
  const { persona } = await params;

  const config = SPECIAL_PERSONA_CONFIGS[persona];
  if (config) {
    const breadcrumbs = [
      { name: "Home", url: siteConfig.url },
      { name: "GAIA for Every Role", url: `${siteConfig.url}/for` },
      { name: config.breadcrumbName, url: `${siteConfig.url}/for/${persona}` },
    ];
    const { default: Client } = await config.getClient();
    return (
      <>
        <JsonLd
          data={[
            generateWebPageSchema(
              config.metaTitle,
              config.schemaDescription,
              `${siteConfig.url}/for/${persona}`,
              breadcrumbs,
            ),
            generateBreadcrumbSchema(breadcrumbs),
            generateFAQSchema(config.faqs),
          ]}
        />
        <Client />
      </>
    );
  }

  const data = getPersona(persona);

  if (!data) {
    notFound();
  }

  const breadcrumbs = [
    { name: "Home", url: siteConfig.url },
    { name: "GAIA for Every Role", url: `${siteConfig.url}/for` },
    {
      name: `AI Assistant for ${data.role}`,
      url: `${siteConfig.url}/for/${persona}`,
    },
  ];

  const webPageSchema = generateWebPageSchema(
    data.metaTitle,
    data.metaDescription,
    `${siteConfig.url}/for/${persona}`,
    breadcrumbs,
  );

  const breadcrumbSchema = generateBreadcrumbSchema(breadcrumbs);
  const faqSchema = generateFAQSchema(data.faqs);

  return (
    <>
      <JsonLd data={[webPageSchema, breadcrumbSchema, faqSchema]} />

      <article className="mx-auto max-w-4xl px-6 pt-36 pb-24">
        {/* Breadcrumb */}
        <nav className="mb-8 text-sm text-zinc-500">
          <Link href="/" className="hover:text-zinc-300">
            Home
          </Link>
          <span className="mx-2">/</span>
          <Link href="/for" className="hover:text-zinc-300">
            Roles
          </Link>
          <span className="mx-2">/</span>
          <span className="text-zinc-300">AI Assistant for {data.role}</span>
        </nav>

        {/* Hero */}
        <header className="mb-16">
          <h1 className="mb-4 font-serif text-5xl font-normal text-white md:text-6xl">
            AI Assistant for {data.role}
          </h1>
          <p className="text-xl leading-relaxed text-zinc-400">
            {data.metaDescription}
          </p>
        </header>

        {/* Introduction */}
        <section className="mb-16">
          <p className="text-lg leading-relaxed text-zinc-300">{data.intro}</p>
        </section>

        {/* Pain Points */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            Challenges {data.role} Face Every Day
          </h2>
          <div className="space-y-4">
            {data.painPoints.map((point) => (
              <div
                key={point}
                className="flex items-start gap-3 rounded-2xl bg-zinc-800 p-5"
              >
                <span className="mt-0.5 shrink-0 text-red-400">*</span>
                <p className="leading-relaxed text-zinc-300">{point}</p>
              </div>
            ))}
          </div>
        </section>

        {/* How GAIA Helps */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            How GAIA Helps {data.role}
          </h2>
          <div className="grid gap-6 md:grid-cols-2">
            {data.howGaiaHelps.map((feature) => (
              <div key={feature.title} className="rounded-3xl bg-zinc-800 p-6">
                <h3 className="mb-3 text-lg font-medium text-emerald-400">
                  {feature.title}
                </h3>
                <p className="leading-relaxed text-zinc-400">
                  {feature.description}
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* Relevant Integrations */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            Integrations for {data.role}
          </h2>
          <p className="mb-6 text-zinc-400">
            GAIA connects with the tools {data.role.toLowerCase()} already use,
            creating an intelligent automation layer across your entire
            workflow.
          </p>
          <div className="flex flex-wrap gap-3">
            {data.relevantIntegrations.map((integration) => (
              <IntegrationBadge key={integration} name={integration} />
            ))}
          </div>
        </section>

        {/* FAQ */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            Frequently Asked Questions
          </h2>
          <FAQAccordion faqs={data.faqs} />
        </section>

        {/* Explore More */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            Explore More
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <Link
              href="/compare"
              className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
            >
              <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                See How GAIA Compares
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                Compare GAIA with other AI productivity tools and see why it
                stands out for {data.role.toLowerCase()}.
              </p>
            </Link>
            <Link
              href="/learn"
              className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
            >
              <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                Learn About AI Concepts
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                Explore the AI technology and concepts that power GAIA's
                intelligent automation.
              </p>
            </Link>
          </div>
        </section>
      </article>
      <FinalSection />
    </>
  );
}
