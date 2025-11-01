import "./styles/tailwind.css";
import "./styles/globals.css";

import { Databuddy } from "@databuddy/sdk/react";
import { SpeedInsights } from "@vercel/speed-insights/next";
import type { Metadata, Viewport } from "next";
import Script from "next/script";
import { Suspense } from "react";

import AnalyticsLayout from "@/layouts/AnalyticsLayout";
import ProvidersLayout from "@/layouts/ProvidersLayout";
import {
  generateOrganizationSchema,
  generateWebSiteSchema,
  siteConfig,
} from "@/lib/seo";

import { defaultFont, getAllFontVariables } from "./fonts";

export const metadata: Metadata = {
  metadataBase: new URL(siteConfig.url),
  title: {
    default: "GAIA - Your Personal AI Assistant",
    template: "%s | GAIA",
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
    "GAIA",
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
    title: "GAIA - Your Personal AI Assistant",
    siteName: siteConfig.fullName,
    url: siteConfig.url,
    type: "website",
    description: siteConfig.description,
    images: [
      {
        url: siteConfig.ogImage,
        width: 1200,
        height: 630,
        alt: "GAIA - Personal AI Assistant",
      },
    ],
    locale: "en_US",
  },
  twitter: {
    card: "summary_large_image",
    title: "GAIA - Your Personal AI Assistant",
    description: siteConfig.description,
    images: [siteConfig.ogImage],
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
  creator: "GAIA",
  publisher: "GAIA",
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
          rel="preconnect"
          href="https://databuddy.cc"
          crossOrigin="anonymous"
        />
        {/* Preload critical hero image to improve LCP - reduce 1,160ms load delay */}
        <link
          rel="preload"
          as="image"
          href="/images/hero.webp?q=80"
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

        {/* Defer all analytics to improve LCP and reduce unused JS */}
        <Script
          src="https://analytics.heygaia.io/api/script.js"
          data-site-id="1"
          strategy="afterInteractive"
          data-session-replay="true"
        />

        <Suspense fallback={<></>}>
          <AnalyticsLayout />
        </Suspense>

        {process.env.NEXT_PUBLIC_DATABUDDY_CLIENT_ID && (
          <Suspense fallback={<></>}>
            <Databuddy
              clientId={process.env.NEXT_PUBLIC_DATABUDDY_CLIENT_ID}
              trackHashChanges
              trackAttributes
              trackOutgoingLinks
              trackInteractions
              trackEngagement
              trackScrollDepth
              trackExitIntent
              trackBounceRate
              trackWebVitals
              trackErrors
              enableBatching
              batchSize={20}
              batchTimeout={5000}
              disabled={process.env.NODE_ENV === "development"}
            />
          </Suspense>
        )}
      </body>
    </html>
  );
}
