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
import {
  Dropdown,
  DropdownTrigger,
  DropdownMenu,
  DropdownItem,
} from "@heroui/dropdown";
import { Popover, PopoverContent, PopoverTrigger } from "@heroui/popover";
import { Slider } from "@heroui/slider";
import { Tooltip } from "@heroui/tooltip";
import {
  Download,
  Share2,
  Palette,
  Dices,
  Link,
  RotateCcw,
  Brain,
} from "lucide-react";
import { useState, useEffect, useRef, Suspense } from "react";
import ColorPicker from "react-best-gradient-color-picker";
import { toast } from "sonner";
import UseCaseCard from "@/features/use-cases/components/UseCaseCard";
import { SimpleChatBubbleBot } from "@/features/landing/components/demo/SimpleChatBubbles";
import confetti from "canvas-confetti";
import { Skeleton } from "@heroui/skeleton";

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

const suggestedWorkflows = [
  {
    title: "Daily Email Summary",
    description:
      "Get a smart summary of your emails every morning with action items highlighted",
    action_type: "workflow" as const,
    integrations: ["gmail"],
    steps: [{ tool_category: "gmail" }, { tool_category: "openai" }],
  },
  {
    title: "Meeting Scheduler",
    description:
      "Automatically schedule meetings based on availability and preferences",
    action_type: "workflow" as const,
    integrations: ["google_calendar"],
    steps: [{ tool_category: "google_calendar" }, { tool_category: "gmail" }],
  },
  {
    title: "Task Automation",
    description: "Create tasks from emails and calendar events automatically",
    action_type: "workflow" as const,
    integrations: ["gmail", "google_calendar"],
    steps: [
      { tool_category: "gmail" },
      { tool_category: "google_calendar" },
      { tool_category: "openai" },
    ],
  },
  {
    title: "Document Intelligence",
    description: "Extract and summarize key information from your documents",
    action_type: "workflow" as const,
    integrations: ["google_drive"],
    steps: [{ tool_category: "google_drive" }, { tool_category: "openai" }],
  },
  {
    title: "Slack Digest",
    description: "Get important Slack messages and threads summarized daily",
    action_type: "workflow" as const,
    integrations: ["slack"],
    steps: [{ tool_category: "slack" }, { tool_category: "openai" }],
  },
];

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
  const [isColorPickerOpen, setIsColorPickerOpen] = useState(false);
  const [selectedHouse, setSelectedHouse] = useState<House>("Bluehaven");
  const hasShownConfetti = useRef(false);

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
  };

  const handleResetColor = () => {
    setColor("rgba(0,0,0,0)");
    setOpacity(40);
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
              {
                "I've put together some workflows to get you started.<NEW_MESSAGE_BREAK>Try any of these or create your own!"
              }
            </SimpleChatBubbleBot>

            <div className="mt-5 grid w-full grid-cols-3 gap-2 pl-12">
              {suggestedWorkflows.map((workflow, index) => (
                <UseCaseCard
                  key={index}
                  title={workflow.title}
                  description={workflow.description}
                  action_type={workflow.action_type}
                  integrations={workflow.integrations}
                  steps={workflow.steps}
                />
              ))}
            </div>

            <SimpleChatBubbleBot>
              {
                "Your very own GAIA Card is waiting on the right! 🎨✨<NEW_MESSAGE_BREAK>Go wild with the customization tools and show off your masterpiece to the world! 🚀"
              }
            </SimpleChatBubbleBot>
            <div className="mt-2 ml-12">
              <Button
                color="primary"
                className="font-medium"
                startContent={<TwitterIcon width={18} height={18} />}
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
                  url={HOUSES[selectedHouse].image}
                  height={470}
                  width={330}
                  showSparkles={true}
                  overlayColor={color}
                  overlayOpacity={opacity}
                  houseName={selectedHouse}
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
                        startContent={<Link size={16} />}
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
                        <Palette size={20} />
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
                            onChange={(value) => setOpacity(value as number)}
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
