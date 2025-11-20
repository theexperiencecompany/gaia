"use client";

import { LinkedinIcon, TwitterIcon } from "@/components";
import { HoloCard } from "@/components/ui/magic-ui/holo-card";
import { Button, ButtonGroup } from "@heroui/button";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { Popover, PopoverContent, PopoverTrigger } from "@heroui/popover";
import { Select, SelectItem } from "@heroui/select";
import { Slider } from "@heroui/slider";
import {
  Download,
  Share2,
  Palette,
  Dices,
  Link,
  RotateCcw,
} from "lucide-react";
import { useState } from "react";
import ColorPicker from "react-best-gradient-color-picker";
import { toast } from "sonner";

interface FeatureModalProps {
  isOpen: boolean;
  onClose: () => void;
}

type House = "Frostpeak" | "Greenvale" | "Mistgrove" | "Bluehaven";

const HOUSES: Record<House, { image: string }> = {
  Frostpeak: {
    image:
      "https://i.pinimg.com/1200x/bf/1a/99/bf1a99c4c2cd8f378b9e4493f71e7e64.jpg",
  },
  Greenvale: {
    image:
      "https://i.pinimg.com/1200x/3b/3e/11/3b3e1167fcfb0933070b6064ce9c72cd.jpg",
  },
  Mistgrove: { image: "/images/wallpapers/holo/mistgrove.png" },
  Bluehaven: {
    image:
      "https://i.pinimg.com/1200x/27/0a/74/270a74bdc412f9eeae4d2403ebc9bd63.jpg",
  },
};

const generateRandomColor = () => {
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

export default function FeatureModal({ isOpen, onClose }: FeatureModalProps) {
  const [color, setColor] = useState(generateRandomColor());
  const [opacity, setOpacity] = useState(40);
  const [isShareOpen, setIsShareOpen] = useState(false);
  const [isColorPickerOpen, setIsColorPickerOpen] = useState(false);
  const [selectedHouse, setSelectedHouse] = useState<House>("Bluehaven");

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
    setIsShareOpen(false);
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

    if (isGradient) {
      // Generate random gradient with vibrant colors
      const color1 = generateVibrantColor();
      const color2 = generateVibrantColor();
      const angle = Math.floor(Math.random() * 360);

      setColor(`linear-gradient(${angle}deg, ${color1} 0%, ${color2} 100%)`);
    } else {
      // Generate random solid vibrant color
      setColor(generateVibrantColor());
    }

    // Randomize opacity too
    setOpacity(30 + Math.floor(Math.random() * 50)); // 30-80%
    toast.info("Color randomized!");
  };

  const handleResetColor = () => {
    setColor("rgba(0,0,0,0)");
    setOpacity(40);
    toast.success("Color reset to transparent");
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size="5xl"
      //   scrollBehavior="inside"
      isDismissable={true}
      className="h-[80vh]"
      backdrop="blur"
    >
      <ModalContent className="border-0! bg-transparent shadow-none outline-0!">
        <ModalBody>
          <div className="group relative flex h-full w-full flex-col items-center justify-center gap-4">
            {/* <Select
              label="Select House"
              selectedKeys={[selectedHouse]}
              onSelectionChange={(keys) => {
                const selected = Array.from(keys)[0] as House;
                setSelectedHouse(selected);
              }}
              className="max-w-xs"
              variant="flat"
            >
              {Object.keys(HOUSES).map((house) => (
                <SelectItem key={house}>{house}</SelectItem>
              ))}
            </Select> */}

            <div className="mb-3 text-zinc-300">Click to flip card</div>

            <HoloCard
              url={HOUSES[selectedHouse].image}
              height={500}
              width={350}
              showSparkles={true}
              overlayColor={color}
              overlayOpacity={opacity}
              houseName={selectedHouse}
            />
          </div>
        </ModalBody>
        <ModalFooter className="flex justify-center">
          <ButtonGroup>
            <Button
              isIconOnly
              variant="flat"
              onPress={handleDownload}
              aria-label="Download"
            >
              <Download size={20} />
            </Button>

            <Popover
              isOpen={isShareOpen}
              onOpenChange={setIsShareOpen}
              placement="top"
            >
              <PopoverTrigger>
                <Button isIconOnly variant="flat" aria-label="Share">
                  <Share2 size={20} />
                </Button>
              </PopoverTrigger>
              <PopoverContent className="p-2">
                <div className="flex flex-col gap-2">
                  <Button
                    size="sm"
                    variant="light"
                    startContent={<TwitterIcon width={16} height={16} />}
                    onPress={() => handleShare("twitter")}
                  >
                    Twitter
                  </Button>
                  <Button
                    size="sm"
                    variant="light"
                    startContent={<LinkedinIcon width={16} height={16} />}
                    onPress={() => handleShare("linkedin")}
                  >
                    LinkedIn
                  </Button>
                  <Button
                    size="sm"
                    variant="light"
                    startContent={<Link size={16} />}
                    onPress={() => handleShare("copy")}
                  >
                    Copy Link
                  </Button>
                </div>
              </PopoverContent>
            </Popover>

            <Popover
              isOpen={isColorPickerOpen}
              onOpenChange={setIsColorPickerOpen}
              placement="top"
            >
              <PopoverTrigger>
                <Button isIconOnly variant="flat" aria-label="Color Picker">
                  <Palette size={20} />
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
                      <RotateCcw size={16} />
                    </Button>
                  </div>
                  <ColorPicker
                    value={color}
                    onChange={setColor}
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
                      onChange={(value) => setOpacity(value as number)}
                      className="max-w-md"
                    />
                  </div>
                </div>
              </PopoverContent>
            </Popover>

            <Button
              isIconOnly
              variant="flat"
              onPress={handleRandomize}
              aria-label="Randomize"
            >
              <Dices size={20} />
            </Button>
          </ButtonGroup>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
