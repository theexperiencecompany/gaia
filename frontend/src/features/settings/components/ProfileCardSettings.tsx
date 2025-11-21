"use client";

import { Button, ButtonGroup } from "@heroui/button";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import { Popover, PopoverContent, PopoverTrigger } from "@heroui/popover";
import { Skeleton } from "@heroui/skeleton";
import { Slider } from "@heroui/slider";
import { Tooltip } from "@heroui/tooltip";
import { Suspense, useCallback,useEffect, useRef, useState } from "react";
import ColorPicker from "react-best-gradient-color-picker";
import { toast } from "sonner";

import { HoloCard } from "@/components/ui/magic-ui/holo-card";
import {
  holoCardApi,
  HoloCardData,
} from "@/features/onboarding/api/holoCardApi";
import {
  getHouseImage,
  normalizeHouse,
} from "@/features/onboarding/constants/houses";
import {
  Copy,
  Dices,
  Download,
  ExternalLink,
  Palette,
  RotateCcw,
  Share2,
} from "@/icons";

export default function ProfileCardSettings() {
  const [holoCardData, setHoloCardData] = useState<HoloCardData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [color, setColor] = useState("rgba(0,0,0,0)");
  const [opacity, setOpacity] = useState(40);
  const [isColorPickerOpen, setIsColorPickerOpen] = useState(false);
  const saveTimeoutRef = useRef<NodeJS.Timeout | null>(null);

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

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const data = await holoCardApi.getMyHoloCard();
        setHoloCardData(data);
        // Set initial color and opacity from data
        if (data.overlay_color) {
          setColor(data.overlay_color);
        }
        if (data.overlay_opacity !== undefined) {
          setOpacity(data.overlay_opacity);
        }
      } catch (error) {
        console.error("Failed to fetch holo card data:", error);
      } finally {
        setIsLoading(false);
      }
    };

    fetchData();
  }, []);

  const handleCopyLink = () => {
    if (!holoCardData?.holo_card_id) return;
    const url = `${window.location.origin}/profile/${holoCardData.holo_card_id}`;
    navigator.clipboard.writeText(url);
    toast.success("Profile link copied to clipboard!");
  };

  const handleOpenProfile = () => {
    if (!holoCardData?.holo_card_id) return;
    const url = `/profile/${holoCardData.holo_card_id}`;
    window.open(url, "_blank");
  };

  const handleDownload = () => {
    toast.success("Download started");
    // Add download logic here
  };

  const handleShare = (platform: "twitter" | "linkedin" | "copy") => {
    if (!holoCardData?.holo_card_id) return;
    const url = `${window.location.origin}/profile/${holoCardData.holo_card_id}`;
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
    // Helper to generate vibrant, distinct colors in RGBA format
    const generateVibrantColor = () => {
      const hue = Math.floor(Math.random() * 360);
      const saturation = 70 + Math.floor(Math.random() * 30);
      const lightness = 40 + Math.floor(Math.random() * 30);

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

    const isGradient = Math.random() > 0.5;
    let newColor: string;
    if (isGradient) {
      const color1 = generateVibrantColor();
      const color2 = generateVibrantColor();
      const angle = Math.floor(Math.random() * 360);
      newColor = `linear-gradient(${angle}deg, ${color1} 0%, ${color2} 100%)`;
    } else {
      newColor = generateVibrantColor();
    }

    const newOpacity = 30 + Math.floor(Math.random() * 50);

    setColor(newColor);
    setOpacity(newOpacity);

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
              <Copy size={16} />
            </Button>
          </Tooltip>
          <Tooltip content="View full profile">
            <Button
              isIconOnly
              variant="flat"
              onPress={handleOpenProfile}
              size="sm"
            >
              <ExternalLink size={16} />
            </Button>
          </Tooltip>
        </ButtonGroup>
      </div>

      <div className="flex justify-center py-4">
        {isLoading ? (
          <Skeleton className="h-[400px] w-[280px] rounded-2xl" />
        ) : holoCardData ? (
          <div className="flex flex-col items-center gap-4">
            <Suspense fallback={<Skeleton className="h-[400px] w-[280px]" />}>
              <HoloCard
                url={getHouseImage(holoCardData.house)}
                height={500}
                width={370}
                showSparkles={true}
                overlayColor={color}
                overlayOpacity={opacity}
                houseName={normalizeHouse(holoCardData.house)}
                userName={holoCardData.name}
                userTagline={holoCardData.personality_phrase}
                userId={`#${holoCardData.account_number}`}
                joinDate={holoCardData.member_since}
                userBio={holoCardData.user_bio}
              />
            </Suspense>

            <ButtonGroup className="mt-2">
              <Tooltip content="Download your card" placement="top">
                <Button
                  isIconOnly
                  variant="flat"
                  onPress={handleDownload}
                  aria-label="Download"
                >
                  <Download size={20} />
                </Button>
              </Tooltip>

              <Tooltip content="Share your card" placement="top">
                <Dropdown placement="top">
                  <DropdownTrigger>
                    <Button isIconOnly variant="flat" aria-label="Share">
                      <Share2 size={20} />
                    </Button>
                  </DropdownTrigger>
                  <DropdownMenu aria-label="Share options">
                    <DropdownItem
                      key="twitter"
                      startContent={
                        <svg
                          width={16}
                          height={16}
                          viewBox="0 0 24 24"
                          fill="currentColor"
                        >
                          <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
                        </svg>
                      }
                      onPress={() => handleShare("twitter")}
                    >
                      Twitter
                    </DropdownItem>
                    <DropdownItem
                      key="linkedin"
                      startContent={
                        <svg
                          width={16}
                          height={16}
                          viewBox="0 0 24 24"
                          fill="currentColor"
                        >
                          <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" />
                        </svg>
                      }
                      onPress={() => handleShare("linkedin")}
                    >
                      LinkedIn
                    </DropdownItem>
                    <DropdownItem
                      key="copy"
                      startContent={<Copy size={16} />}
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
                    <Button isIconOnly variant="flat" aria-label="Color Picker">
                      <Palette width={20} height={20} />
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
                          <RotateCcw size={16} />
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
                          <span className="text-sm text-white/70">Opacity</span>
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
        ) : null}
      </div>
    </div>
  );
}
