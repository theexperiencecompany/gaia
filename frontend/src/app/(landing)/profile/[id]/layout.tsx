import type { Metadata } from "next";

import type { PublicHoloCardData } from "@/features/onboarding/api/holoCardApi";
import { normalizeHouse } from "@/features/onboarding/constants/houses";

export async function generateMetadata({
  params,
}: {
  params: { id: string };
}): Promise<Metadata> {
  try {
    const cardId = params.id;
    const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL;

    const response = await fetch(
      `${backendUrl}/api/v1/user/holo-card/${cardId}`,
      {
        headers: {
          "Content-Type": "application/json",
        },
      },
    );

    if (!response.ok) throw new Error("Failed to fetch profile data");

    const holoCardData: PublicHoloCardData = await response.json();
    const houseName = normalizeHouse(holoCardData.house);

    const title = `${holoCardData.name}'s GAIA Card`;
    const description = `${holoCardData.personality_phrase} • ${houseName} • User #${holoCardData.account_number} • Member since ${holoCardData.member_since}`;

    return {
      title,
      description,
      openGraph: {
        title,
        description,
        type: "profile",
        images: [
          {
            url: `/profile/${cardId}/opengraph-image`,
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
        images: [`/profile/${cardId}/opengraph-image`],
      },
    };
  } catch (error) {
    console.error("Failed to generate metadata:", error);
    return {
      title: "GAIA Profile Card",
      description: "View this personalized GAIA profile card",
    };
  }
}

export default function ProfileLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
