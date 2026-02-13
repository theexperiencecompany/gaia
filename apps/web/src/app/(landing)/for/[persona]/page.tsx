import { Chip } from "@heroui/chip";
import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import FAQAccordion from "@/components/seo/FAQAccordion";
import JsonLd from "@/components/seo/JsonLd";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import {
  getAllPersonaSlugs,
  getPersona,
  type PersonaData,
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

export async function generateStaticParams() {
  return getAllPersonaSlugs().map((persona) => ({ persona }));
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { persona } = await params;
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
