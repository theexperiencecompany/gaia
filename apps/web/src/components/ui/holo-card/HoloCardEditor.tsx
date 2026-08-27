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
import {
  Copy01Icon,
  Download01Icon,
  LinkSquare02Icon,
  PaintBoardIcon,
  ReloadIcon,
  Share08Icon,
} from "@icons";
import { toPng } from "html-to-image";
import {
  type RefObject,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import ColorPicker from "react-best-gradient-color-picker";
import { TwitterShareButton } from "react-share";

/** Uniform [0,1) from Web Crypto. The card randomizer is cosmetic, but
 * crypto-grade randomness keeps security scanners quiet and costs nothing. */
function random(): number {
  return crypto.getRandomValues(new Uint32Array(1))[0] / 2 ** 32;
}

import { Dices, TwitterIcon } from "@/components/shared/icons";
import { holoCardApi } from "@/features/onboarding/api/holoCardApi";
import { toast } from "@/lib/toast";

import { HoloCard } from "./HoloCard";
import type { HoloCardDisplayData } from "./types";
import { mergeIncomingCard } from "./utils";

interface HoloCardEditorProps {
  initialData: HoloCardDisplayData;
  height?: number;
  width?: number;
  onUpdate?: (data: Partial<HoloCardDisplayData>) => void;
  showViewProfile?: boolean; // Option to show "View Profile" button in share menu or separately
}

// Generates a vibrant, distinct color in RGBA format.
const generateVibrantColor = (): string => {
  const hue = Math.floor(random() * 360);
  const saturation = 70 + Math.floor(random() * 30);
  const lightness = 40 + Math.floor(random() * 30);

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

// Picks a random overlay style — linear/radial/multi-stop/conic gradient or a
// solid color — plus a varied opacity.
const generateRandomOverlay = (): { color: string; opacity: number } => {
  // Randomly decide gradient type with more variety
  const gradientType = random();
  let color: string;

  if (gradientType < 0.35) {
    // Linear gradient (35% chance)
    const color1 = generateVibrantColor();
    const color2 = generateVibrantColor();
    const angle = Math.floor(random() * 360);
    color = `linear-gradient(${angle}deg, ${color1} 0%, ${color2} 100%)`;
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
    const position = positions[Math.floor(random() * positions.length)];
    color = `radial-gradient(${position}, ${color1} 0%, ${color2} 100%)`;
  } else if (gradientType < 0.75) {
    // Multi-color gradient (15% chance)
    const color1 = generateVibrantColor();
    const color2 = generateVibrantColor();
    const color3 = generateVibrantColor();
    const angle = Math.floor(random() * 360);
    const stop1 = Math.floor(random() * 30);
    const stop2 = 50 + Math.floor(random() * 20);
    color = `linear-gradient(${angle}deg, ${color1} ${stop1}%, ${color2} ${stop2}%, ${color3} 100%)`;
  } else if (gradientType < 0.85) {
    // Conic gradient (10% chance)
    const color1 = generateVibrantColor();
    const color2 = generateVibrantColor();
    const angle = Math.floor(random() * 360);
    color = `conic-gradient(from ${angle}deg, ${color1}, ${color2}, ${color1})`;
  } else {
    // Solid color (15% chance)
    color = generateVibrantColor();
  }

  // More varied opacity range with occasional extremes
  const opacityRoll = random();
  let opacity: number;

  if (opacityRoll < 0.1) {
    // Very subtle (10% chance)
    opacity = 10 + Math.floor(random() * 20);
  } else if (opacityRoll < 0.3) {
    // Light (20% chance)
    opacity = 30 + Math.floor(random() * 20);
  } else if (opacityRoll < 0.7) {
    // Medium (40% chance)
    opacity = 50 + Math.floor(random() * 30);
  } else if (opacityRoll < 0.9) {
    // Strong (20% chance)
    opacity = 80 + Math.floor(random() * 15);
  } else {
    // Very intense (10% chance)
    opacity = 95 + Math.floor(random() * 5);
  }

  return { color, opacity };
};

// Swatch shown inside the color-picker trigger; falls back to the palette
// icon while no color is set.
const ColorSwatch = ({ color }: { color: string }) => {
  if (color === "rgba(0,0,0,0)" || color.trim() === "") {
    return <PaintBoardIcon width={20} height={20} />;
  }

  const isLinear = color.startsWith("linear-gradient");
  const angleMatch = isLinear ? color.match(/linear-gradient\((\d+)deg/) : null;
  const angle = angleMatch ? parseInt(angleMatch[1], 10) : 0;

  return (
    <span
      className="border-1 border-zinc-300"
      style={{
        display: "inline-block",
        width: 24,
        height: 24,
        borderRadius: "50%",
        background: color,
        ...(isLinear ? { transform: `rotate(${angle}deg)` } : {}),
      }}
    />
  );
};

interface EditorToolbarProps {
  shareUrl: string;
  shareTitle: string;
  showViewProfile: boolean;
  holoCardId?: string;
  color: string;
  opacity: number;
  isColorPickerOpen: boolean;
  onColorPickerOpenChange: (open: boolean) => void;
  onShare: (platform: "twitter" | "linkedin" | "copy") => void;
  onColorChange: (color: string) => void;
  onOpacityChange: (opacity: number) => void;
  onResetColor: () => void;
  onRandomize: () => void;
  onDownload: () => void;
}

const EditorToolbar = ({
  shareUrl,
  shareTitle,
  showViewProfile,
  holoCardId,
  color,
  opacity,
  isColorPickerOpen,
  onColorPickerOpenChange,
  onShare,
  onColorChange,
  onOpacityChange,
  onResetColor,
  onRandomize,
  onDownload,
}: EditorToolbarProps) => (
  <ButtonGroup className="mt-2">
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
            onPress={() => onShare("copy")}
          >
            Copy Link
          </DropdownItem>
          {showViewProfile && holoCardId ? (
            <DropdownItem
              key="view"
              startContent={<LinkSquare02Icon size={16} />}
              onPress={() => window.open(`/profile/${holoCardId}`, "_blank")}
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
        onOpenChange={onColorPickerOpenChange}
        placement="top"
      >
        <PopoverTrigger>
          <Button isIconOnly variant="flat" aria-label="Color Picker">
            <ColorSwatch color={color} />
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
                onPress={onResetColor}
                aria-label="Reset Color"
              >
                <ReloadIcon size={16} />
              </Button>
            </div>
            <ColorPicker
              value={color}
              onChange={onColorChange}
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
                onChange={(value) => onOpacityChange(value as number)}
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
        onPress={onRandomize}
        aria-label="Randomize"
      >
        <Dices size={20} />
      </Button>
    </Tooltip>

    <Tooltip content="Download your card" placement="top">
      <Button
        isIconOnly
        variant="flat"
        onPress={onDownload}
        aria-label="Download"
      >
        <Download01Icon size={20} />
      </Button>
    </Tooltip>
  </ButtonGroup>
);

interface HiddenDownloadCardsProps {
  cardRef: RefObject<HTMLDivElement | null>;
  data: HoloCardDisplayData;
  height: number;
  width: number;
}

// Offscreen static front/back pair that html-to-image snapshots into the PNG
// download.
const HiddenDownloadCards = ({
  cardRef,
  data,
  height,
  width,
}: HiddenDownloadCardsProps) => (
  <div
    style={{
      position: "fixed",
      top: -10000,
      left: -10000,
      opacity: 0,
      pointerEvents: "none",
    }}
  >
    <div ref={cardRef} className="flex items-center gap-8 bg-transparent p-8">
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
);

// Owns the overlay color/opacity state, its persistence to the API, and every
// mutation path (picker, slider, randomize, reset).
function useHoloCardColors(
  initialData: HoloCardDisplayData,
  onUpdate?: (data: Partial<HoloCardDisplayData>) => void,
) {
  const [data, setData] = useState<HoloCardDisplayData>(initialData);
  const saveTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Reset the editable copy during render when a new card object arrives — the
  // React-recommended alternative to a post-render sync effect, so nothing
  // stale ever paints.
  const [prevInitialData, setPrevInitialData] = useState(initialData);
  if (prevInitialData !== initialData) {
    setPrevInitialData(initialData);
    setData((prev) => mergeIncomingCard(prev, initialData, prevInitialData));
  }

  // Overlay color/opacity are pure derivations of `data` — no mirrored state.
  const color = data.overlay_color || "rgba(0,0,0,0)";
  const opacity = data.overlay_opacity || 40;

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

  const applyOverlay = (overlayColor: string, overlayOpacity: number) => {
    const newData = {
      ...data,
      overlay_color: overlayColor,
      overlay_opacity: overlayOpacity,
    };
    setData(newData);
    onUpdate?.(newData);
    saveColors(overlayColor, overlayOpacity);
  };

  const handleColorChange = (newColor: string) => {
    applyOverlay(newColor, opacity);
  };

  const handleOpacityChange = (newOpacity: number) => {
    applyOverlay(color, newOpacity);
  };

  const handleRandomize = () => {
    const { color: newColor, opacity: newOpacity } = generateRandomOverlay();
    applyOverlay(newColor, newOpacity);
  };

  const handleResetColor = () => {
    applyOverlay("rgba(0,0,0,0)", 40);
  };

  return {
    data,
    color,
    opacity,
    handleColorChange,
    handleOpacityChange,
    handleRandomize,
    handleResetColor,
  };
}

export const HoloCardEditor = ({
  initialData,
  height = 470,
  width = 330,
  onUpdate,
  showViewProfile = false,
}: HoloCardEditorProps) => {
  const {
    data,
    color,
    opacity,
    handleColorChange,
    handleOpacityChange,
    handleRandomize,
    handleResetColor,
  } = useHoloCardColors(initialData, onUpdate);
  const [isColorPickerOpen, setIsColorPickerOpen] = useState(false);

  // Resolved on the client only — reading window during render crashes SSR.
  const [origin, setOrigin] = useState<string>("");
  const [href, setHref] = useState<string>("");
  useEffect(() => {
    setOrigin(window.location.origin);
    setHref(window.location.href);
  }, []);

  const cardRef = useRef<HTMLDivElement>(null);

  const handleDownload = useCallback(async () => {
    if (cardRef.current === null) return;
    try {
      // Wait for images to decode before snapshotting, else html-to-image clones empty placeholders into the PNG.
      const imgs = Array.from(cardRef.current.querySelectorAll("img"));
      await Promise.all(
        imgs.map((img) => {
          if (img.complete && img.naturalWidth > 0) return Promise.resolve();
          return img.decode().catch(() => undefined);
        }),
      );

      const dataUrl = await toPng(cardRef.current, {
        cacheBust: true,
        pixelRatio: 2,
        backgroundColor: "transparent",
      });
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

  const shareUrl = data.holo_card_id
    ? `${origin}/profile/${data.holo_card_id}`
    : href;
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

      <EditorToolbar
        shareUrl={shareUrl}
        shareTitle={shareTitle}
        showViewProfile={showViewProfile}
        holoCardId={data.holo_card_id}
        color={color}
        opacity={opacity}
        isColorPickerOpen={isColorPickerOpen}
        onColorPickerOpenChange={setIsColorPickerOpen}
        onShare={handleShare}
        onColorChange={handleColorChange}
        onOpacityChange={handleOpacityChange}
        onResetColor={handleResetColor}
        onRandomize={handleRandomize}
        onDownload={handleDownload}
      />

      <HiddenDownloadCards
        cardRef={cardRef}
        data={data}
        height={height}
        width={width}
      />
    </div>
  );
};
