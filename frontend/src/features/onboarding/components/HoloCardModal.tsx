"use client";

import { Button, ButtonGroup } from "@heroui/button";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import { Modal, ModalContent } from "@heroui/modal";
import { Popover, PopoverContent, PopoverTrigger } from "@heroui/popover";
import { Skeleton } from "@heroui/skeleton";
import { Slider } from "@heroui/slider";
import { Tooltip } from "@heroui/tooltip";
import confetti from "canvas-confetti";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import ColorPicker from "react-best-gradient-color-picker";
import { toast } from "sonner";

import { LinkedinIcon, TwitterIcon } from "@/components";
import { HoloCard } from "@/components/ui/holo-card";
import { useUser } from "@/features/auth/hooks/useUser";
import { SimpleChatBubbleBot } from "@/features/landing/components/demo/SimpleChatBubbles";
import { holoCardApi } from "@/features/onboarding/api/holoCardApi";
import { getHouseImage } from "@/features/onboarding/constants/houses";
import {
  House,
  usePersonalization,
} from "@/features/onboarding/hooks/usePersonalization";
import UseCaseCard from "@/features/use-cases/components/UseCaseCard";
import {
  Dices,
  Download01Icon,
  LinkBackwardIcon,
  PaintBoardIcon,
  ReloadIcon,
  Rocket01Icon,
  Share08Icon,
} from "@/icons";

interface FeatureModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function FeatureModal({ isOpen, onClose }: FeatureModalProps) {
  const [color, setColor] = useState("rgba(0,0,0,0)");
  const [opacity, setOpacity] = useState(40);
  const [isColorPickerOpen, setIsColorPickerOpen] = useState(false);
  const [selectedHouse, setSelectedHouse] = useState<House>("bluehaven");
  const hasShownConfetti = useRef(false);
  const saveTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const user = useUser();

  // Use centralized personalization hook
  const { personalizationData, isLoading: isLoadingPersonalization } =
    usePersonalization(isOpen);

  // Debounced save function
  const saveColors = useCallback((newColor: string, newOpacity: number) => {
    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current);
    }

    saveTimeoutRef.current = setTimeout(() => {
      holoCardApi.updateHoloCardColors(newColor, newOpacity).catch((error) => {
        console.error("Failed to save colors:", error);
      });
    }, 1000); // 1 second debounce
  }, []);

  // Update selected house when data arrives
  useEffect(() => {
    if (personalizationData?.house) {
      setSelectedHouse(personalizationData.house);
    }
  }, [personalizationData]);

  // Set color and opacity from backend when data arrives
  useEffect(() => {
    if (personalizationData?.overlay_color) {
      setColor(personalizationData.overlay_color);
    }
    if (personalizationData?.overlay_opacity !== undefined) {
      setOpacity(personalizationData.overlay_opacity);
    }
  }, [personalizationData]);

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

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
      }
    };
  }, []);

  const handleDownload = () => {
    toast.success("Download started");
    // Add download logic here
  };

  const handleShare = (platform: "twitter" | "linkedin" | "copy") => {
    const url = window.location.href;
    switch (platform) {
      case "twitter":
        window.open(
          `https://twitter.com/intent/tweet?url=${encodeURIComponent(url)}`,
          "_blank",
        );
        break;
      case "linkedin":
        window.open(
          `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(url)}`,
          "_blank",
        );
        break;
      case "copy":
        navigator.clipboard.writeText(url);
        toast.success("Link copied to clipboard");
        break;
    }
  };

  const handleRandomize = () => {
    // Generate wildly random, distinct colors
    const isGradient = Math.random() > 0.5;

    // Helper to generate vibrant, distinct colors in RGBA format
    const generateVibrantColor = () => {
      // Use HSL for more vibrant, distinct colors, then convert to RGB
      const hue = Math.floor(Math.random() * 360);
      const saturation = 70 + Math.floor(Math.random() * 30); // 70-100%
      const lightness = 40 + Math.floor(Math.random() * 30); // 40-70%

      // Convert HSL to RGB
      const h = hue / 360;
      const s = saturation / 100;
      const l = lightness / 100;

      let r, g, b;
      if (s === 0) {
        r = g = b = l;
      } else {
        const hue2rgb = (p: number, q: number, t: number) => {
          if (t < 0) t += 1;
          if (t > 1) t -= 1;
          if (t < 1 / 6) return p + (q - p) * 6 * t;
          if (t < 1 / 2) return q;
          if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
          return p;
        };
        const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
        const p = 2 * l - q;
        r = hue2rgb(p, q, h + 1 / 3);
        g = hue2rgb(p, q, h);
        b = hue2rgb(p, q, h - 1 / 3);
      }

      return `rgba(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}, 1)`;
    };

    let newColor: string;
    if (isGradient) {
      // Generate random gradient with vibrant colors
      const color1 = generateVibrantColor();
      const color2 = generateVibrantColor();
      const angle = Math.floor(Math.random() * 360);

      newColor = `linear-gradient(${angle}deg, ${color1} 0%, ${color2} 100%)`;
    } else {
      // Generate random solid vibrant color
      newColor = generateVibrantColor();
    }

    // Randomize opacity too
    const newOpacity = 30 + Math.floor(Math.random() * 50); // 30-80%

    setColor(newColor);
    setOpacity(newOpacity);

    // Save to backend
    holoCardApi
      .updateHoloCardColors(newColor, newOpacity)
      .then(() => {
        toast.success("Card colors updated!");
      })
      .catch((error) => {
        console.error("Failed to save colors:", error);
        toast.error("Failed to save colors");
      });
  };

  const handleResetColor = () => {
    const defaultColor = "rgba(0,0,0,0)";
    const defaultOpacity = 40;

    setColor(defaultColor);
    setOpacity(defaultOpacity);

    // Save to backend
    holoCardApi
      .updateHoloCardColors(defaultColor, defaultOpacity)
      .then(() => {
        toast.success("Colors reset!");
      })
      .catch((error) => {
        console.error("Failed to reset colors:", error);
        toast.error("Failed to reset colors");
      });
  };

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
                      integrations={workflow.steps
                        .map((s) => s.tool_category)
                        .filter((v, i, a) => a.indexOf(v) === i)}
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

              <Button
                className="font-medium"
                endContent={<TwitterIcon width={18} height={18} />}
                onPress={() => handleShare("twitter")}
              >
                Share on Twitter
              </Button>
            </div>
          </div>

          <div className="flex h-full flex-col items-center justify-center">
            <div className="relative flex flex-col items-center gap-4">
              <div className="text-sm text-zinc-400">Click to flip card</div>
              <Suspense fallback={<Skeleton />}>
                <HoloCard
                  url={getHouseImage(selectedHouse)}
                  height={470}
                  width={330}
                  showSparkles={true}
                  overlayColor={color}
                  overlayOpacity={opacity}
                  houseName={selectedHouse}
                  userName={user.name || "User"}
                  userTagline={
                    personalizationData?.personality_phrase ||
                    "Curious Adventurer"
                  }
                  userId={`#${personalizationData?.account_number || "00000"}`}
                  joinDate={personalizationData?.member_since || "Nov 21, 2024"}
                  userBio={
                    personalizationData?.user_bio ||
                    "A passionate individual exploring new possibilities and making an impact."
                  }
                />
              </Suspense>

              <ButtonGroup className="mt-5">
                <Tooltip content="Download your card" placement="top">
                  <Button
                    isIconOnly
                    variant="flat"
                    onPress={handleDownload}
                    aria-label="Download"
                  >
                    <Download01Icon size={20} />
                  </Button>
                </Tooltip>

                <Tooltip content="Share your card" placement="top">
                  <Dropdown placement="top">
                    <DropdownTrigger>
                      <Button isIconOnly variant="flat" aria-label="Share">
                        <Share08Icon size={20} />
                      </Button>
                    </DropdownTrigger>
                    <DropdownMenu aria-label="Share options">
                      <DropdownItem
                        key="twitter"
                        startContent={<TwitterIcon width={16} height={16} />}
                        onPress={() => handleShare("twitter")}
                      >
                        Twitter
                      </DropdownItem>
                      <DropdownItem
                        key="linkedin"
                        startContent={<LinkedinIcon width={16} height={16} />}
                        onPress={() => handleShare("linkedin")}
                      >
                        LinkedIn
                      </DropdownItem>
                      <DropdownItem
                        key="copy"
                        startContent={<LinkBackwardIcon size={16} />}
                        onPress={() => handleShare("copy")}
                      >
                        Copy Link
                      </DropdownItem>
                    </DropdownMenu>
                  </Dropdown>
                </Tooltip>

                <Tooltip content="Customize colors" placement="top">
                  <Popover
                    isOpen={isColorPickerOpen}
                    onOpenChange={setIsColorPickerOpen}
                    placement="top"
                  >
                    <PopoverTrigger>
                      <Button
                        isIconOnly
                        variant="flat"
                        aria-label="Color Picker"
                      >
                        <PaintBoardIcon width={20} height={20} />
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent className="w-auto bg-zinc-800 p-4">
                      <div className="flex flex-col gap-3">
                        <div className="flex items-center justify-between">
                          <span className="text-sm text-white/70">
                            Color Picker
                          </span>
                          <Button
                            size="sm"
                            variant="light"
                            isIconOnly
                            onPress={handleResetColor}
                            aria-label="Reset Color"
                          >
                            <ReloadIcon size={16} />
                          </Button>
                        </div>
                        <ColorPicker
                          value={color}
                          onChange={(newColor) => {
                            setColor(newColor);
                            saveColors(newColor, opacity);
                          }}
                          hidePresets={true}
                          hideOpacity={true}
                          hideEyeDrop={true}
                          hideAdvancedSliders={true}
                          hideColorGuide={true}
                          hideInputType={true}
                          width={300}
                          height={100}
                          hideGradientStop={true}
                          className={"bg-transparent!"}
                        />
                        <div className="flex flex-col gap-2">
                          <div className="flex items-center justify-between">
                            <span className="text-sm text-white/70">
                              Opacity
                            </span>
                            <span className="text-xs text-white/50">
                              {opacity}%
                            </span>
                          </div>
                          <Slider
                            size="sm"
                            step={1}
                            minValue={0}
                            maxValue={100}
                            value={opacity}
                            onChange={(value) => {
                              const newOpacity = value as number;
                              setOpacity(newOpacity);
                              saveColors(color, newOpacity);
                            }}
                            className="max-w-md"
                          />
                        </div>
                      </div>
                    </PopoverContent>
                  </Popover>
                </Tooltip>

                <Tooltip content="Randomize colors" placement="top">
                  <Button
                    isIconOnly
                    variant="flat"
                    onPress={handleRandomize}
                    aria-label="Randomize"
                  >
                    <Dices size={20} />
                  </Button>
                </Tooltip>
              </ButtonGroup>
            </div>
          </div>
        </div>
      </ModalContent>
    </Modal>
  );
}
