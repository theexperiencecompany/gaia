"use client";

import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownSection,
  DropdownTrigger,
} from "@heroui/dropdown";
import type React from "react";
import { NestedMenuTooltip } from "@/features/settings/components/NestedMenuTooltip";
import { useNestedMenu } from "@/features/settings/hooks/useNestedMenu";
import {
  AiBrain01Icon,
  ArrowRight01Icon,
  BookBookmark02Icon,
  BookOpen02Icon,
  BubbleChatQuestionIcon,
  ChartLineData02Icon,
  CircleArrowUp02Icon,
  CloudDownloadIcon,
  CustomerService01Icon,
  DiscordIcon,
  GitPullRequestIcon,
  KeyboardIcon,
  Layers01Icon,
  Logout02Icon,
  MapsIcon,
  MessageMultiple02Icon,
  QuillWrite01Icon,
  Settings01Icon,
  SparklesIcon,
  TwitterIcon,
  UserCircleIcon,
  WhatsappIcon,
} from "@/icons";

const ic = "h-[18px] w-[18px]";

interface DemoSettingsDropdownProps {
  children: React.ReactNode;
  onOpenChange?: (open: boolean) => void;
}

export default function DemoSettingsDropdown({
  children,
  onOpenChange,
}: DemoSettingsDropdownProps) {
  const resourcesMenu = useNestedMenu();
  const supportMenu = useNestedMenu();
  const downloadMenu = useNestedMenu();

  const resourcesMenuItems = [
    {
      key: "documentation",
      label: "Documentation",
      icon: BookBookmark02Icon,
      action: () => {},
    },
    {
      key: "changelog",
      label: "Changelog",
      icon: Layers01Icon,
      action: () => {},
    },
    { key: "blog", label: "Blog", icon: QuillWrite01Icon, action: () => {} },
    { key: "roadmap", label: "Roadmap", icon: MapsIcon, action: () => {} },
  ];

  const supportMenuItems = [
    {
      key: "contact_support",
      label: "Contact Support",
      icon: BubbleChatQuestionIcon,
      action: () => {},
    },
    {
      key: "feature_request",
      label: "Request a Feature",
      icon: GitPullRequestIcon,
      action: () => {},
    },
  ];

  const downloadMenuItems = [
    { key: "macos", label: "macOS", action: () => {} },
    { key: "windows", label: "Windows", action: () => {} },
    { key: "linux", label: "Linux", action: () => {} },
  ];

  return (
    <>
      <Dropdown
        placement="right-end"
        className="dark rounded-2xl bg-secondary-bg text-foreground shadow-xl"
        offset={21}
        onOpenChange={onOpenChange}
      >
        <DropdownTrigger>{children}</DropdownTrigger>
        <DropdownMenu aria-label="Settings" variant="faded">
          <DropdownSection
            showDivider
            classNames={{ divider: "bg-zinc-800/60" }}
          >
            <DropdownItem
              key="upgrade"
              startContent={
                <CircleArrowUp02Icon className={ic} color="#00bbff" />
              }
              classNames={{ title: "text-primary font-medium" }}
            >
              Upgrade to Pro
            </DropdownItem>
          </DropdownSection>

          <DropdownSection
            title="Settings"
            showDivider
            classNames={{ divider: "bg-zinc-800/60" }}
          >
            <DropdownItem
              key="profile"
              startContent={<SparklesIcon className={ic} />}
              className="text-zinc-400 transition hover:text-white"
            >
              Profile Card
            </DropdownItem>
            <DropdownItem
              key="account"
              startContent={<UserCircleIcon className={ic} />}
              className="text-zinc-400 transition hover:text-white"
            >
              Account
            </DropdownItem>
            <DropdownItem
              key="usage"
              startContent={<ChartLineData02Icon className={ic} />}
              className="text-zinc-400 transition hover:text-white"
            >
              Usage
            </DropdownItem>
            <DropdownItem
              key="preferences"
              startContent={<MessageMultiple02Icon className={ic} />}
              className="text-zinc-400 transition hover:text-white"
            >
              Preferences
            </DropdownItem>
            <DropdownItem
              key="memory"
              startContent={<AiBrain01Icon className={ic} />}
              className="text-zinc-400 transition hover:text-white"
            >
              Memories
            </DropdownItem>
            <DropdownItem
              key="shortcuts"
              startContent={<KeyboardIcon className={ic} />}
              className="text-zinc-400 transition hover:text-white"
            >
              Keyboard Shortcuts
            </DropdownItem>
          </DropdownSection>

          <DropdownSection
            title="Community"
            showDivider
            classNames={{ divider: "bg-zinc-800/60" }}
          >
            <DropdownItem
              key="twitter"
              startContent={<TwitterIcon className={ic} />}
              style={{ color: "#1da1f2" }}
              className="transition"
            >
              Follow Us
            </DropdownItem>
            <DropdownItem
              key="discord"
              startContent={<DiscordIcon className={ic} />}
              style={{ color: "#5865F2" }}
              className="transition"
            >
              Join Discord
            </DropdownItem>
            <DropdownItem
              key="whatsapp"
              startContent={<WhatsappIcon className={ic} />}
              style={{ color: "#25d366" }}
              className="transition"
            >
              Join WhatsApp
            </DropdownItem>
          </DropdownSection>

          <DropdownSection>
            <DropdownItem
              key="download"
              startContent={<CloudDownloadIcon className={ic} />}
              endContent={
                <ArrowRight01Icon className="h-4 w-4 text-zinc-500" />
              }
              className="text-zinc-400 transition hover:text-white"
              onMouseEnter={downloadMenu.handleMouseEnter}
              onMouseLeave={downloadMenu.handleMouseLeave}
            >
              Download for Desktop
            </DropdownItem>
            <DropdownItem
              key="resources"
              startContent={<BookOpen02Icon className={ic} />}
              endContent={
                <ArrowRight01Icon className="h-4 w-4 text-zinc-500" />
              }
              className="text-zinc-400 transition hover:text-white"
              onMouseEnter={resourcesMenu.handleMouseEnter}
              onMouseLeave={resourcesMenu.handleMouseLeave}
            >
              Resources
            </DropdownItem>
            <DropdownItem
              key="support"
              startContent={<CustomerService01Icon className={ic} />}
              endContent={
                <ArrowRight01Icon className="h-4 w-4 text-zinc-500" />
              }
              className="text-zinc-400 transition hover:text-white"
              onMouseEnter={supportMenu.handleMouseEnter}
              onMouseLeave={supportMenu.handleMouseLeave}
            >
              Support
            </DropdownItem>
            <DropdownItem
              key="settings"
              startContent={<Settings01Icon className={ic} />}
              className="text-zinc-400 transition hover:text-white"
            >
              Settings
            </DropdownItem>
            <DropdownItem
              key="logout"
              startContent={<Logout02Icon className={ic} />}
              color="danger"
              className="text-danger"
            >
              Sign Out
            </DropdownItem>
          </DropdownSection>
        </DropdownMenu>
      </Dropdown>

      <NestedMenuTooltip
        isOpen={resourcesMenu.isOpen}
        onOpenChange={resourcesMenu.setIsOpen}
        itemRef={resourcesMenu.itemRef}
        menuItems={resourcesMenuItems}
        iconClasses={ic}
      />

      <NestedMenuTooltip
        isOpen={supportMenu.isOpen}
        onOpenChange={supportMenu.setIsOpen}
        itemRef={supportMenu.itemRef}
        menuItems={supportMenuItems}
        iconClasses={ic}
      />

      <NestedMenuTooltip
        isOpen={downloadMenu.isOpen}
        onOpenChange={downloadMenu.setIsOpen}
        itemRef={downloadMenu.itemRef}
        menuItems={downloadMenuItems}
        iconClasses={ic}
      />
    </>
  );
}
