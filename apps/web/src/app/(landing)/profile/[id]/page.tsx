"use client";

import { Button } from "@heroui/button";
import { Skeleton } from "@heroui/skeleton";
import { Tooltip } from "@heroui/tooltip";
import { Share08Icon } from "@icons";
import { useParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { HoloCard, type HoloCardDisplayData } from "@/components/ui/holo-card";
import {
  holoCardApi,
  type PublicHoloCardData,
} from "@/features/onboarding/api/holoCardApi";
import { toast } from "@/lib/toast";

export default function ProfilePage() {
  const params = useParams();
  const cardId = params.id as string;
  const [holoCardData, setHoloCardData] = useState<PublicHoloCardData | null>(
    null,
  );
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (holoCardData) {
      document.title = `${holoCardData.name} - GAIA Profile`;
    }
  }, [holoCardData]);

  useEffect(() => {
    const fetchProfile = async () => {
      try {
        const data = await holoCardApi.getPublicHoloCard(cardId);
        setHoloCardData(data);
      } catch (error) {
        console.error("Failed to fetch profile:", error);
        toast.error("Failed to load profile");
      } finally {
        setIsLoading(false);
      }
    };

    fetchProfile();
  }, [cardId]);

  const handleShare = () => {
    if (typeof window === "undefined") return;
    const url = window.location.href;
    navigator.clipboard.writeText(url);
    toast.success("Profile link copied to clipboard!");
  };

  const displayData: HoloCardDisplayData | null = holoCardData
    ? {
        house: holoCardData.house,
        name: holoCardData.name,
        personality_phrase: holoCardData.personality_phrase,
        user_bio: holoCardData.user_bio,
        account_number: `#${holoCardData.account_number}`,
        member_since: holoCardData.member_since,
        overlay_color: holoCardData.overlay_color || "rgba(0,0,0,0)",
        overlay_opacity: holoCardData.overlay_opacity || 40,
        holo_card_id: cardId,
      }
    : null;

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-black">
      <h1 className="sr-only">
        {holoCardData?.name
          ? `${holoCardData.name} - GAIA Profile`
          : "GAIA Profile"}
      </h1>
      <div className="flex flex-col items-center gap-8">
        {isLoading ? (
          <Skeleton className="h-[500px] w-[350px] rounded-2xl" />
        ) : displayData ? (
          <Suspense fallback={<Skeleton className="h-[500px] w-[350px]" />}>
            <HoloCard
              data={displayData}
              height={600}
              width={400}
              showSparkles={true}
            />
          </Suspense>
        ) : (
          <div className="text-center text-zinc-400">
            <p>Card not found</p>
          </div>
        )}

        {holoCardData && (
          <Tooltip content="Share profile">
            <Button isIconOnly variant="flat" onPress={handleShare} size="sm">
              <Share08Icon size={18} />
            </Button>
          </Tooltip>
        )}
      </div>
    </div>
  );
}
