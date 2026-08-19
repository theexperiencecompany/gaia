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
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ColorPicker from "react-best-gradient-color-picker";
import { TwitterShareButton } from "react-share";
import { Dices, TwitterIcon } from "@/components/shared/icons";
import { holoCardApi } from "@/features/onboarding/api/holoCardApi";
import { toast } from "@/lib/toast";

import { HoloCard } from "./HoloCard";
import type { HoloCardDisplayData } from "./types";

interface HoloCardEditorProps {
  initialData: HoloCardDisplayData;
  height?: number;
  width?: number;
  onUpdate?: (data: Partial<HoloCardDisplayData>) => void;
  showViewProfile?: boolean;
}

function generateVibrantColor(): string {
  const hue = Math.floor(Math.random() * 360);
  const saturation = 70 + Math.floor(Math.random() * 30);
  const lightness = 40 + Math.floor(Math.random() * 30);

  const h = hue / 360;
  const s = saturation / 100;
  const l = lightness / 100;

  let r: number;
  let g: number;
  let b: number;
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
}

function generateRandomHoloStyle(): { color: string; opacity: number } {
  const gradientType = Math.random();
  let newColor: string;

  if (gradientType < 0.35) {
    const color1 = generateVibrantColor();
    const color2 = generateVibrantColor();
    const angle = Math.floor(Math.random() * 360);
    newColor = `linear-gradient(${angle}deg, ${color1} 0%, ${color2} 100%)`;
  } else if (gradientType < 0.6) {
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
    const color1 = generateVibrantColor();
    const color2 = generateVibrantColor();
    const color3 = generateVibrantColor();
    const angle = Math.floor(Math.random() * 360);
    const stop1 = Math.floor(Math.random() * 30);
    const stop2 = 50 + Math.floor(Math.random() * 20);
    newColor = `linear-gradient(${angle}deg, ${color1} ${stop1}%, ${color2} ${stop2}%, ${color3} 100%)`;
  } else if (gradientType < 0.85) {
    const color1 = generateVibrantColor();
    const color2 = generateVibrantColor();
    const angle = Math.floor(Math.random() * 360);
    newColor = `conic-gradient(from ${angle}deg, ${color1}, ${color2}, ${color1})`;
  } else {
    newColor = generateVibrantColor();
  }

  const opacityRoll = Math.random();
  let newOpacity: number;
  if (opacityRoll < 0.1) {
    newOpacity = 10 + Math.floor(Math.random() * 20);
  } else if (opacityRoll < 0.3) {
    newOpacity = 30 + Math.floor(Math.random() * 20);
  } else if (opacityRoll < 0.7) {
    newOpacity = 50 + Math.floor(Math.random() * 30);
  } else if (opacityRoll < 0.9) {
    newOpacity = 80 + Math.floor(Math.random() * 15);
  } else {
    newOpacity = 95 + Math.floor(Math.random() * 5);
  }

  return { color: newColor, opacity: newOpacity };
}

function HoloCardColorSwatch({ color }: { color: string }) {
  if (
    typeof color === "string" &&
    color !== "rgba(0,0,0,0)" &&
    color.trim() !== ""
  ) {
    if (color.startsWith("linear-gradient")) {
      const angleMatch = color.match(/linear-gradient\((\d+)deg/);
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
            transform: `rotate(${angle}deg)`,
          }}
        />
      );
    }
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
  return <PaintBoardIcon width={20} height={20} />;
}

function HoloCardColorPickerPanel({
  color,
  opacity,
  onColorChange,
  onOpacityChange,
  onReset,
}: {
  color: string;
  opacity: number;
  onColorChange: (c: string) => void;
  onOpacityChange: (o: number) => void;
  onReset: () => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-sm text-white/70">Color Picker</span>
        <Button
          size="sm"
          variant="light"
          isIconOnly
          onPress={onReset}
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
  );
}

function HoloCardShareMenu({
  shareUrl,
  shareTitle,
  holoCardId,
  showViewProfile,
  onCopy,
}: {
  shareUrl: string;
  shareTitle: string;
  holoCardId?: string;
  showViewProfile: boolean;
  onCopy: () => void;
}) {
  return (
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
        onPress={onCopy}
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
  );
}

function HoloCardEditorToolbar({
  color,
  opacity,
  shareUrl,
  shareTitle,
  holoCardId,
  showViewProfile,
  isColorPickerOpen,
  onColorPickerOpenChange,
  onColorChange,
  onOpacityChange,
  onResetColor,
  onRandomize,
  onDownload,
  onCopyLink,
}: {
  color: string;
  opacity: number;
  shareUrl: string;
  shareTitle: string;
  holoCardId?: string;
  showViewProfile: boolean;
  isColorPickerOpen: boolean;
  onColorPickerOpenChange: (open: boolean) => void;
  onColorChange: (c: string) => void;
  onOpacityChange: (o: number) => void;
  onResetColor: () => void;
  onRandomize: () => void;
  onDownload: () => void;
  onCopyLink: () => void;
}) {
  return (
    <ButtonGroup className="mt-2">
      <Tooltip content="Share your card" placement="top">
        <Dropdown placement="top">
          <DropdownTrigger>
            <Button isIconOnly variant="flat" aria-label="Share">
              <Share08Icon size={20} />
            </Button>
          </DropdownTrigger>
          <HoloCardShareMenu
            shareUrl={shareUrl}
            shareTitle={shareTitle}
            holoCardId={holoCardId}
            showViewProfile={showViewProfile}
            onCopy={onCopyLink}
          />
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
              <HoloCardColorSwatch color={color} />
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-auto bg-zinc-800 p-4">
            <HoloCardColorPickerPanel
              color={color}
              opacity={opacity}
              onColorChange={onColorChange}
              onOpacityChange={onOpacityChange}
              onReset={onResetColor}
            />
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
}

function HoloCardDownloadPreview({
  cardRef,
  data,
  height,
  width,
}: {
  cardRef: React.RefObject<HTMLDivElement | null>;
  data: HoloCardDisplayData;
  height: number;
  width: number;
}) {
  return (
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
    if (cardRef.current === null) return;
    try {
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

  const handleShareCopy = () => {
    const url = data.holo_card_id
      ? `${window.location.origin}/profile/${data.holo_card_id}`
      : window.location.href;
    navigator.clipboard.writeText(url);
    toast.success("Link copied to clipboard");
  };

  const handleRandomize = () => {
    const { color: newColor, opacity: newOpacity } = generateRandomHoloStyle();
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

  const shareUrl = useMemo(() => {
    if (typeof window === "undefined") return "";
    return data.holo_card_id
      ? `${window.location.origin}/profile/${data.holo_card_id}`
      : window.location.href;
  }, [data.holo_card_id]);
  const shareTitle = "Check out my Personal Card made using GAIA";

  return (
    <div className="flex flex-col items-center gap-4">
      <div>
        <HoloCard data={data} height={height} width={width} showSparkles />
      </div>

      <HoloCardEditorToolbar
        color={color}
        opacity={opacity}
        shareUrl={shareUrl}
        shareTitle={shareTitle}
        holoCardId={data.holo_card_id}
        showViewProfile={showViewProfile}
        isColorPickerOpen={isColorPickerOpen}
        onColorPickerOpenChange={setIsColorPickerOpen}
        onColorChange={handleColorChange}
        onOpacityChange={handleOpacityChange}
        onResetColor={handleResetColor}
        onRandomize={handleRandomize}
        onDownload={handleDownload}
        onCopyLink={handleShareCopy}
      />
      <HoloCardDownloadPreview
        cardRef={cardRef}
        data={data}
        height={height}
        width={width}
      />
    </div>
  );
};
