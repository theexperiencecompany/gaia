"use client";

import { Button } from "@heroui/button";
import {
  Copy01Icon,
  DownloadCircle01Icon,
  FolderLibraryIcon,
  PackageOpenIcon,
} from "@icons";
import Image from "next/image";
import Link from "next/link";
import { useCallback, useState } from "react";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { toast } from "@/lib/toast";

const menuItemsConfig = [
  {
    id: "copy-logo-svg",
    type: "button" as const,
    label: "Copy Logo as SVG",
    icon: <Copy01Icon className="size-5 shrink-0" />,
    action: "copy-svg",
  },
  {
    id: "download-icon",
    type: "button" as const,
    label: "Download Logo as PNG",
    icon: <DownloadCircle01Icon className="size-5 shrink-0" />,
    action: "download-icon",
  },
  {
    id: "download-wordmark",
    type: "button" as const,
    label: "Download Wordmark as PNG",
    icon: <DownloadCircle01Icon className="size-5 shrink-0" />,
    action: "download-wordmark",
  },
  {
    id: "release-notes",
    type: "link" as const,
    label: "Release Notes",
    href: "https://docs.heygaia.io/release-notes",
    icon: <PackageOpenIcon className="size-5 shrink-0" />,
    target: "_blank",
  },
  {
    id: "brand-assets",
    type: "link" as const,
    label: "Brand Assets",
    href: "/brand",
    icon: <FolderLibraryIcon className="size-5 shrink-0" />,
  },
  {
    id: "experience-company",
    type: "link" as const,
    label: "by The Experience Company",
    href: "https://experience.heygaia.io",
    icon: (
      <Image
        src="/images/logos/experience_logo.svg"
        alt="The Experience Company"
        width={16}
        height={16}
        className="size-5 shrink-0 object-contain"
      />
    ),
    target: "_blank",
  },
];

interface LogoWithContextMenuProps {
  className?: string;
  imageClassName?: string;
  width?: number;
  height?: number;
}

export function LogoWithContextMenu({
  className = "px-2",
  imageClassName = "object-contain",
  width = 100,
  height = 30,
}: LogoWithContextMenuProps) {
  const [isOpen, setIsOpen] = useState(false);

  const downloadImageAsPng = useCallback(
    async (imagePath: string, fileName: string): Promise<void> => {
      try {
        const response = await fetch(imagePath);
        const blob = await response.blob();
        const img = document.createElement("img");
        const objectUrl = URL.createObjectURL(blob);

        await new Promise((resolve, reject) => {
          img.onload = resolve;
          img.onerror = reject;
          img.src = objectUrl;
        });

        const canvas = document.createElement("canvas");
        canvas.width = img.naturalWidth;
        canvas.height = img.naturalHeight;
        const ctx = canvas.getContext("2d");

        if (!ctx) throw new Error("Failed to get canvas context");

        ctx.drawImage(img, 0, 0);
        canvas.toBlob(
          (pngBlob) => {
            if (!pngBlob) {
              toast.error("Failed to convert image");
              return;
            }
            const url = URL.createObjectURL(pngBlob);
            const a = document.createElement("a");
            a.href = url;
            a.download = fileName;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            URL.revokeObjectURL(objectUrl);
            toast.success(`Downloaded ${fileName}`);
          },
          "image/png",
          1.0,
        );
      } catch (error) {
        toast.error("Failed to download image");
        console.error("Failed to download image:", error);
      }
    },
    [],
  );

  const handleDownloadIcon = useCallback(() => {
    downloadImageAsPng("/images/logos/logo.webp", "gaia-icon.png");
  }, [downloadImageAsPng]);

  const handleDownloadWordmark = useCallback(() => {
    downloadImageAsPng(
      "/images/logos/text_w_logo_white.webp",
      "gaia-wordmark.png",
    );
  }, [downloadImageAsPng]);

  const copyLogoAsSvg = useCallback(async (): Promise<void> => {
    try {
      const response = await fetch("/images/logos/logo.svg");
      const svgText = await response.text();
      await navigator.clipboard.writeText(svgText);
      toast.success("Logo SVG copied to clipboard");
    } catch (error) {
      toast.error("Failed to copy SVG");
      console.error("Failed to copy SVG:", error);
    }
  }, []);

  const handleAction = useCallback(
    (action: string) => {
      if (action === "copy-svg") copyLogoAsSvg();
      if (action === "download-icon") handleDownloadIcon();
      if (action === "download-wordmark") handleDownloadWordmark();
    },
    [copyLogoAsSvg, handleDownloadIcon, handleDownloadWordmark],
  );

  return (
    <ContextMenu onOpenChange={setIsOpen} modal={false}>
      <ContextMenuTrigger asChild>
        <Button as={Link} href={"/"} variant="light" className={className}>
          <div className="transition-transform duration-200 hover:scale-[1.02]">
            <Image
              src="/images/logos/text_w_logo_white.webp"
              alt="GAIA Logo"
              width={width}
              height={height}
              priority
              className={imageClassName}
            />
          </div>
        </Button>
      </ContextMenuTrigger>
      {isOpen && (
        <ContextMenuContent className="rounded-2xl bg-primary-bg/70 p-1.5">
          {menuItemsConfig.map((item, index) => (
            <ContextMenuItem
              key={item.id}
              asChild
              className="hover:bg-zinc-700! hover:text-white text-zinc-400"
              style={{
                animationDelay: `${index * 50}ms`,
                animationFillMode: "both",
              }}
            >
              <div
                className="animate-in fade-in slide-in-from-left-2 duration-100"
                onClick={
                  item.type === "button"
                    ? () => handleAction(item.action!)
                    : undefined
                }
              >
                {item.type === "link" ? (
                  <Link
                    href={item.href}
                    className="flex items-center gap-3 w-full cursor-pointer"
                    target={item.target}
                  >
                    {item.icon}
                    <span>{item.label}</span>
                  </Link>
                ) : (
                  <div className="flex items-center gap-3 w-full cursor-pointer">
                    {item.icon}
                    <span>{item.label}</span>
                  </div>
                )}
              </div>
            </ContextMenuItem>
          ))}
        </ContextMenuContent>
      )}
    </ContextMenu>
  );
}
