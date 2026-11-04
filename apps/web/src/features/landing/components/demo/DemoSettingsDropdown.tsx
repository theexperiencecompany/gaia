"use client";

import { Dropdown, Header } from "@heroui/react";
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
} from "@icons";
import type React from "react";
import { NestedMenuTooltip } from "@/features/settings/components/NestedMenuTooltip";
import { useNestedMenu } from "@/features/settings/hooks/useNestedMenu";

const ic = "h-[18px] w-[18px]";

const noopAction = () => {
  /* demo menu items are non-functional on the landing page */
};

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
      action: noopAction,
    },
    {
      key: "changelog",
      label: "Changelog",
      icon: Layers01Icon,
      action: noopAction,
    },
    { key: "blog", label: "Blog", icon: QuillWrite01Icon, action: noopAction },
    { key: "roadmap", label: "Roadmap", icon: MapsIcon, action: noopAction },
  ];

  const supportMenuItems = [
    {
      key: "contact_support",
      label: "Contact Support",
      icon: BubbleChatQuestionIcon,
      action: noopAction,
    },
    {
      key: "feature_request",
      label: "Request a Feature",
      icon: GitPullRequestIcon,
      action: noopAction,
    },
  ];

  const downloadMenuItems = [
    { key: "macos", label: "macOS", action: noopAction },
    { key: "windows", label: "Windows", action: noopAction },
    { key: "linux", label: "Linux", action: noopAction },
  ];

  return (
    <>
      <Dropdown onOpenChange={onOpenChange}>
        <Dropdown.Trigger>{children}</Dropdown.Trigger>
        <Dropdown.Popover
          placement="right"
          offset={21}
          className="dark rounded-2xl bg-secondary-bg text-foreground shadow-xl"
        >
          <Dropdown.Menu aria-label="Settings">
            <Dropdown.Section>
              <Dropdown.Item id="upgrade" textValue="Subscribe to GAIA Pro">
                <CircleArrowUp02Icon className={ic} color="#00bbff" />
                <span className="text-primary font-medium">
                  Subscribe to GAIA Pro
                </span>
              </Dropdown.Item>
            </Dropdown.Section>

            <Dropdown.Section>
              <Header>Settings</Header>
              <Dropdown.Item
                id="profile"
                textValue="Profile Card"
                className="text-zinc-400 transition hover:text-white"
              >
                <SparklesIcon className={ic} />
                Profile Card
              </Dropdown.Item>
              <Dropdown.Item
                id="account"
                textValue="Account"
                className="text-zinc-400 transition hover:text-white"
              >
                <UserCircleIcon className={ic} />
                Account
              </Dropdown.Item>
              <Dropdown.Item
                id="usage"
                textValue="Usage"
                className="text-zinc-400 transition hover:text-white"
              >
                <ChartLineData02Icon className={ic} />
                Usage
              </Dropdown.Item>
              <Dropdown.Item
                id="preferences"
                textValue="Preferences"
                className="text-zinc-400 transition hover:text-white"
              >
                <MessageMultiple02Icon className={ic} />
                Preferences
              </Dropdown.Item>
              <Dropdown.Item
                id="memory"
                textValue="Memories"
                className="text-zinc-400 transition hover:text-white"
              >
                <AiBrain01Icon className={ic} />
                Memories
              </Dropdown.Item>
              <Dropdown.Item
                id="shortcuts"
                textValue="Keyboard Shortcuts"
                className="text-zinc-400 transition hover:text-white"
              >
                <KeyboardIcon className={ic} />
                Keyboard Shortcuts
              </Dropdown.Item>
            </Dropdown.Section>

            <Dropdown.Section>
              <Header>Community</Header>
              <Dropdown.Item
                id="twitter"
                textValue="Follow Us"
                style={{ color: "#1da1f2" }}
                className="transition"
              >
                <TwitterIcon className={ic} />
                Follow Us
              </Dropdown.Item>
              <Dropdown.Item
                id="discord"
                textValue="Join Discord"
                style={{ color: "#5865F2" }}
                className="transition"
              >
                <DiscordIcon className={ic} />
                Join Discord
              </Dropdown.Item>
              <Dropdown.Item
                id="whatsapp"
                textValue="Join WhatsApp"
                style={{ color: "#25d366" }}
                className="transition"
              >
                <WhatsappIcon className={ic} />
                Join WhatsApp
              </Dropdown.Item>
            </Dropdown.Section>

            <Dropdown.Section>
              <Dropdown.Item
                id="download"
                textValue="Download for Desktop"
                className="text-zinc-400 transition hover:text-white"
                onMouseEnter={downloadMenu.handleMouseEnter}
                onMouseLeave={downloadMenu.handleMouseLeave}
              >
                <CloudDownloadIcon className={ic} />
                Download for Desktop
                <ArrowRight01Icon className="ml-auto h-4 w-4 text-zinc-500" />
              </Dropdown.Item>
              <Dropdown.Item
                id="resources"
                textValue="Resources"
                className="text-zinc-400 transition hover:text-white"
                onMouseEnter={resourcesMenu.handleMouseEnter}
                onMouseLeave={resourcesMenu.handleMouseLeave}
              >
                <BookOpen02Icon className={ic} />
                Resources
                <ArrowRight01Icon className="ml-auto h-4 w-4 text-zinc-500" />
              </Dropdown.Item>
              <Dropdown.Item
                id="support"
                textValue="Support"
                className="text-zinc-400 transition hover:text-white"
                onMouseEnter={supportMenu.handleMouseEnter}
                onMouseLeave={supportMenu.handleMouseLeave}
              >
                <CustomerService01Icon className={ic} />
                Support
                <ArrowRight01Icon className="ml-auto h-4 w-4 text-zinc-500" />
              </Dropdown.Item>
              <Dropdown.Item
                id="settings"
                textValue="Settings"
                className="text-zinc-400 transition hover:text-white"
              >
                <Settings01Icon className={ic} />
                Settings
              </Dropdown.Item>
              <Dropdown.Item
                id="logout"
                textValue="Sign Out"
                variant="danger"
                className="text-danger"
              >
                <Logout02Icon className={ic} />
                Sign Out
              </Dropdown.Item>
            </Dropdown.Section>
          </Dropdown.Menu>
        </Dropdown.Popover>
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
