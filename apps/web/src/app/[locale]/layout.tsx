import type { Metadata, Viewport } from "next";
import { notFound } from "next/navigation";
import Script from "next/script";
import { hasLocale, NextIntlClientProvider } from "next-intl";
import { setRequestLocale } from "next-intl/server";
import { type ReactNode, Suspense } from "react";
import { defaultFont, getAllFontVariables } from "@/app/fonts";
import { AgentationProvider } from "@/components/dev/AgentationProvider";
import { routing } from "@/i18n/routing";
import AnalyticsLayout from "@/layouts/AnalyticsLayout";
import {
  generateOrganizationSchema,
  generateWebSiteSchema,
  siteConfig,
} from "@/lib/seo";

const OG_LOCALE_MAP: Record<string, string> = {
  en: "en_US",
  de: "de_DE",
  es: "es_ES",
  fr: "fr_FR",
  ja: "ja_JP",
  ko: "ko_KR",
  "pt-BR": "pt_BR",
};

type Props = {
  readonly children: ReactNode;
  readonly params: Promise<{ readonly locale: string }>;
};

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;

  return {
    metadataBase: new URL(siteConfig.url),
    title: {
      default: siteConfig.name,
      template: `%s | ${siteConfig.short_name}`,
    },
    description: siteConfig.description,
    icons: {
      icon: [
        { url: "/favicon.ico", type: "image/x-icon" },
        { url: "/favicon-32x32.png", type: "image/png", sizes: "32x32" },
        { url: "/favicon-16x16.png", type: "image/png", sizes: "16x16" },
      ],
      apple: "/apple-touch-icon.png",
    },
    manifest: "/site.webmanifest",
    keywords: [
      siteConfig.short_name,
      "GAIA AI",
      "Personal AI Assistant",
      "AI",
      "ai assistant",
      "digital assistant",
      "productivity",
      "Hey GAIA",
      "general purpose ai assistant",
      "artificial intelligence",
      "virtual assistant",
      "smart assistant",
      "AI personal assistant",
      "task management",
      "email automation",
      "calendar management",
      "goal tracking",
      "workflow automation",
      "proactive AI",
      "productivity assistant",
    ],
    openGraph: {
      title: siteConfig.name,
      siteName: siteConfig.name,
      url: siteConfig.url,
      type: "website",
      description: siteConfig.description,
      images: [
        {
          url: `${siteConfig.url}${siteConfig.ogImage}`,
          width: 1200,
          height: 630,
          alt: "GAIA - Personal AI Assistant",
          type: "image/webp",
        },
      ],
      locale: OG_LOCALE_MAP[locale] || "en_US",
    },
    twitter: {
      card: "summary_large_image",
      title: siteConfig.name,
      description: siteConfig.description,
      images: [
        {
          url: `${siteConfig.url}${siteConfig.ogImage}`,
          width: 1200,
          height: 630,
          alt: "GAIA - Personal AI Assistant",
        },
      ],
      creator: "@trygaia",
      site: "@trygaia",
    },
    other: {
      "msapplication-TileColor": "#00bbff",
      "apple-mobile-web-app-capable": "yes",
    },
    authors: [
      { name: "GAIA Team", url: siteConfig.url },
      ...siteConfig.founders.map((founder) => ({
        name: founder.name,
        url: founder.linkedin,
      })),
    ],
    creator: siteConfig.short_name,
    publisher: siteConfig.short_name,
    robots: {
      index: true,
      follow: true,
      googleBot: {
        index: true,
        follow: true,
        "max-video-preview": -1,
        "max-image-preview": "large",
        "max-snippet": -1,
      },
    },
  };
}

export const viewport: Viewport = {
  themeColor: "#00bbff",
};

export default async function LocaleLayout({ children, params }: Props) {
  const { locale } = await params;

  if (!hasLocale(routing.locales, locale)) {
    notFound();
  }

  setRequestLocale(locale);

  return (
    <html lang={locale} className={`${getAllFontVariables()} dark`}>
      <head>
        <link
          rel="preconnect"
          href="https://status.heygaia.io"
          crossOrigin="anonymous"
        />
        <link
          rel="preconnect"
          href="https://api.github.com"
          crossOrigin="anonymous"
        />
        <link rel="dns-prefetch" href="https://uptime.betterstackcdn.com" />
        <link
          rel="preload"
          as="image"
          href="/images/logos/text_w_logo_white.webp"
          fetchPriority="high"
        />
        <link
          rel="alternate"
          type="application/rss+xml"
          title="GAIA RSS Feed"
          href="/feed.xml"
        />
        <link
          rel="alternate"
          type="application/rss+xml"
          title="GAIA Blog RSS Feed"
          href="/blog/rss.xml"
        />
      </head>
      <body className={`dark ${defaultFont.className}`}>
        <NextIntlClientProvider locale={locale} messages={{}}>
          <div id="app-root">
            <Suspense fallback={null}>{children}</Suspense>
          </div>
        </NextIntlClientProvider>

        <Script id="json-ld-organization" type="application/ld+json">
          {JSON.stringify(generateOrganizationSchema())}
        </Script>

        <Script id="json-ld-website" type="application/ld+json">
          {JSON.stringify(generateWebSiteSchema())}
        </Script>

        <AnalyticsLayout />
        <AgentationProvider />
      </body>
    </html>
  );
}
