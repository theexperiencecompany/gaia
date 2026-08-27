"use client";

import { Button, ButtonGroup } from "@heroui/button";
import { Chip } from "@heroui/chip";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import { ArrowRight02Icon } from "@icons";
import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";
import { useState } from "react";
import { ChevronDown, ChevronRight } from "@/components/shared/icons";
import ProgressiveImage from "@/components/ui/ProgressiveImage";
import { appConfig } from "@/config/appConfig";
import GetStartedButton from "@/features/landing/components/shared/GetStartedButton";
import {
  type DesktopArch,
  type DesktopOS,
  GITHUB_RELEASES_BASE,
  usePlatformDetection,
} from "@/hooks/ui/usePlatformDetection";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";

const DESKTOP_OSES: DesktopOS[] = ["mac", "windows", "linux"];

const OS_META: Record<DesktopOS, { name: string; icon: string }> = {
  mac: { name: "macOS", icon: "/images/icons/apple.svg" },
  windows: { name: "Windows", icon: "/images/icons/windows.svg" },
  linux: { name: "Linux", icon: "/images/icons/linux.svg" },
};

// Reusable section layout component
interface DownloadSectionLayoutProps {
  webpSrc: string;
  pngSrc: string;
  imageAlt: string;
  imagePosition?: "left" | "right";
  imageClassName?: string;
  contentAlignment?: "left" | "right" | "center";
  chip?: ReactNode;
  title: string;
  description: string;
  actions: ReactNode;
  extraContent?: ReactNode;
}

const CONTENT_ALIGNMENT_CLASSES: Record<"left" | "right" | "center", string> = {
  left: "md:items-start md:text-left",
  right: "md:items-end md:text-right",
  center: "md:items-center md:text-center",
};

function DownloadSectionLayout({
  webpSrc,
  pngSrc,
  imageAlt,
  imagePosition = "left",
  imageClassName = "object-cover object-bottom",
  contentAlignment = "center",
  chip,
  title,
  description,
  actions,
  extraContent,
}: DownloadSectionLayoutProps) {
  return (
    <section className="relative z-10 w-full max-w-5xl px-4 sm:px-6 py-16">
      <div className="grid grid-cols-1 items-center gap-8 md:grid-cols-2">
        {/* Image */}
        <div
          className={`relative aspect-video w-full overflow-hidden rounded-4xl bg-zinc-900 ${imagePosition === "right" ? "md:order-2" : ""}`}
        >
          <ProgressiveImage
            webpSrc={webpSrc}
            pngSrc={pngSrc}
            alt={imageAlt}
            className={imageClassName}
          />
        </div>

        {/* Content */}
        <div
          className={`flex flex-col items-center gap-6 text-center ${CONTENT_ALIGNMENT_CLASSES[contentAlignment]}`}
        >
          {chip && chip}
          <div className="flex flex-col gap-2">
            <h2 className="text-5xl font-medium text-white font-serif">
              {title}
            </h2>
            <p className="text-sm text-zinc-400">{description}</p>
          </div>

          {actions}

          {extraContent}
        </div>
      </div>
    </section>
  );
}

// One download control for a desktop OS. Renders an arch chooser (x64 / ARM)
// when more than one binary is published, a single button when only one is, a
// loading state while the release resolves, and a releases-page fallback if the
// lookup failed entirely — so a click always does something sensible.
function DesktopDownloadButton({
  os,
  isPrimary = false,
}: {
  os: DesktopOS;
  isPrimary?: boolean;
}) {
  const { desktopDownloads, detectedDesktop, isDesktopReleaseLoading } =
    usePlatformDetection();
  const [overrideArch, setOverrideArch] = useState<DesktopArch | null>(null);

  const meta = OS_META[os];
  const available = desktopDownloads[os].filter((v) => v.downloadUrl);
  const buttonVariant = isPrimary ? undefined : ("flat" as const);
  // Mac's apple.svg is dark; invert it on the light "flat" (secondary) buttons.
  const invertIcon = os === "mac" && !isPrimary;

  const icon = (
    <div className="relative h-4 w-4">
      <Image
        src={meta.icon}
        alt={meta.name}
        fill
        sizes="16px"
        className={
          invertIcon ? "object-contain filter invert" : "object-contain"
        }
      />
    </div>
  );

  const baseLabel = isPrimary ? `Download for ${meta.name}` : meta.name;

  if (isDesktopReleaseLoading) {
    return (
      <Button variant={buttonVariant} isLoading startContent={icon}>
        {baseLabel}
      </Button>
    );
  }

  if (available.length === 0) {
    return (
      <Button
        as={Link}
        href={GITHUB_RELEASES_BASE}
        target="_blank"
        rel="noopener noreferrer"
        variant={buttonVariant}
        startContent={icon}
        onPress={() => {
          trackEvent(ANALYTICS_EVENTS.NAVIGATION_CTA_CLICKED, {
            destination: "github_releases",
            os,
          });
        }}
      >
        {baseLabel}
      </Button>
    );
  }

  const defaultArch =
    detectedDesktop?.os === os &&
    available.some((v) => v.arch === detectedDesktop.arch)
      ? detectedDesktop.arch
      : available[0].arch;
  const effectiveArch =
    overrideArch && available.some((v) => v.arch === overrideArch)
      ? overrideArch
      : defaultArch;
  const selected =
    available.find((v) => v.arch === effectiveArch) ?? available[0];

  // Surface the selected arch only when there's a real choice to make.
  const label =
    available.length > 1 ? `${baseLabel} (${selected.label})` : baseLabel;

  const mainButton = (
    <Button
      as={Link}
      href={selected.downloadUrl ?? "#"}
      target="_blank"
      rel="noopener noreferrer"
      variant={buttonVariant}
      startContent={icon}
      onPress={() => {
        trackEvent(ANALYTICS_EVENTS.NAVIGATION_CTA_CLICKED, {
          destination: "download",
          os,
        });
      }}
    >
      {label}
    </Button>
  );

  if (available.length === 1) {
    return mainButton;
  }

  return (
    <ButtonGroup>
      {mainButton}
      <Dropdown placement="bottom-end">
        <DropdownTrigger>
          <Button isIconOnly variant={buttonVariant}>
            <ChevronDown width={17} height={17} />
          </Button>
        </DropdownTrigger>
        <DropdownMenu
          disallowEmptySelection
          aria-label={`${meta.name} architecture options`}
          selectedKeys={new Set([effectiveArch])}
          selectionMode="single"
          onSelectionChange={(keys) =>
            setOverrideArch(Array.from(keys)[0] as DesktopArch)
          }
        >
          {available.map((variant) => (
            <DropdownItem key={variant.arch} description={variant.description}>
              {variant.label}
            </DropdownItem>
          ))}
        </DropdownMenu>
      </Dropdown>
    </ButtonGroup>
  );
}

function DesktopSection() {
  const { detectedDesktop } = usePlatformDetection();
  const primaryOs: DesktopOS = detectedDesktop?.os ?? "mac";
  const secondaryOses = DESKTOP_OSES.filter((os) => os !== primaryOs);

  return (
    <DownloadSectionLayout
      webpSrc="/images/screenshots/desktop_dock.webp"
      pngSrc="/images/screenshots/desktop_dock.png"
      imageAlt="GAIA Desktop App"
      imagePosition="left"
      contentAlignment="right"
      title="Download for Desktop"
      chip={
        <Chip variant="flat" color="success">
          Beta
        </Chip>
      }
      description="Get the native desktop experience with enhanced performance."
      actions={
        <div className="flex flex-col gap-3 justify-center items-center">
          <DesktopDownloadButton os={primaryOs} isPrimary />
          <div className="flex flex-wrap justify-center gap-2 md:justify-end">
            {secondaryOses.map((os) => (
              <DesktopDownloadButton key={os} os={os} />
            ))}
          </div>
        </div>
      }
      extraContent={
        <div className="flex items-center gap-4 text-sm text-zinc-500">
          <Link
            href={GITHUB_RELEASES_BASE}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 transition hover:text-zinc-300"
          >
            All releases
            <ArrowRight02Icon className="h-4 w-4" />
          </Link>
          <Link
            href="https://docs.heygaia.io/release-notes"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 transition hover:text-zinc-300"
          >
            Release Notes
            <ArrowRight02Icon className="h-4 w-4" />
          </Link>
        </div>
      }
    />
  );
}

function MobileSection() {
  return (
    <DownloadSectionLayout
      webpSrc="/images/screenshots/phone_dock.webp"
      pngSrc="/images/screenshots/phone_dock.png"
      imageAlt="GAIA Mobile App"
      imagePosition="right"
      imageClassName="object-cover object-center"
      contentAlignment="left"
      chip={
        <Chip variant="flat" color="warning">
          Waitlist
        </Chip>
      }
      title="Mobile Apps"
      description="GAIA for iOS and Android is currently in development."
      actions={
        <div className="flex flex-col gap-3">
          <Button
            as={Link}
            href={appConfig.site.mobileWaitlist}
            target="_blank"
            rel="noopener noreferrer"
            onPress={() => {
              trackEvent(ANALYTICS_EVENTS.CTA_GET_STARTED_CLICKED, {
                button_text: "mobile_waitlist",
              });
            }}
          >
            Sign up for waitlist <ChevronRight width={17} height={17} />
          </Button>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="flat"
              isDisabled
              startContent={
                <div className="relative h-4 w-4">
                  <Image
                    src="/images/icons/apple.svg"
                    alt="iOS"
                    fill
                    sizes="16px"
                    className="object-contain"
                  />
                </div>
              }
            >
              App Store
            </Button>
            <Button
              variant="flat"
              isDisabled
              startContent={
                <div className="relative h-4 w-4">
                  <Image
                    src="/images/icons/google_play.svg"
                    alt="Android"
                    fill
                    sizes="16px"
                    className="object-contain"
                  />
                </div>
              }
            >
              Google Play
            </Button>
          </div>
        </div>
      }
      extraContent={
        <div className="flex items-center gap-4 text-sm text-zinc-500">
          <Link
            href="https://docs.heygaia.io/release-notes"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 transition hover:text-zinc-300"
          >
            Release Notes
            <ArrowRight02Icon className="h-4 w-4" />
          </Link>
        </div>
      }
    />
  );
}

function WebSection() {
  return (
    <DownloadSectionLayout
      webpSrc="/images/screenshots/website_tab.webp"
      pngSrc="/images/screenshots/website_tab.png"
      imageAlt="GAIA Web App"
      imagePosition="left"
      imageClassName="object-cover object-top"
      contentAlignment="right"
      title="Get Started on the Web"
      description="No download required. Access GAIA directly from your browser."
      actions={<GetStartedButton />}
      extraContent={
        <div className="flex items-center gap-4 text-sm text-zinc-500">
          <Link
            href="https://docs.heygaia.io/release-notes"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 transition hover:text-zinc-300"
          >
            Release Notes
            <ArrowRight02Icon className="h-4 w-4" />
          </Link>
        </div>
      }
    />
  );
}

export default function DownloadPage() {
  return (
    <div className="relative flex min-h-screen w-full flex-col items-center">
      <section className="relative z-10 flex w-full max-w-5xl flex-col items-center gap-4 px-6 pb-8 pt-24 sm:pt-32">
        <h1 className="text-4xl font-medium text-white sm:text-7xl font-serif mt-8">
          Download GAIA
        </h1>
        <p className="max-w-xl text-center text-lg text-zinc-400">
          Available on all your devices. Choose your platform below.
        </p>
      </section>

      <DesktopSection />
      <MobileSection />
      <WebSection />
    </div>
  );
}
