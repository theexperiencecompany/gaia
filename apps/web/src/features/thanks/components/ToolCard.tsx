"use client";

import { Tooltip } from "@heroui/tooltip";
import Image from "next/image";
import { memo, useRef, useState } from "react";
import tinycolor from "tinycolor2";

import { useTheme } from "@/components/providers/ThemeProvider";
import type { Tool } from "@/data/tools";
import { GlobalIcon } from "@/icons";

interface ToolMetadata {
  title: string | null;
  description: string | null;
  favicon: string | null;
  website_name: string | null;
  website_image: string | null;
  url: string;
}

interface ToolCardProps {
  tool: Tool;
  metadata?: ToolMetadata;
}

const ToolCard = memo(({ tool, metadata }: ToolCardProps) => {
  const elementRef = useRef<HTMLAnchorElement>(null);
  const [faviconError, setFaviconError] = useState(false);
  const [imageError, setImageError] = useState(false);
  const [faviconBrightness, setFaviconBrightness] = useState<number | null>(
    null,
  );
  const { resolvedTheme } = useTheme();

  const checkImageBrightness = (imgElement: HTMLImageElement) => {
    try {
      const canvas = document.createElement("canvas");
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      // Scale down to 10x10 for faster sampling - browser handles averaging
      const size = 10;
      canvas.width = size;
      canvas.height = size;

      ctx.drawImage(imgElement, 0, 0, size, size);
      const imageData = ctx.getImageData(0, 0, size, size);
      const data = imageData.data;

      let r = 0;
      let g = 0;
      let b = 0;
      const pixelCount = data.length / 4;

      for (let i = 0; i < data.length; i += 4) {
        r += data[i];
        g += data[i + 1];
        b += data[i + 2];
      }

      const avgColor = tinycolor({
        r: Math.round(r / pixelCount),
        g: Math.round(g / pixelCount),
        b: Math.round(b / pixelCount),
      });

      setFaviconBrightness(avgColor.getBrightness());
    } catch {
      // CORS or other errors - skip brightness check
      setFaviconBrightness(null);
    }
  };

  // In dark mode, invert dark icons. In light mode, invert light icons.
  const shouldInvert =
    faviconBrightness !== null &&
    (resolvedTheme === "dark"
      ? faviconBrightness < 30
      : faviconBrightness > 220);

  const favicon = metadata?.favicon && !faviconError ? metadata.favicon : null;
  const websiteImage =
    metadata?.website_image && !imageError ? metadata.website_image : null;

  return (
    <Tooltip
      showArrow
      delay={0}
      closeDelay={0}
      className="max-w-[320px] border-0 bg-surface-100 p-0 text-foreground-900 shadow-xl rounded-2xl overflow-hidden"
      content={
        <div className="flex w-full flex-col rounded-3xl">
          {websiteImage && (
            <div className="relative aspect-video w-full overflow-hidden">
              <Image
                src={websiteImage}
                alt={`${tool.name} preview`}
                fill
                className="object-cover"
                onError={() => setImageError(true)}
              />
            </div>
          )}
          <div className="flex flex-col gap-2 p-4">
            <div className="flex items-center gap-2">
              {favicon ? (
                <Image
                  width={20}
                  height={20}
                  alt={`${tool.name} favicon`}
                  className={`h-5 w-5 rounded-sm ${
                    shouldInvert ? "invert" : ""
                  }`}
                  src={favicon}
                  onLoad={(e) => checkImageBrightness(e.currentTarget)}
                  onError={() => setFaviconError(true)}
                />
              ) : (
                <GlobalIcon className="h-5 w-5 text-foreground-400" />
              )}
              <span className="font-semibold text-foreground-900">{tool.name}</span>
            </div>

            <p className="text-sm leading-relaxed text-foreground-600">
              {tool.description}
            </p>

            <div className="mt-1 flex items-center gap-2">
              <span className="rounded-full bg-surface-200 px-2 py-0.5 text-xs text-foreground-400">
                {tool.category}
              </span>
            </div>

            <a
              href={tool.url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-1 truncate text-xs text-primary hover:underline"
            >
              {tool.url.replace("https://", "").replace("http://", "")}
            </a>
          </div>
        </div>
      }
    >
      <a
        ref={elementRef}
        href={tool.url}
        target="_blank"
        rel="noopener noreferrer"
        className="group flex items-center gap-3 rounded-2xl bg-surface-100 px-4 py-3 transition-all duration-200 hover:border-primary/50 hover:bg-surface-200/50"
      >
        <div
          className={`relative flex h-8 w-8 items-center justify-center overflow-hidden rounded-lg ${
            favicon ? "" : "bg-surface-200"
          }`}
        >
          {favicon ? (
            <Image
              width={100}
              height={100}
              alt={`${tool.name} favicon`}
              className={`h-6 w-6 object-contain ${
                shouldInvert ? "invert" : ""
              }`}
              src={favicon}
              onLoad={(e) => checkImageBrightness(e.currentTarget)}
              onError={() => setFaviconError(true)}
            />
          ) : (
            <GlobalIcon className="h-5 w-5 text-foreground-500" />
          )}
        </div>
        <span className="font-medium text-foreground-700 transition-colors group-hover:text-foreground-900">
          {tool.name}
        </span>
      </a>
    </Tooltip>
  );
});

ToolCard.displayName = "ToolCard";

export default ToolCard;
