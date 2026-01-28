"use client";

import { Button } from "@heroui/button";
import { motion } from "framer-motion";
import Image from "next/image";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { Copy01Icon, DownloadCircle01Icon, FolderLibraryIcon } from "@/icons";

interface LogoWithContextMenuProps {
  className?: string;
  imageClassName?: string;
  width?: number;
  height?: number;
}

type MenuItem =
  | {
      id: string;
      type: "link";
      label: string;
      href: string;
      icon: React.ReactNode;
      target?: string;
    }
  | {
      id: string;
      type: "button";
      label: string;
      icon: React.ReactNode;
      onClick: () => void;
    };

export function LogoWithContextMenu({
  className = "px-2",
  imageClassName = "object-contain",
  width = 100,
  height = 30,
}: LogoWithContextMenuProps) {
  const [isOpen, setIsOpen] = useState(false);

  const downloadImageAsPng = async (
    imagePath: string,
    fileName: string,
  ): Promise<void> => {
    try {
      const response = await fetch(imagePath);
      const blob = await response.blob();

      // Create an image element to get dimensions
      const img = document.createElement("img");
      const objectUrl = URL.createObjectURL(blob);

      await new Promise((resolve, reject) => {
        img.onload = resolve;
        img.onerror = reject;
        img.src = objectUrl;
      });

      // Create canvas and draw image
      const canvas = document.createElement("canvas");
      canvas.width = img.naturalWidth;
      canvas.height = img.naturalHeight;
      const ctx = canvas.getContext("2d");

      if (!ctx) {
        throw new Error("Failed to get canvas context");
      }

      ctx.drawImage(img, 0, 0);

      // Convert to PNG blob
      canvas.toBlob(
        (pngBlob) => {
          if (!pngBlob) {
            toast.error("Failed to convert image");
            return;
          }

          // Download the PNG
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
  };

  const handleDownloadIcon = () => {
    downloadImageAsPng("/images/logos/logo.webp", "gaia-icon.png");
  };

  const handleDownloadWordmark = () => {
    downloadImageAsPng(
      "/images/logos/text_w_logo_white.webp",
      "gaia-wordmark.png",
    );
  };

  const copyLogoAsSvg = async (): Promise<void> => {
    try {
      const response = await fetch("/images/logos/logo.svg");
      const svgText = await response.text();

      await navigator.clipboard.writeText(svgText);
      toast.success("Logo SVG copied to clipboard");
    } catch (error) {
      toast.error("Failed to copy SVG");
      console.error("Failed to copy SVG:", error);
    }
  };

  const menuItems: MenuItem[] = [
    {
      id: "copy-logo-svg",
      type: "button",
      label: "Copy Logo as SVG",
      icon: <Copy01Icon className="size-5 shrink-0" />,
      onClick: copyLogoAsSvg,
    },
    {
      id: "download-icon",
      type: "button",
      label: "Download Logo as PNG",
      icon: <DownloadCircle01Icon className="size-5 shrink-0" />,
      onClick: handleDownloadIcon,
    },
    {
      id: "download-wordmark",
      type: "button",
      label: "Download Wordmark as PNG",
      icon: <DownloadCircle01Icon className="size-5 shrink-0" />,
      onClick: handleDownloadWordmark,
    },
    {
      id: "brand-assets",
      type: "link",
      label: "Brand Assets",
      href: "/brand",
      icon: <FolderLibraryIcon className="size-5 shrink-0" />,
    },
    {
      id: "experience-company",
      type: "link",
      label: "by The Experience Company",
      href: "https://exprience.heygaia.io",
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

  const containerVariants = {
    hidden: {},
    visible: {
      transition: {
        staggerChildren: 0.05,
        delayChildren: 0.05,
      },
    },
  };

  const itemVariants = {
    hidden: { opacity: 0, x: -10 },
    visible: {
      opacity: 1,
      x: 0,
      transition: {
        type: "tween" as const,
        duration: 0.1,
        ease: "easeOut" as const,
      },
    },
  };

  return (
    <ContextMenu onOpenChange={setIsOpen} modal={false}>
      <ContextMenuTrigger asChild>
        <Button as={Link} href={"/"} variant="light" className={className}>
          <motion.div
            whileHover={{
              scale: 1.02,
              transition: { duration: 0.2 },
            }}
          >
            <Image
              src="/images/logos/text_w_logo_white.webp"
              alt="GAIA Logo"
              width={width}
              height={height}
              className={imageClassName}
            />
          </motion.div>
        </Button>
      </ContextMenuTrigger>
      <ContextMenuContent className="rounded-2xl bg-primary-bg/70 p-1.5">
        <motion.div
          initial="hidden"
          animate={isOpen ? "visible" : "hidden"}
          variants={containerVariants}
        >
          {menuItems.map((item) => (
            <ContextMenuItem
              key={item.id}
              asChild
              className="hover:bg-zinc-700! hover:text-white text-zinc-400 "
            >
              <motion.div
                variants={itemVariants}
                onClick={item.type === "button" ? item.onClick : undefined}
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
              </motion.div>
            </ContextMenuItem>
          ))}
        </motion.div>
      </ContextMenuContent>
    </ContextMenu>
  );
}
