"use client";

import { Button, ButtonGroup, Chip, Dropdown, Menu } from "@heroui/react";
import { ArrowRight02Icon } from "@icons";
import Image from "next/image";
import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";
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
import { track } from "@/lib/analytics";
import { getImageDimensions } from "@/lib/imageDimensions";

const DESKTOP_OSES: DesktopOS[] = ["mac", "windows", "linux"];

const APPLE_ICON = getImageDimensions("/images/icons/apple.svg");
const GOOGLE_PLAY_ICON = getImageDimensions("/images/icons/google_play.svg");

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
  /** False for a section that starts below the fold on every viewport. */
  imagePriority?: boolean;
  imageWidth?: number;
  imageHeight?: number;
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
  imagePriority = true,
  imageWidth = 1920,
  imageHeight = 1080,
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
            priority={imagePriority}
            sizes="(max-width: 768px) 100vw, 512px"
            width={imageWidth}
            height={imageHeight}
          />
        </div>

        {/* Content */}
        <div
          className={`flex flex-col items-center gap-6 text-center ${CONTENT_ALIGNMENT_CLASSES[contentAlignment]}`}
        >
          {chip}
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

// One download control for a desktop OS: an arch chooser (x64/ARM) when more
// than one binary is published, a single button when only one is, a loading
// state while resolving, and a releases-page fallback if the lookup fails.
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
  // v2 parity: the primary CTA was the dark default button, which is v3
  // secondary (dark fill). v3 primary is the blue accent fill.
  const buttonVariant = isPrimary ? "secondary" : "tertiary";
  // Mac's apple.svg is dark; invert it on the light "tertiary" buttons.
  const invertIcon = os === "mac" && !isPrimary;
  const iconSize = getImageDimensions(meta.icon);

  const icon = (
    <div className="relative h-4 w-4">
      <Image
        src={meta.icon}
        alt=""
        width={iconSize.width}
        height={iconSize.height}
        sizes="16px"
        className={
          invertIcon
            ? "absolute inset-0 h-full w-full object-contain filter invert"
            : "absolute inset-0 h-full w-full object-contain"
        }
      />
    </div>
  );

  const baseLabel = isPrimary ? `Download for ${meta.name}` : meta.name;

  if (isDesktopReleaseLoading) {
    return (
      <Button variant={buttonVariant} isPending>
        {icon}
        {baseLabel}
      </Button>
    );
  }

  if (available.length === 0) {
    return (
      <Button
        render={(props) => (
          <Link
            {...(props as unknown as ComponentProps<"a">)}
            href={GITHUB_RELEASES_BASE}
            target="_blank"
            rel="noopener noreferrer"
          />
        )}
        variant={buttonVariant}
        onPress={() => {
          track("navigation:cta_clicked", {
            destination: "github_releases",
            os,
          });
        }}
      >
        {icon}
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
      render={(props) => (
        <Link
          {...(props as unknown as ComponentProps<"a">)}
          href={selected.downloadUrl ?? "#"}
          target="_blank"
          rel="noopener noreferrer"
        />
      )}
      variant={buttonVariant}
      onPress={() => {
        track("navigation:cta_clicked", {
          destination: "download",
          os,
        });
      }}
    >
      {icon}
      {label}
    </Button>
  );

  if (available.length === 1) {
    return mainButton;
  }

  return (
    <ButtonGroup>
      {mainButton}
      <Dropdown>
        <Dropdown.Trigger>
          <Button isIconOnly variant={buttonVariant}>
            <ChevronDown width={17} height={17} />
          </Button>
        </Dropdown.Trigger>
        <Dropdown.Popover placement="bottom end">
          <Menu
            disallowEmptySelection
            aria-label={`${meta.name} architecture options`}
            selectedKeys={new Set([effectiveArch])}
            selectionMode="single"
            onSelectionChange={(keys) =>
              setOverrideArch(Array.from(keys)[0] as DesktopArch)
            }
          >
            {available.map((variant) => (
              <Menu.Item
                key={variant.arch}
                id={variant.arch}
                textValue={variant.label}
              >
                <div className="flex flex-col">
                  <span>{variant.label}</span>
                  <span className="text-xs text-zinc-400">
                    {variant.description}
                  </span>
                </div>
              </Menu.Item>
            ))}
          </Menu>
        </Dropdown.Popover>
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
      imagePriority={false}
      title="Download for Desktop"
      chip={
        <Chip variant="tertiary" color="success">
          Beta
        </Chip>
      }
      description="Native apps for macOS, Windows, and Linux."
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
      pngSrc="/images/screenshots/phone_dock.webp"
      imageAlt="GAIA Mobile App"
      imagePosition="right"
      imageClassName="object-cover object-center"
      contentAlignment="left"
      imagePriority={false}
      imageWidth={1024}
      imageHeight={576}
      chip={
        <Chip variant="tertiary" color="warning">
          Waitlist
        </Chip>
      }
      title="Mobile Apps"
      description="GAIA for iOS and Android is currently in development."
      actions={
        <div className="flex flex-col gap-3">
          <Button
            render={(props) => (
              <Link
                {...(props as unknown as ComponentProps<"a">)}
                href={appConfig.site.mobileWaitlist}
                target="_blank"
                rel="noopener noreferrer"
              />
            )}
            onPress={() => {
              track("cta:get_started_clicked", {});
            }}
          >
            Sign up for waitlist <ChevronRight width={17} height={17} />
          </Button>
          <div className="flex flex-wrap gap-2">
            <Button variant="tertiary" isDisabled>
              <div className="relative h-4 w-4">
                <Image
                  src="/images/icons/apple.svg"
                  alt=""
                  width={APPLE_ICON.width}
                  height={APPLE_ICON.height}
                  sizes="16px"
                  className="absolute inset-0 h-full w-full object-contain"
                />
              </div>
              App Store
            </Button>
            <Button variant="tertiary" isDisabled>
              <div className="relative h-4 w-4">
                <Image
                  src="/images/icons/google_play.svg"
                  alt=""
                  width={GOOGLE_PLAY_ICON.width}
                  height={GOOGLE_PLAY_ICON.height}
                  sizes="16px"
                  className="absolute inset-0 h-full w-full object-contain"
                />
              </div>
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
      imagePriority={false}
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
          GAIA is available as a native desktop app in beta for macOS, Windows,
          and Linux, with mobile apps for iOS and Android in development. Choose
          the installer for your platform below: macOS has separate Apple
          Silicon and Intel builds, while Windows and Linux each use a single
          download. The page detects your platform and puts the matching
          download first, so you can start there if you are unsure which build
          to pick. The desktop app is the native option; the web app runs in
          your browser without an install. Use All releases for previous
          versions, and the release notes to see what changed in each update.
          The beta ships frequently, so check those notes after an update.
        </p>
      </section>

      <DesktopSection />
      <MobileSection />
      <WebSection />
    </div>
  );
}
