"use client";

import { Button, ButtonGroup } from "@heroui/button";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import { Popover, PopoverContent, PopoverTrigger } from "@heroui/popover";
import { Slider } from "@heroui/slider";
import { Tooltip } from "@heroui/tooltip";
import { toPng } from "html-to-image";
import { useCallback, useEffect, useRef, useState } from "react";
import ColorPicker from "react-best-gradient-color-picker";
import { TwitterShareButton } from "react-share";
import { toast } from "sonner";

import { TwitterIcon } from "@/components";
import { holoCardApi } from "@/features/onboarding/api/holoCardApi";
import {
  Copy01Icon,
  Dices,
  Download01Icon,
  LinkSquare02Icon,
  PaintBoardIcon,
  ReloadIcon,
  Share08Icon,
} from "@/icons";

import { HoloCard } from "./HoloCard";
import type { HoloCardDisplayData } from "./types";

interface HoloCardEditorProps {
  initialData: HoloCardDisplayData;
  height?: number;
  width?: number;
  onUpdate?: (data: Partial<HoloCardDisplayData>) => void;
  showViewProfile?: boolean; // Option to show "View Profile" button in share menu or separately
}

export const HoloCardEditor = ({
  initialData,
  height = 470,
  width = 330,
  onUpdate,
  showViewProfile = false,
}: HoloCardEditorProps) => {
  const [data, setData] = useState<HoloCardDisplayData>(initialData);
  const [color, setColor] = useState(
    initialData.overlay_color || "rgba(0,0,0,0)",
  );
  const [opacity, setOpacity] = useState(initialData.overlay_opacity || 40);
  const [isColorPickerOpen, setIsColorPickerOpen] = useState(false);
  const saveTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    setData(initialData);
    if (initialData.overlay_color) setColor(initialData.overlay_color);
    if (initialData.overlay_opacity !== undefined)
      setOpacity(initialData.overlay_opacity);
  }, [initialData]);

  // Debounced save function
  const saveColors = useCallback((newColor: string, newOpacity: number) => {
    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current);
    }

    saveTimeoutRef.current = setTimeout(() => {
      holoCardApi.updateHoloCardColors(newColor, newOpacity).catch((error) => {
        console.error("Failed to save colors:", error);
        toast.error("Failed to save colors");
      });
    }, 1000);
  }, []);

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
      }
    };
  }, []);

  const handleColorChange = (newColor: string) => {
    setColor(newColor);
    const newData = {
      ...data,
      overlay_color: newColor,
      overlay_opacity: opacity,
    };
    setData(newData);
    onUpdate?.(newData);
    saveColors(newColor, opacity);
  };

  const handleOpacityChange = (newOpacity: number) => {
    setOpacity(newOpacity);
    const newData = {
      ...data,
      overlay_color: color,
      overlay_opacity: newOpacity,
    };
    setData(newData);
    onUpdate?.(newData);
    saveColors(color, newOpacity);
  };

  const cardRef = useRef<HTMLDivElement>(null);

  const handleDownload = useCallback(async () => {
    if (cardRef.current === null) {
      return;
    }

    try {
      const dataUrl = await toPng(cardRef.current, { cacheBust: true });
      const link = document.createElement("a");
      link.download = `holo-card-${data.name || "user"}.png`;
      link.href = dataUrl;
      link.click();
    } catch (err) {
      console.error("Failed to download image", err);
      toast.error("Failed to download image");
    }
  }, [data.name]);

  const handleShare = (platform: "twitter" | "linkedin" | "copy") => {
    if (!data.holo_card_id && typeof window !== "undefined") {
      // Fallback to current URL if no ID (e.g. during onboarding before full persistence if that happens, though usually we have it)
      // Or just warn
    }
    const url = data.holo_card_id
      ? `${window.location.origin}/profile/${data.holo_card_id}`
      : window.location.href;

    switch (platform) {
      case "twitter":
        window.open(
          `https://twitter.com/intent/tweet?text=${encodeURIComponent("Check out my Personal Card made using GAIA\n")}&url=${encodeURIComponent(url)}`,
        );
        break;
      case "linkedin":
        window.open(
          `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(url)}}`,
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

      let r: number, g: number, b: number;
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

    // Randomly decide gradient type with more variety
    const gradientType = Math.random();
    let newColor: string;

    if (gradientType < 0.35) {
      // Linear gradient (35% chance)
      const color1 = generateVibrantColor();
      const color2 = generateVibrantColor();
      const angle = Math.floor(Math.random() * 360);
      newColor = `linear-gradient(${angle}deg, ${color1} 0%, ${color2} 100%)`;
    } else if (gradientType < 0.6) {
      // Radial gradient (25% chance)
      const color1 = generateVibrantColor();
      const color2 = generateVibrantColor();
      const positions = [
        "circle at center",
        "circle at top left",
        "circle at top right",
        "circle at bottom left",
        "circle at bottom right",
        "ellipse at center",
      ];
      const position = positions[Math.floor(Math.random() * positions.length)];
      newColor = `radial-gradient(${position}, ${color1} 0%, ${color2} 100%)`;
    } else if (gradientType < 0.75) {
      // Multi-color gradient (15% chance)
      const color1 = generateVibrantColor();
      const color2 = generateVibrantColor();
      const color3 = generateVibrantColor();
      const angle = Math.floor(Math.random() * 360);
      const stop1 = Math.floor(Math.random() * 30);
      const stop2 = 50 + Math.floor(Math.random() * 20);
      newColor = `linear-gradient(${angle}deg, ${color1} ${stop1}%, ${color2} ${stop2}%, ${color3} 100%)`;
    } else if (gradientType < 0.85) {
      // Conic gradient (10% chance)
      const color1 = generateVibrantColor();
      const color2 = generateVibrantColor();
      const angle = Math.floor(Math.random() * 360);
      newColor = `conic-gradient(from ${angle}deg, ${color1}, ${color2}, ${color1})`;
    } else {
      // Solid color (15% chance)
      newColor = generateVibrantColor();
    }

    // More varied opacity range with occasional extremes
    const opacityRoll = Math.random();
    let newOpacity: number;

    if (opacityRoll < 0.1) {
      // Very subtle (10% chance)
      newOpacity = 10 + Math.floor(Math.random() * 20);
    } else if (opacityRoll < 0.3) {
      // Light (20% chance)
      newOpacity = 30 + Math.floor(Math.random() * 20);
    } else if (opacityRoll < 0.7) {
      // Medium (40% chance)
      newOpacity = 50 + Math.floor(Math.random() * 30);
    } else if (opacityRoll < 0.9) {
      // Strong (20% chance)
      newOpacity = 80 + Math.floor(Math.random() * 15);
    } else {
      // Very intense (10% chance)
      newOpacity = 95 + Math.floor(Math.random() * 5);
    }

    setColor(newColor);
    setOpacity(newOpacity);

    const newData = {
      ...data,
      overlay_color: newColor,
      overlay_opacity: newOpacity,
    };
    setData(newData);
    onUpdate?.(newData);

    saveColors(newColor, newOpacity);
  };

  const handleResetColor = () => {
    const defaultColor = "rgba(0,0,0,0)";
    const defaultOpacity = 40;

    setColor(defaultColor);
    setOpacity(defaultOpacity);

    const newData = {
      ...data,
      overlay_color: defaultColor,
      overlay_opacity: defaultOpacity,
    };
    setData(newData);
    onUpdate?.(newData);

    saveColors(defaultColor, defaultOpacity);
  };

  const shareUrl = data.holo_card_id
    ? `${window.location.origin}/profile/${data.holo_card_id}`
    : window.location.href;
  const shareTitle = "Check out my Personal Card made using GAIA";

  return (
    <div className="flex flex-col items-center gap-4">
      <div>
        <HoloCard
          data={data}
          height={height}
          width={width}
          showSparkles={true}
        />
      </div>

      <ButtonGroup className="mt-2">
        {/* <Tooltip content="Download your card" placement="top">
          <Button
            isIconOnly
            variant="flat"
            onPress={handleDownload}
            aria-label="Download"
          >
            <Download01Icon size={20} />
          </Button>
        </Tooltip> */}

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
              >
                <TwitterShareButton url={shareUrl} title={shareTitle}>
                  Twitter
                </TwitterShareButton>
              </DropdownItem>
              <DropdownItem
                key="copy"
                startContent={<Copy01Icon size={16} />}
                onPress={() => handleShare("copy")}
              >
                Copy Link
              </DropdownItem>
              {showViewProfile && data.holo_card_id ? (
                <DropdownItem
                  key="view"
                  startContent={<LinkSquare02Icon size={16} />}
                  onPress={() =>
                    window.open(`/profile/${data.holo_card_id}`, "_blank")
                  }
                >
                  View Profile
                </DropdownItem>
              ) : null}
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
                {(() => {
                  // Show color swatch if color is set and not transparent
                  if (
                    typeof color === "string" &&
                    color !== "rgba(0,0,0,0)" &&
                    color.trim() !== ""
                  ) {
                    // Gradient detection
                    if (color.startsWith("linear-gradient")) {
                      // Extract angle if present
                      const angleMatch = color.match(
                        /linear-gradient\((\d+)deg/,
                      );
                      const angle = angleMatch
                        ? parseInt(angleMatch[1], 10)
                        : 0;
                      return (
                        <span
                          className="border-1 border-zinc-300"
                          style={{
                            display: "inline-block",
                            width: 24,
                            height: 24,
                            borderRadius: "50%",
                            background: color,
                            transform: `rotate(${angle}deg)`,
                          }}
                        />
                      );
                    } else {
                      // Solid color
                      return (
                        <span
                          className="border-1 border-zinc-300"
                          style={{
                            display: "inline-block",
                            width: 24,
                            height: 24,
                            borderRadius: "50%",
                            background: color,
                          }}
                        />
                      );
                    }
                  }
                  // Default icon if no color
                  return <PaintBoardIcon width={20} height={20} />;
                })()}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-auto bg-zinc-800 p-4">
              <div className="flex flex-col gap-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-white/70">Color Picker</span>
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
                  onChange={handleColorChange}
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
                    <span className="text-xs text-white/50">{opacity}%</span>
                  </div>
                  <Slider
                    size="sm"
                    step={1}
                    minValue={0}
                    maxValue={100}
                    value={opacity}
                    onChange={(value) => handleOpacityChange(value as number)}
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
      {/* Hidden container for download */}
      <div
        style={{
          position: "fixed",
          top: -10000,
          left: -10000,
          opacity: 0,
          pointerEvents: "none",
        }}
      >
        <div
          ref={cardRef}
          className="flex items-center gap-8 bg-transparent p-8"
        >
          <div style={{ width, height }}>
            <HoloCard
              data={data}
              height={height}
              width={width}
              showSparkles={false}
              forceSide="front"
            />
          </div>
          <div style={{ width, height }}>
            <HoloCard
              data={data}
              height={height}
              width={width}
              showSparkles={false}
              forceSide="back"
            />
          </div>
        </div>
      </div>
    </div>
  );
};
