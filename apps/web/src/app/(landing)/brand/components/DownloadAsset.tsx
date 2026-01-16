"use client";

import { Button } from "@heroui/button";
import Image from "next/image";
import { useState } from "react";
import { Download01Icon } from "@/components";

interface DownloadOption {
  format: string;
  path: string;
  variant?: string;
}

interface DownloadAssetProps {
  name: string;
  imagePath: string;
  downloadOptions: DownloadOption[];
  imageAlt: string;
  backgroundColor?: "light" | "dark";
}

export function DownloadAsset({
  name,
  imagePath,
  downloadOptions,
  imageAlt,
  backgroundColor = "light",
}: DownloadAssetProps) {
  const [isHovered, setIsHovered] = useState(false);

  const handleDownload = (path: string, format: string) => {
    const link = document.createElement("a");
    link.href = path;
    link.download = path.split("/").pop() || `download${format}`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const bgClass =
    backgroundColor === "dark"
      ? "bg-surface-950 outline-1 outline-surface-700"
      : "bg-surface-50 outline-1 outline-surface-300";

  return (
    <div
      className="group relative"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div
        className={`relative aspect-[4/3] overflow-hidden rounded-3xl ${bgClass}`}
      >
        <div className="flex h-full items-center justify-center p-12">
          <Image
            src={imagePath}
            alt={imageAlt}
            width={800}
            height={600}
            className="h-auto w-full object-contain p-10"
            loading="lazy"
          />
        </div>

        {/* Download Buttons - Bottom Right on Hover */}
        <div
          className={`absolute bottom-4 right-4 flex gap-2 transition-opacity duration-300 ${
            isHovered ? "opacity-100" : "opacity-0"
          }`}
        >
          {downloadOptions.map((option) => (
            <Button
              key={`${option.format}-${option.variant || "default"}`}
              size="sm"
              onPress={() => handleDownload(option.path, option.format)}
              startContent={<Download01Icon width={15} height={15} />}
            >
              {option.variant
                ? `${option.format} (${option.variant})`
                : option.format}
            </Button>
          ))}
        </div>
      </div>

      {/* Asset Name */}
      <div className="mt-4 text-center">
        <h3 className="text-sm font-semibold">{name}</h3>
      </div>
    </div>
  );
}
