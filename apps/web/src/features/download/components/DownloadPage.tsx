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
import GetStartedButton from "@/features/landing/components/shared/GetStartedButton";
import {
  GITHUB_RELEASES_BASE,
  platformConfigs,
  usePlatformDetection,
} from "@/hooks/ui/usePlatformDetection";

type MacChipOption = "intel" | "m-series";

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
  const contentAlignmentClasses = {
    left: "md:items-start md:text-left",
    right: "md:items-end md:text-right",
    center: "md:items-center md:text-center",
  };

  return (
    <section className="relative z-10 w-full max-w-5xl py-16">
      <div className="grid grid-cols-1 items-center gap-8 md:grid-cols-2">
        {/* Image */}
        <div
          className={`relative aspect-video w-full overflow-hidden rounded-4xl bg-zinc-900 ${
            imagePosition === "right" ? "md:order-2" : ""
          }`}
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
          className={`flex flex-col items-center gap-6 text-center ${contentAlignmentClasses[contentAlignment]}`}
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

function MacDownloadButton({ isPrimary = false }: { isPrimary?: boolean }) {
  const [selectedOption, setSelectedOption] = useState<Set<MacChipOption>>(
    new Set(["intel"]),
  );

  const labelsMap: Record<MacChipOption, string> = {
    intel: "Download for macOS Intel",
    "m-series": "Download for M-series",
  };

  const downloadUrlMap: Record<MacChipOption, string> = {
    intel: platformConfigs["mac-intel"].downloadUrl || "#",
    "m-series": platformConfigs["mac-arm"].downloadUrl || "#",
  };

  const selectedOptionValue = Array.from(selectedOption)[0] as MacChipOption;

  if (!isPrimary) {
    return (
      <ButtonGroup>
        <Button
          as={Link}
          href={downloadUrlMap[selectedOptionValue]}
          target="_blank"
          rel="noopener noreferrer"
          variant="flat"
          startContent={
            <div className="relative h-4 w-4">
              <Image
                src="/images/icons/apple.svg"
                alt="Apple"
                fill
                className="object-contain"
              />
            </div>
          }
        >
          {selectedOptionValue === "intel" ? "macOS Intel" : "macOS M-series"}
        </Button>
        <Dropdown placement="bottom-end">
          <DropdownTrigger>
            <Button isIconOnly variant="flat">
              <ChevronDown width={17} height={17} />
            </Button>
          </DropdownTrigger>
          <DropdownMenu
            disallowEmptySelection
            aria-label="Mac chip options"
            selectedKeys={selectedOption}
            selectionMode="single"
            onSelectionChange={(keys) =>
              setSelectedOption(keys as Set<MacChipOption>)
            }
          >
            <DropdownItem
              key="intel"
              description="For Macs with Intel processor"
            >
              Intel
            </DropdownItem>
            <DropdownItem
              key="m-series"
              description="For Macs with M1, M2, M3, or M4 chip"
            >
              Apple Silicon (M-series)
            </DropdownItem>
          </DropdownMenu>
        </Dropdown>
      </ButtonGroup>
    );
  }

  return (
    <ButtonGroup>
      <Button
        as={Link}
        href={downloadUrlMap[selectedOptionValue]}
        target="_blank"
        rel="noopener noreferrer"
        startContent={
          <div className="relative h-4 w-4">
            <Image
              src="/images/icons/apple.svg"
              alt="Apple"
              fill
              className="object-contain"
            />
          </div>
        }
      >
        {labelsMap[selectedOptionValue]}
      </Button>
      <Dropdown placement="bottom-end">
        <DropdownTrigger>
          <Button isIconOnly>
            <ChevronDown width={17} height={17} />
          </Button>
        </DropdownTrigger>
        <DropdownMenu
          disallowEmptySelection
          aria-label="Mac chip options"
          selectedKeys={selectedOption}
          selectionMode="single"
          onSelectionChange={(keys) =>
            setSelectedOption(keys as Set<MacChipOption>)
          }
        >
          <DropdownItem key="intel" description="For Macs with Intel processor">
            Intel
          </DropdownItem>
          <DropdownItem
            key="m-series"
            description="For Macs with M1, M2, M3, or M4 chip"
          >
            Apple Silicon (M-series)
          </DropdownItem>
        </DropdownMenu>
      </Dropdown>
    </ButtonGroup>
  );
}

function DesktopSection() {
  const { isMac, isWindows, isLinux } = usePlatformDetection();

  const renderPrimaryButton = () => {
    if (isMac) return <MacDownloadButton isPrimary />;

    if (isWindows) {
      return (
        <Button
          as={Link}
          href={platformConfigs["windows"].downloadUrl || "#"}
          target="_blank"
          rel="noopener noreferrer"
          startContent={
            <div className="relative h-4 w-4">
              <Image
                src="/images/icons/windows.svg"
                alt="Windows"
                fill
                className="object-contain"
              />
            </div>
          }
        >
          Download for Windows
        </Button>
      );
    }

    if (isLinux)
      return (
        <Button
          as={Link}
          href={platformConfigs["linux"].downloadUrl || "#"}
          target="_blank"
          rel="noopener noreferrer"
          startContent={
            <div className="relative h-4 w-4">
              <Image
                src="/images/icons/linux.svg"
                alt="Linux"
                fill
                className="object-contain"
              />
            </div>
          }
        >
          Download for Linux
        </Button>
      );

    return <MacDownloadButton isPrimary />;
  };

  const renderSecondaryButtons = () => {
    const buttons = [];

    if (!isMac) buttons.push(<MacDownloadButton key="mac" />);

    if (!isWindows)
      buttons.push(
        <Button
          key="windows"
          as={Link}
          href={platformConfigs["windows"].downloadUrl || "#"}
          target="_blank"
          rel="noopener noreferrer"
          variant="flat"
          startContent={
            <div className="relative h-4 w-4">
              <Image
                src="/images/icons/windows.svg"
                alt="Windows"
                fill
                className="object-contain"
              />
            </div>
          }
        >
          Windows
        </Button>,
      );

    if (!isLinux)
      buttons.push(
        <Button
          key="linux"
          as={Link}
          href={platformConfigs["linux"].downloadUrl || "#"}
          target="_blank"
          rel="noopener noreferrer"
          variant="flat"
          startContent={
            <div className="relative h-4 w-4">
              <Image
                src="/images/icons/linux.svg"
                alt="Linux"
                fill
                className="object-contain"
              />
            </div>
          }
        >
          Linux
        </Button>,
      );

    return buttons;
  };

  return (
    <DownloadSectionLayout
      webpSrc="/images/screenshots/desktop_dock.webp"
      pngSrc="/images/screenshots/desktop_dock.png"
      imageAlt="GAIA Desktop App"
      imagePosition="left"
      contentAlignment="right"
      title="Download for Desktop"
      description="Get the native desktop experience with enhanced performance."
      actions={
        <div className="flex flex-col gap-3">
          {renderPrimaryButton()}
          <div className="flex flex-wrap justify-center gap-2 md:justify-end">
            {renderSecondaryButtons()}
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
          Coming Soon
        </Chip>
      }
      title="Mobile Apps"
      description="GAIA for iOS and Android is currently in development."
      actions={
        <div className="flex flex-col gap-3">
          <Button
            as={Link}
            href="https://heygaia.app"
            target="_blank"
            rel="noopener noreferrer"
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
    />
  );
}

// Landing page variant - 2 column grid with Desktop and Mobile side by side
export function LandingDownloadSection() {
  const { isMac, isWindows, isLinux } = usePlatformDetection();

  const renderPrimaryButton = () => {
    if (isMac) return <MacDownloadButton isPrimary />;

    if (isWindows) {
      return (
        <Button
          as={Link}
          href={platformConfigs["windows"].downloadUrl || "#"}
          target="_blank"
          rel="noopener noreferrer"
          startContent={
            <div className="relative h-4 w-4">
              <Image
                src="/images/icons/windows.svg"
                alt="Windows"
                fill
                className="object-contain"
              />
            </div>
          }
        >
          Download for Windows
        </Button>
      );
    }

    if (isLinux)
      return (
        <Button
          as={Link}
          href={platformConfigs["linux"].downloadUrl || "#"}
          target="_blank"
          rel="noopener noreferrer"
          startContent={
            <div className="relative h-4 w-4">
              <Image
                src="/images/icons/linux.svg"
                alt="Linux"
                fill
                className="object-contain"
              />
            </div>
          }
        >
          Download for Linux
        </Button>
      );

    return <MacDownloadButton isPrimary />;
  };

  return (
    <section className="relative z-10 mx-auto w-full max-w-6xl px-4 sm:px-6 py-24 sm:py-16">
      <div className="grid grid-cols-1 gap-8 md:grid-cols-2">
        <div className="flex flex-col overflow-hidden rounded-3xl bg-zinc-900/50 backdrop-blur-sm">
          <div className="relative aspect-video w-full overflow-hidden">
            <ProgressiveImage
              webpSrc="/images/screenshots/desktop_dock.webp"
              pngSrc="/images/screenshots/desktop_dock.png"
              alt="GAIA Desktop App"
              className="object-cover object-bottom"
            />
          </div>
          <div className="flex flex-1 flex-col items-center gap-4 p-6 text-center">
            <div>
              <h3 className="mb-1 text-xl font-medium text-white">Desktop</h3>
              <p className="text-sm text-zinc-400">
                Experience GAIA on desktop with enhanced features
              </p>
            </div>
            <div className="flex flex-col gap-2">
              {renderPrimaryButton()}
              <Link
                href={GITHUB_RELEASES_BASE}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-center gap-1 text-sm text-zinc-500 transition hover:text-zinc-300"
              >
                All platforms
                <ArrowRight02Icon className="h-3 w-3" />
              </Link>
            </div>
          </div>
        </div>

        {/* Mobile Card */}
        <div className="flex flex-col overflow-hidden rounded-3xl bg-zinc-900/50 backdrop-blur-sm">
          <div className="relative aspect-video w-full overflow-hidden">
            <ProgressiveImage
              webpSrc="/images/screenshots/phone_dock.webp"
              pngSrc="/images/screenshots/phone_dock.png"
              alt="GAIA Mobile App"
              className="object-cover object-center"
            />
          </div>
          <div className="flex flex-1 flex-col items-center gap-4 p-6 text-center pt-6.5">
            <div className="flex items-center gap-4">
              <Chip variant="flat" color="warning" size="sm">
                Coming Soon
              </Chip>
              <h3 className="text-xl font-medium text-white">Mobile</h3>
            </div>
            <p className="text-sm text-zinc-400">
              iOS and Android apps in development
            </p>
            <div className="flex flex-col gap-2">
              <Button
                as={Link}
                href="https://heygaia.app"
                target="_blank"
                rel="noopener noreferrer"
              >
                Sign up for waitlist <ChevronRight width={17} height={17} />
              </Button>
              <div className="flex gap-2">
                <Button
                  variant="flat"
                  isDisabled
                  size="sm"
                  startContent={
                    <div className="relative h-4 w-4">
                      <Image
                        src="/images/icons/apple.svg"
                        alt="iOS"
                        fill
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
                  size="sm"
                  startContent={
                    <div className="relative h-4 w-4">
                      <Image
                        src="/images/icons/google_play.svg"
                        alt="Android"
                        fill
                        className="object-contain"
                      />
                    </div>
                  }
                >
                  Google Play
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
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
