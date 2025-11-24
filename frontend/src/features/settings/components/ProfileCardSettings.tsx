"use client";

import { Button, ButtonGroup } from "@heroui/button";
import { Skeleton } from "@heroui/skeleton";
import { Tooltip } from "@heroui/tooltip";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { HoloCardDisplayData, HoloCardEditor } from "@/components/ui/holo-card";
import {
  holoCardApi,
  HoloCardData,
} from "@/features/onboarding/api/holoCardApi";
import { Copy01Icon, LinkSquare02Icon } from "@/icons";

export default function ProfileCardSettings() {
  const [holoCardData, setHoloCardData] = useState<HoloCardData | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const data = await holoCardApi.getMyHoloCard();
        setHoloCardData(data);
      } catch (error) {
        console.error("Failed to fetch holo card data:", error);
      } finally {
        setIsLoading(false);
      }
    };

    fetchData();
  }, []);

  const handleCopyLink = () => {
    if (!holoCardData?.holo_card_id &&
      typeof window !== "undefined"
    ) return;
    const url = `${window.location.origin}/profile/${holoCardData?.holo_card_id}`;
    navigator.clipboard.writeText(url);
    toast.success("Profile link copied to clipboard!");
  };

  const handleOpenProfile = () => {
    if (!holoCardData?.holo_card_id) return;
    const url = `/profile/${holoCardData.holo_card_id}`;
    window.open(url, "_blank");
  };

  const handleConnectGmail = () => {
    // TODO: Implement Gmail OAuth flow or redirect to integrations page
    toast("Redirecting to Gmail connection...");
    window.location.href = "/integrations?connect=gmail";
  };

  const displayData: HoloCardDisplayData | null = holoCardData
    ? {
      house: holoCardData.house || "bluehaven",
      name: holoCardData.name,
      personality_phrase: holoCardData.personality_phrase,
      user_bio: holoCardData.user_bio,
      account_number: `#${holoCardData.account_number}`,
      member_since: holoCardData.member_since,
      overlay_color: holoCardData.overlay_color,
      overlay_opacity: holoCardData.overlay_opacity,
      holo_card_id: holoCardData.holo_card_id,
    }
    : null;

  return (
    <div className="w-full space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-white">Your GAIA Card</h3>
          <p className="text-sm text-zinc-400">A tiny window into you</p>
        </div>
        <ButtonGroup>
          <Tooltip content="Copy profile link">
            <Button
              isIconOnly
              variant="flat"
              onPress={handleCopyLink}
              size="sm"
            >
              <Copy01Icon size={16} />
            </Button>
          </Tooltip>
          <Tooltip content="View full profile">
            <Button
              isIconOnly
              variant="flat"
              onPress={handleOpenProfile}
              size="sm"
            >
              <LinkSquare02Icon size={16} />
            </Button>
          </Tooltip>
        </ButtonGroup>
      </div>

      <div className="flex justify-center py-4">
        {isLoading ? (
          <Skeleton className="h-[400px] w-[280px] rounded-2xl" />
        ) : displayData ? (
          <div className="flex flex-col items-center gap-4">
            <HoloCardEditor
              initialData={displayData}
              height={500}
              width={370}
            />
            {displayData.user_bio &&
              (displayData.user_bio.startsWith("Connect your Gmail") ||
                displayData.user_bio.startsWith("Processing")) && (
                <Button
                  color="primary"
                  size="lg"
                  className="mt-4 rounded-xl px-6 py-3 text-base font-semibold"
                  onPress={handleConnectGmail}
                >
                  Connect Gmail for a personalized bio
                  <span className="mt-1 block text-xs font-normal text-zinc-300">
                    Unlock your unique AI bio and insights
                  </span>
                </Button>
              )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
