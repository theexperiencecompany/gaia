"use client";

import { Chip } from "@heroui/react";
import Image from "next/image";
import { useEffect, useState } from "react";

export interface ImageOption {
  name: string;
  src: string;
}

interface ImageSelectorProps {
  images: ImageOption[];
  defaultIndex?: number;
}

export default function ImageSelector({
  images,
  defaultIndex = 0,
}: ImageSelectorProps) {
  const [selected, setSelected] = useState(images[defaultIndex]);

  // Preload all images
  useEffect(() => {
    images.forEach((img) => {
      const preload = new window.Image();
      preload.src = img.src;
    });
  }, [images]);

  return (
    <div className="flex flex-col justify-center gap-5 items-center">
      <Image
        width={1920}
        height={1080}
        className="w-full rounded-2xl border-2 border-zinc-800 min-w-full bg-zinc-950"
        src={selected.src}
        alt={selected.name}
        priority
      />

      <div className="flex gap-3">
        {images.map((option) => (
          <Chip
            key={option.name}
            radius="sm"
            onClick={() => setSelected(option)}
            color={selected.name === option.name ? "primary" : "default"}
            variant={selected.name === option.name ? "solid" : "light"}
            className="cursor-pointer font-medium"
          >
            {option.name}
          </Chip>
        ))}
      </div>
    </div>
  );
}
