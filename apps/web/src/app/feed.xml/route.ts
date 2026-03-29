import { getAllAlternatives } from "@/features/alternatives/data/alternativesData";
import { blogApi } from "@/features/blog/api/blogApi";
import { getAllComparisons } from "@/features/comparisons/data/comparisonsData";
import { getAllGlossaryTerms } from "@/features/glossary/data/glossaryData";
import { getAllCombos } from "@/features/integrations/data/combosData";
import { FEATURES } from "@/features/landing/data/featuresData";
import { getAllPersonas } from "@/features/personas/data/personasData";
import { workflowApi } from "@/features/workflows/api/workflowApi";
import { fetchAllPaginated } from "@/lib/fetchAll";
import { siteConfig } from "@/lib/seo";
import { getServerApiBaseUrl } from "@/lib/serverApiBaseUrl";

interface FeedItem {
  title: string;
  link: string;
  description: string;
  pubDate: string;
  category: string;
}

const BUILD_DATE = new Date().toUTCString();

function escapeXml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function buildItem(item: FeedItem): string {
  return `
    <item>
      <title><![CDATA[${item.title}]]></title>
      <link>${item.link}</link>
      <guid isPermaLink="true">${item.link}</guid>
      <description><![CDATA[${item.description}]]></description>
      <pubDate>${item.pubDate}</pubDate>
      <category>${escapeXml(item.category)}</category>
    </item>`;
}

function getStaticPages(baseUrl: string): FeedItem[] {
  const pages: Array<{
    path: string;
    title: string;
    description: string;
    category: string;
  }> = [
    {
      path: "",
      title: "GAIA - Your Personal AI Assistant",
      description:
        "GAIA is your open-source personal AI assistant to proactively manage your email, calendar, todos, workflows and all your digital tools.",
      category: "Product",
    },
    {
      path: "/pricing",
      title: "Pricing",
      description:
        "Explore GAIA pricing plans. Free open-source tier, Pro, and Enterprise options for personal AI assistance.",
      category: "Product",
    },
    {
      path: "/features",
      title: "Features",
      description:
        "Explore everything GAIA can do. AI intelligence, productivity tools, workflow automation, integrations, and multi-platform support.",
      category: "Product",
    },
    {
      path: "/marketplace",
      title: "Integration Marketplace",
      description:
        "Browse community integrations for GAIA. Connect your favorite tools and automate workflows.",
      category: "Product",
    },
    {
      path: "/use-cases",
      title: "Use Cases",
      description:
        "Discover AI workflows and automation use cases powered by GAIA.",
      category: "Product",
    },
    {
      path: "/download",
      title: "Download GAIA",
      description:
        "Get GAIA for desktop, mobile, and web. Available on macOS, Windows, Linux, iOS, and Android.",
      category: "Product",
    },
    {
      path: "/blog",
      title: "GAIA Blog",
      description:
        "Read the latest updates, insights, and stories from the GAIA team about AI, productivity, and open-source development.",
      category: "Resources",
    },
    {
      path: "/cli",
      title: "Install GAIA CLI",
      description:
        "Install the GAIA CLI for self-hosting your personal AI assistant.",
      category: "Resources",
    },
    {
      path: "/compare",
      title: "Compare GAIA",
      description:
        "See how GAIA compares to other AI assistants and productivity tools.",
      category: "Resources",
    },
    {
      path: "/alternative-to",
      title: "GAIA Alternatives",
      description:
        "Discover which tools GAIA replaces and how it compares as an alternative.",
      category: "Resources",
    },
    {
      path: "/automate",
      title: "Automation Combos",
      description:
        "Automate any two tools together with GAIA. Browse integration combinations.",
      category: "Resources",
    },
    {
      path: "/learn",
      title: "Glossary",
      description:
        "AI and productivity terms explained. Learn about the concepts behind GAIA.",
      category: "Resources",
    },
    {
      path: "/for",
      title: "Built For",
      description:
        "Discover how GAIA is built for different roles and industries.",
      category: "Product",
    },
    {
      path: "/about",
      title: "About GAIA",
      description:
        "Learn about GAIA and the team building the future of personal AI assistants.",
      category: "Company",
    },
    {
      path: "/manifesto",
      title: "Our Manifesto",
      description: "The mission and vision behind GAIA.",
      category: "Company",
    },
    {
      path: "/faq",
      title: "FAQ",
      description:
        "Frequently asked questions about GAIA, the open-source personal AI assistant.",
      category: "Company",
    },
    {
      path: "/contact",
      title: "Contact",
      description: "Get in touch with the GAIA team.",
      category: "Company",
    },
    {
      path: "/brand",
      title: "Branding",
      description: "GAIA brand guidelines and downloadable assets.",
      category: "Company",
    },
    {
      path: "/open-source-ai-assistant",
      title: "Open Source AI Assistant",
      description:
        "GAIA is the open-source AI assistant that proactively manages your digital life.",
      category: "Product",
    },
    {
      path: "/ai-chief-of-staff",
      title: "AI Chief of Staff",
      description:
        "GAIA acts as your AI chief of staff, managing communications, scheduling, and workflows.",
      category: "Product",
    },
    {
      path: "/inbox-zero-ai",
      title: "Inbox Zero AI",
      description:
        "Achieve inbox zero with GAIA's AI email management and automation.",
      category: "Product",
    },
  ];

  return pages.map((page) => ({
    title: page.title,
    link: `${baseUrl}${page.path}`,
    description: page.description,
    pubDate: BUILD_DATE,
    category: page.category,
  }));
}

function getFeaturePages(baseUrl: string): FeedItem[] {
  return FEATURES.map((feature) => ({
    title: `${feature.title} - ${feature.tagline}`,
    link: `${baseUrl}/features/${feature.slug}`,
    description: feature.subheadline,
    pubDate: BUILD_DATE,
    category: `Features / ${feature.category}`,
  }));
}

function getComparisonPages(baseUrl: string): FeedItem[] {
  return getAllComparisons().map((item) => ({
    title: item.metaTitle || `GAIA vs ${item.name}`,
    link: `${baseUrl}/compare/${item.slug}`,
    description: item.metaDescription || item.description,
    pubDate: BUILD_DATE,
    category: "Comparisons",
  }));
}

function getAlternativePages(baseUrl: string): FeedItem[] {
  return getAllAlternatives().map((item) => ({
    title: item.metaTitle || `GAIA Alternative to ${item.name}`,
    link: `${baseUrl}/alternative-to/${item.slug}`,
    description: item.metaDescription || item.tagline,
    pubDate: BUILD_DATE,
    category: "Alternatives",
  }));
}

function getPersonaPages(baseUrl: string): FeedItem[] {
  return getAllPersonas().map((item) => ({
    title: item.metaTitle || `GAIA for ${item.title}`,
    link: `${baseUrl}/for/${item.slug}`,
    description: item.metaDescription || item.intro,
    pubDate: BUILD_DATE,
    category: "Built For",
  }));
}

function getGlossaryPages(baseUrl: string): FeedItem[] {
  return getAllGlossaryTerms()
    .filter((term) => !term.canonicalSlug)
    .map((term) => ({
      title: term.metaTitle || term.term,
      link: `${baseUrl}/learn/${term.slug}`,
      description: term.metaDescription || term.definition,
      pubDate: BUILD_DATE,
      category: "Glossary",
    }));
}

function getComboPages(baseUrl: string): FeedItem[] {
  return getAllCombos()
    .filter((combo) => !combo.canonicalSlug)
    .map((combo) => ({
      title: combo.metaTitle || `${combo.toolA} + ${combo.toolB} Automation`,
      link: `${baseUrl}/automate/${combo.slug}`,
      description: combo.metaDescription || combo.tagline,
      pubDate: BUILD_DATE,
      category: "Automation Combos",
    }));
}

async function getIntegrationItems(baseUrl: string): Promise<FeedItem[]> {
  try {
    const apiBaseUrl = getServerApiBaseUrl();
    if (!apiBaseUrl) return [];

    type IntegrationEntry = {
      slug: string;
      name?: string;
      description?: string;
      publishedAt?: string;
      createdAt?: string;
    };

    const allIntegrations: IntegrationEntry[] = await fetchAllPaginated(
      async (limit, offset) => {
        const response = await fetch(
          `${apiBaseUrl}/integrations/community?limit=${limit}&offset=${offset}`,
          { next: { revalidate: 3600 } },
        );
        if (!response.ok) return { items: [], total: 0, hasMore: false };
        const data = await response.json();
        return {
          items: data.integrations || [],
          total: data.total || 0,
          hasMore: data.hasMore !== false,
        };
      },
      100,
    );

    return allIntegrations.map((integration) => ({
      title: integration.name
        ? `${integration.name} Integration`
        : `GAIA Marketplace: ${integration.slug}`,
      link: `${baseUrl}/marketplace/${integration.slug}`,
      description:
        integration.description ||
        `Connect ${integration.name || integration.slug} with GAIA to automate your workflows.`,
      pubDate: new Date(
        integration.publishedAt || integration.createdAt || Date.now(),
      ).toUTCString(),
      category: "Integrations",
    }));
  } catch (error) {
    console.error("Error fetching integrations for RSS feed:", error);
    return [];
  }
}

async function getBlogItems(baseUrl: string): Promise<FeedItem[]> {
  try {
    const blogs = await blogApi.getBlogs(true);
    return blogs.map((blog) => ({
      title: blog.title,
      link: `${baseUrl}/blog/${blog.slug}`,
      description: blog.content
        .replace(/[#*`[\]()]/g, "")
        .replace(/\n/g, " ")
        .slice(0, 500)
        .trim(),
      pubDate: new Date(blog.date).toUTCString(),
      category: blog.category || "Blog",
    }));
  } catch (error) {
    console.error("Error fetching blogs for RSS feed:", error);
    return [];
  }
}

async function getWorkflowItems(baseUrl: string): Promise<FeedItem[]> {
  try {
    const [explore, community] = await Promise.all([
      workflowApi.getExploreWorkflows(1000, 0).catch(() => ({ workflows: [] })),
      workflowApi
        .getCommunityWorkflows(1000, 0)
        .catch(() => ({ workflows: [] })),
    ]);

    const allWorkflows = [...explore.workflows, ...community.workflows];
    const seen = new Set<string>();

    return allWorkflows
      .filter((wf) => {
        if (seen.has(wf.id)) return false;
        seen.add(wf.id);
        return true;
      })
      .map((wf) => ({
        title: wf.title || wf.id,
        link: `${baseUrl}/use-cases/${wf.id}`,
        description:
          wf.description ||
          `AI workflow: ${wf.title || wf.id}. Automate this use case with GAIA.`,
        pubDate: new Date(wf.created_at).toUTCString(),
        category: wf.categories?.includes("featured")
          ? "Featured Workflows"
          : "Community Workflows",
      }));
  } catch (error) {
    console.error("Error fetching workflows for RSS feed:", error);
    return [];
  }
}

export async function GET() {
  try {
    const baseUrl = siteConfig.url;

    const [blogItems, workflowItems, integrationItems] = await Promise.all([
      getBlogItems(baseUrl),
      getWorkflowItems(baseUrl),
      getIntegrationItems(baseUrl),
    ]);

    const allItems: FeedItem[] = [
      ...getStaticPages(baseUrl),
      ...getFeaturePages(baseUrl),
      ...getComparisonPages(baseUrl),
      ...getAlternativePages(baseUrl),
      ...getPersonaPages(baseUrl),
      ...getGlossaryPages(baseUrl),
      ...getComboPages(baseUrl),
      ...integrationItems,
      ...blogItems,
      ...workflowItems,
    ];

    const rssItems = allItems.map(buildItem).join("");

    const rss = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:atom="http://www.w3.org/2005/Atom"
     xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>GAIA - Your Personal AI Assistant</title>
    <link>${baseUrl}</link>
    <description>${escapeXml(siteConfig.description)}</description>
    <language>en-us</language>
    <lastBuildDate>${new Date().toUTCString()}</lastBuildDate>
    <atom:link href="${baseUrl}/feed.xml" rel="self" type="application/rss+xml"/>
    <image>
      <url>${baseUrl}/images/logos/logo.webp</url>
      <title>GAIA</title>
      <link>${baseUrl}</link>
    </image>
    ${rssItems}
  </channel>
</rss>`;

    return new Response(rss, {
      headers: {
        "Content-Type": "application/xml; charset=utf-8",
        "Cache-Control": "public, max-age=3600, s-maxage=3600",
      },
    });
  } catch (error) {
    console.error("Error generating full-site RSS feed:", error);
    return new Response("Error generating RSS feed", { status: 500 });
  }
}
