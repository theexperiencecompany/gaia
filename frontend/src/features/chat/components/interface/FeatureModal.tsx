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

type House = "Frostpeak" | "Greenvale" | "Starforge" | "Bluehaven";

const HOUSES: Record<House, { image: string }> = {
  Frostpeak: { image: "/images/wallpapers/holo/frostpeak.webp" },
  Greenvale: { image: "/images/wallpapers/holo/greenvale.webp" },
  Starforge: { image: "/images/wallpapers/holo/starforge.webp" },
  Bluehaven: { image: "/images/wallpapers/holo/bluehaven.webp" },
};

export default function FeatureModal({ isOpen, onClose }: FeatureModalProps) {
  const [color, setColor] = useState("rgba(0,0,0,0)");
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

    // Helper to generate vibrant, distinct colors
    const generateVibrantColor = () => {
      // Use HSL for more vibrant, distinct colors
      const hue = Math.floor(Math.random() * 360);
      const saturation = 70 + Math.floor(Math.random() * 30); // 70-100%
      const lightness = 40 + Math.floor(Math.random() * 30); // 40-70%
      return `hsl(${hue}, ${saturation}%, ${lightness}%)`;
    };

    if (isGradient) {
      // Generate random gradient with vibrant colors
      const color1 = generateVibrantColor();
      const color2 = generateVibrantColor();
      const angle = Math.floor(Math.random() * 360);
      const gradientType = Math.random() > 0.5 ? "linear" : "radial";

      if (gradientType === "linear") {
        setColor(`linear-gradient(${angle}deg, ${color1} 0%, ${color2} 100%)`);
      } else {
        setColor(`radial-gradient(circle, ${color1} 0%, ${color2} 100%)`);
      }
    } else {
      // Generate random solid vibrant color
      setColor(generateVibrantColor());
    }

    // Randomize opacity too
    setOpacity(30 + Math.floor(Math.random() * 50)); // 30-80%
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
      scrollBehavior="inside"
      isDismissable={true}
      className="h-[80vh]"
      backdrop="blur"
    >
      <ModalContent className="border-0! bg-transparent shadow-none outline-0!">
        <ModalBody>
          <div className="group relative flex h-full w-full flex-col items-center justify-center gap-4">
            <Select
              label="Select House"
              selectedKeys={[selectedHouse]}
              onSelectionChange={(keys) => {
                const selected = Array.from(keys)[0] as House;
                setSelectedHouse(selected);
              }}
              className="max-w-xs"
              variant="bordered"
            >
              {Object.keys(HOUSES).map((house) => (
                <SelectItem key={house}>{house}</SelectItem>
              ))}
            </Select>
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
