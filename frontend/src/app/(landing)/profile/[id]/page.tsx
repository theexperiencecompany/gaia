"use client";

import { HoloCard } from "@/components/ui/magic-ui/holo-card";
import { Skeleton } from "@heroui/skeleton";
import { useParams } from "next/navigation";
import { useEffect, useState, Suspense } from "react";
import {
  getHouseImage,
  normalizeHouse,
} from "@/features/onboarding/constants/houses";
import {
  holoCardApi,
  PublicHoloCardData,
} from "@/features/onboarding/api/holoCardApi";
import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import { Share2 } from "lucide-react";
import { toast } from "sonner";

export default function ProfilePage() {
  const params = useParams();
  const cardId = params.id as string;
  const [holoCardData, setHoloCardData] = useState<PublicHoloCardData | null>(
    null,
  );
  const [isLoading, setIsLoading] = useState(true);

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
    const url = window.location.href;
    navigator.clipboard.writeText(url);
    toast.success("Profile link copied to clipboard!");
  };

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-black">
      <div className="flex flex-col items-center gap-8">
        {isLoading ? (
          <Skeleton className="h-[500px] w-[350px] rounded-2xl" />
        ) : holoCardData ? (
          <Suspense fallback={<Skeleton className="h-[500px] w-[350px]" />}>
            <HoloCard
              url={getHouseImage(holoCardData.house)}
              height={600}
              width={400}
              showSparkles={true}
              overlayColor={holoCardData.overlay_color || "rgba(0,0,0,0)"}
              overlayOpacity={holoCardData.overlay_opacity || 40}
              houseName={normalizeHouse(holoCardData.house)}
              userName={holoCardData.name}
              userTagline={holoCardData.personality_phrase}
              userId={`#${holoCardData.account_number}`}
              joinDate={holoCardData.member_since}
              userBio={holoCardData.user_bio}
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
              <Share2 size={18} />
            </Button>
          </Tooltip>
        )}
      </div>
    </div>
  );
}
