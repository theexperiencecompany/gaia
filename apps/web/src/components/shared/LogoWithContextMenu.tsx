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
      let objectUrl: string | null = null;
      let pngObjectUrl: string | null = null;
      try {
        const response = await fetch(imagePath);
        if (!response.ok) {
          throw new Error(
            `Failed to fetch image (${response.status} ${response.statusText})`,
          );
        }

        const blob = await response.blob();
        const img = document.createElement("img");
        const newObjectUrl = URL.createObjectURL(blob);
        objectUrl = newObjectUrl;

        await new Promise((resolve, reject) => {
          img.onload = resolve;
          img.onerror = reject;
          img.src = newObjectUrl;
        });

        const canvas = document.createElement("canvas");
        canvas.width = img.naturalWidth;
        canvas.height = img.naturalHeight;
        const ctx = canvas.getContext("2d");

        if (!ctx) throw new Error("Failed to get canvas context");

        ctx.drawImage(img, 0, 0);
        const pngBlob = await new Promise<Blob>((resolve, reject) => {
          canvas.toBlob(
            (blobResult) => {
              if (!blobResult) {
                reject(new Error("Failed to convert image"));
                return;
              }
              resolve(blobResult);
            },
            "image/png",
            1.0,
          );
        });

        pngObjectUrl = URL.createObjectURL(pngBlob);
        const a = document.createElement("a");
        a.href = pngObjectUrl;
        a.download = fileName;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        toast.success(`Downloaded ${fileName}`);
      } catch (error) {
        toast.error("Failed to download image");
        console.error("Failed to download image:", error);
      } finally {
        if (pngObjectUrl) URL.revokeObjectURL(pngObjectUrl);
        if (objectUrl) URL.revokeObjectURL(objectUrl);
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
      if (!response.ok) {
        throw new Error(
          `Failed to fetch SVG (${response.status} ${response.statusText})`,
        );
      }
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
          {menuItemsConfig.map((item, index) => {
            const className =
              "hover:bg-zinc-700! hover:text-white text-zinc-400 animate-in fade-in slide-in-from-left-2 duration-100";
            const style = {
              animationDelay: `${index * 50}ms`,
              animationFillMode: "both",
            } as const;

            if (item.type === "link") {
              return (
                <ContextMenuItem
                  key={item.id}
                  asChild
                  className={className}
                  style={style}
                >
                  <Link
                    href={item.href}
                    className="flex w-full items-center gap-3 cursor-pointer"
                    target={item.target}
                  >
                    {item.icon}
                    <span>{item.label}</span>
                  </Link>
                </ContextMenuItem>
              );
            }

            return (
              <ContextMenuItem
                key={item.id}
                className={className}
                style={style}
                onSelect={() => handleAction(item.action)}
              >
                <div className="flex w-full items-center gap-3 cursor-pointer">
                  {item.icon}
                  <span>{item.label}</span>
                </div>
              </ContextMenuItem>
            );
          })}
        </ContextMenuContent>
      )}
    </ContextMenu>
  );
}
