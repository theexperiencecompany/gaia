import type { Metadata } from "next";
import { notFound } from "next/navigation";

import type { PublicHoloCardData } from "@/features/onboarding/api/holoCardApi";
import {
  getHouseImage,
  normalizeHouse,
} from "@/features/onboarding/constants/houses";
import { siteConfig } from "@/lib/seo";
import { getServerApiBaseUrl } from "@/lib/serverApiBaseUrl";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id: cardId } = await params;
  const profileUrl = `${siteConfig.url}/profile/${cardId}`;
  const fallbackMetadata: Metadata = {
    title: "GAIA Profile Card",
    description: "View this personalized GAIA profile card",
    alternates: {
      canonical: profileUrl,
    },
    openGraph: {
      url: profileUrl,
      type: "profile",
    },
  };

  try {
    const apiBaseUrl = getServerApiBaseUrl();
    if (!apiBaseUrl) {
      return fallbackMetadata;
    }

    const response = await fetch(`${apiBaseUrl}/user/holo-card/${cardId}`, {
      headers: {
        "Content-Type": "application/json",
      },
    });

    if (response.status === 404) {
      notFound();
    }

    if (!response.ok) {
      console.error(
        `Failed to fetch profile metadata for ${cardId}: status ${response.status}`,
      );
      return fallbackMetadata;
    }

    const holoCardData: PublicHoloCardData = await response.json();
    const houseName = normalizeHouse(holoCardData.house);
    const houseImage = getHouseImage(holoCardData.house);

    const title = `${holoCardData.name}'s GAIA Card`;
    const description = `${holoCardData.personality_phrase} • ${houseName} • User #${holoCardData.account_number} • Member since ${holoCardData.member_since}`;

    return {
      title,
      description,
      alternates: {
        canonical: profileUrl,
      },
      openGraph: {
        title,
        description,
        url: profileUrl,
        type: "profile",
        images: [
          {
            url: houseImage,
            width: 1200,
            height: 630,
            alt: `${holoCardData.name}'s GAIA Profile Card`,
          },
        ],
      },
      twitter: {
        card: "summary_large_image",
        title,
        description,
        images: [houseImage],
      },
    };
  } catch (error) {
    if (
      typeof error === "object" &&
      error !== null &&
      "digest" in error &&
      (error as { digest?: string }).digest === "NEXT_HTTP_ERROR_FALLBACK;404"
    ) {
      throw error;
    }

    console.error("Failed to generate metadata:", error);
    return fallbackMetadata;
  }
}

export default function ProfileLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
