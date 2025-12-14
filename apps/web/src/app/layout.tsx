import "./styles/globals.css";
import "./styles/tailwind.css";

import { Analytics as VercelAnalytics } from "@vercel/analytics/next";
import { SpeedInsights } from "@vercel/speed-insights/next";
import type { Metadata, Viewport } from "next";
import Script from "next/script";

import AnalyticsLayout from "@/layouts/AnalyticsLayout";
import ProvidersLayout from "@/layouts/ProvidersLayout";
import {
  generateOrganizationSchema,
  generateWebSiteSchema,
  siteConfig,
} from "@/lib/seo";

import { defaultFont, getAllFontVariables } from "./fonts";

// Dynamically determine the base URL based on environment
const getMetadataBase = () => {
  // if (process.env.NEXT_PUBLIC_APP_URL)
  //   return new URL(process.env.NEXT_PUBLIC_APP_URL);

  // if (process.env.VERCEL_URL)
  //   return new URL(`https://${process.env.VERCEL_URL}`);

  return new URL(siteConfig.url);
};

export const metadata: Metadata = {
  metadataBase: getMetadataBase(),
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
    locale: "en_US",
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

export const viewport: Viewport = {
  themeColor: "#00bbff",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${getAllFontVariables()} dark`}>
      <SpeedInsights />
      <head>
        <link
          rel="preconnect"
          href="https://status.heygaia.io"
          crossOrigin="anonymous"
        />
        <link rel="dns-prefetch" href="https://uptime.betterstack.com" />
        <link rel="dns-prefetch" href="https://us.i.posthog.com" />
        <link
          rel="preload"
          as="image"
          href="/images/wallpapers/g3.png"
          fetchPriority="high"
        />

        <link
          rel="preload"
          as="image"
          href="/images/wallpapers/g3.webp"
          fetchPriority="high"
        />
        {/* <link rel="preconnect" href="https://i.ytimg.com" /> */}
      </head>
      <body className={`dark ${defaultFont.className}`}>
        <main>
          <ProvidersLayout>{children}</ProvidersLayout>
        </main>

        {/* JSON-LD Schema - Organization */}
        <Script id="json-ld-organization" type="application/ld+json">
          {JSON.stringify(generateOrganizationSchema())}
        </Script>

        {/* JSON-LD Schema - WebSite */}
        <Script id="json-ld-website" type="application/ld+json">
          {JSON.stringify(generateWebSiteSchema())}
        </Script>

        <VercelAnalytics />
        <AnalyticsLayout />
      </body>
    </html>
  );
}
