"use client";

import { Button } from "@heroui/button";
import { Modal, ModalContent } from "@heroui/modal";
import { Skeleton } from "@heroui/skeleton";
import confetti from "canvas-confetti";
import { useEffect, useRef, useState } from "react";
import { TwitterShareButton } from "react-share";
import { toast } from "sonner";

import { TwitterIcon } from "@/components";
import { HoloCardDisplayData, HoloCardEditor } from "@/components/ui/holo-card";
import { useUser } from "@/features/auth/hooks/useUser";
import { SimpleChatBubbleBot } from "@/features/landing/components/demo/SimpleChatBubbles";
import {
  House,
  usePersonalization,
} from "@/features/onboarding/hooks/usePersonalization";
import UseCaseCard from "@/features/use-cases/components/UseCaseCard";
import { Rocket01Icon } from "@/icons";

interface FeatureModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function FeatureModal({ isOpen, onClose }: FeatureModalProps) {
  const [selectedHouse, setSelectedHouse] = useState<House>("bluehaven");
  const [shareUrl, setShareUrl] = useState("");
  const hasShownConfetti = useRef(false);
  const user = useUser();

  // Use centralized personalization hook
  const { personalizationData, isLoading: isLoadingPersonalization } =
    usePersonalization(isOpen);

  // Update selected house when data arrives
  useEffect(() => {
    if (personalizationData?.house) {
      setSelectedHouse(personalizationData.house as House);
    }
  }, [personalizationData]);

  // Set share URL only on client side
  useEffect(() => {
    if (typeof window !== "undefined") {
      const url = personalizationData?.holo_card_id
        ? `${window.location.origin}/profile/${personalizationData.holo_card_id}`
        : window.location.href;
      setShareUrl(url);
    }
  }, [personalizationData?.holo_card_id]);

  useEffect(() => {
    if (isOpen && !hasShownConfetti.current) {
      hasShownConfetti.current = true;
      confetti({
        particleCount: 300,
        spread: 500,
        origin: { y: 0.4 },
        colors: ["#00bbff", "#a855f7", "#ec4899", "#f59e0b"],
      });
    }
  }, [isOpen]);

  const handleShare = (platform: "twitter" | "linkedin" | "copy") => {
    if (typeof window === "undefined" || !shareUrl) return;

    switch (platform) {
      case "twitter":
        window.open(
          `https://twitter.com/intent/tweet?url=${encodeURIComponent(shareUrl)}`,
          "_blank",
        );
        break;
      case "linkedin":
        window.open(
          `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(shareUrl)}`,
          "_blank",
        );
        break;
      case "copy":
        navigator.clipboard.writeText(shareUrl);
        toast.success("Link copied to clipboard");
        break;
    }
  };

  const holoCardData: HoloCardDisplayData = {
    house: selectedHouse,
    name: user.name || "User",
    personality_phrase:
      personalizationData?.personality_phrase || "Curious Adventurer",
    user_bio:
      personalizationData?.user_bio ||
      "A passionate individual exploring new possibilities and making an impact.",
    account_number: `#${personalizationData?.account_number || "00000"}`,
    member_since: personalizationData?.member_since || "Nov 21, 2024",
    overlay_color: personalizationData?.overlay_color || "rgba(0,0,0,0)",
    overlay_opacity: personalizationData?.overlay_opacity ?? 40,
    holo_card_id: personalizationData?.holo_card_id,
  };

  const shareTitle = "Check out my Personal Card made using GAIA";

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size="full"
      isDismissable={true}
      backdrop="blur"
      scrollBehavior="inside"
    >
      <ModalContent className="flex border-0! bg-zinc-900/50 shadow-none outline-0!">
        <div className="grid h-full flex-1 grid-cols-1 items-center lg:grid-cols-3">
          <div className="col-span-2 space-y-4 p-10 pr-0!">
            <SimpleChatBubbleBot>
              {isLoadingPersonalization
                ? "I'm preparing your personalized workflows...<NEW_MESSAGE_BREAK>Just a moment! ✨"
                : "I've put together some workflows to get you started.<NEW_MESSAGE_BREAK>Try any of these or create your own!"}
            </SimpleChatBubbleBot>

            <div className="mt-5 grid w-full grid-cols-3 gap-2 pl-12">
              {isLoadingPersonalization ? (
                <>
                  <Skeleton className="h-32 rounded-lg" />
                  <Skeleton className="h-32 rounded-lg" />
                  <Skeleton className="h-32 rounded-lg" />
                  <Skeleton className="h-32 rounded-lg" />
                </>
              ) : (
                (personalizationData?.suggested_workflows || []).map(
                  (workflow, index) => (
                    <UseCaseCard
                      key={workflow.id || index}
                      title={workflow.title}
                      description={workflow.description}
                      action_type="workflow"
                      steps={workflow.steps}
                    />
                  ),
                )
              )}
            </div>

            <SimpleChatBubbleBot>
              {
                "Your very own GAIA Card is waiting on the right! 🎨✨<NEW_MESSAGE_BREAK>Go wild with the customization tools and show off your masterpiece to the world! 🚀"
              }
            </SimpleChatBubbleBot>
            <div className="mt-8 ml-12 space-x-2">
              <Button
                color="primary"
                className="font-medium"
                endContent={<Rocket01Icon width={18} height={18} />}
                onPress={onClose}
              >
                Let's Go!
              </Button>

              <TwitterShareButton url={shareUrl} title={shareTitle}>
                <Button
                  className="font-medium"
                  endContent={<TwitterIcon width={18} height={18} />}
                  onPress={() => handleShare("twitter")}
                >
                  Share on Twitter
                </Button>
              </TwitterShareButton>
            </div>
          </div>

          <div className="flex h-full flex-col items-center justify-center">
            <div className="relative flex flex-col items-center gap-4">
              <div className="text-sm text-zinc-400">Click to flip card</div>
              <HoloCardEditor
                initialData={holoCardData}
                height={470}
                width={330}
              />
            </div>
          </div>
        </div>
      </ModalContent>
    </Modal>
  );
}
