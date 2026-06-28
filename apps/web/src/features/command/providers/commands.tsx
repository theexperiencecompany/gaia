"use client";

import {
  BookBookmark02Icon,
  BubbleChatAddIcon,
  CircleArrowUp02Icon,
  DiscordIcon,
  KeyboardIcon,
  Layers01Icon,
  Logout02Icon,
  MapsIcon,
  QuillWrite01Icon,
  WhatsappIcon,
} from "@icons";
import type { ReactNode } from "react";
import { Github } from "@/components/shared/icons";
import { prepareNewChat } from "@/features/chat/utils/newChatNavigation";
import { ACTION_ICON, ICON } from "../model/constants";
import type { BuildCtx, CommandGroup, CommandItem } from "../model/types";

const RELEASE_NOTES_URL = "https://docs.heygaia.io/release-notes";
const ROADMAP_URL = "https://gaia.featurebase.app/roadmap";

export interface CommandDeps {
  isSubscribed: boolean;
  openPricing: () => void;
  openShortcuts: () => void;
  logout: () => void;
  links: {
    discord?: string;
    whatsapp?: string;
    docs?: string;
    github?: string;
  };
}

/** A flat command row (Enter runs it; no Tab actions). */
function cmd(
  id: string,
  title: string,
  icon: ReactNode,
  run: () => void,
  opts: {
    subtitle?: string;
    keywords?: string;
    destructive?: boolean;
    tint?: string;
  } = {},
): CommandItem {
  return {
    id: `cmd:${id}`,
    type: "action",
    title,
    subtitle: opts.subtitle,
    icon,
    tint: opts.tint,
    keywords: opts.keywords,
    primary: {
      id: "run",
      label: title,
      icon,
      run,
      destructive: opts.destructive,
    },
    actions: [],
  };
}

/** Static app commands, grouped by section. Returns groups in display order. */
export function buildCommandGroups(
  ctx: BuildCtx,
  deps: CommandDeps,
): CommandGroup[] {
  const { host } = ctx;
  const external = (url?: string) => () => {
    if (url) window.open(url, "_blank", "noopener,noreferrer");
    host.close();
  };
  const fire = (fn: () => void) => () => {
    fn();
    host.close();
  };

  const quickActions: CommandItem[] = [
    cmd(
      "new-chat",
      "New chat",
      <BubbleChatAddIcon {...ICON} />,
      () => {
        prepareNewChat();
        ctx.navigate("/c")();
      },
      { subtitle: "Start a fresh conversation", keywords: "compose message" },
    ),
  ];
  if (!deps.isSubscribed) {
    quickActions.push(
      cmd(
        "upgrade",
        "Upgrade to Pro",
        <CircleArrowUp02Icon {...ICON} color="#00bbff" />,
        fire(deps.openPricing),
        {
          subtitle: "Unlock everything",
          keywords: "pricing plan billing",
          tint: "text-primary",
        },
      ),
    );
  }

  const community: CommandItem[] = [
    cmd(
      "discord",
      "Join Discord",
      <DiscordIcon {...ICON} color="#5865F2" />,
      external(deps.links.discord),
      { keywords: "community chat", tint: "text-[#5865F2]" },
    ),
    cmd(
      "whatsapp",
      "WhatsApp Community",
      <WhatsappIcon {...ICON} color="#25d366" />,
      external(deps.links.whatsapp),
      { keywords: "community", tint: "text-[#25d366]" },
    ),
  ];

  const resources: CommandItem[] = [
    cmd(
      "docs",
      "Documentation",
      <BookBookmark02Icon {...ICON} />,
      external(deps.links.docs),
      { keywords: "help docs guide" },
    ),
    cmd(
      "blog",
      "Blog",
      <QuillWrite01Icon {...ICON} />,
      fire(() => ctx.navigate("/blog")()),
      { keywords: "articles" },
    ),
    cmd("roadmap", "Roadmap", <MapsIcon {...ICON} />, external(ROADMAP_URL), {
      keywords: "plans features",
    }),
    cmd(
      "release-notes",
      "Release notes",
      <Layers01Icon {...ICON} />,
      external(RELEASE_NOTES_URL),
      { keywords: "changelog updates" },
    ),
    cmd(
      "opensource",
      "Open source",
      <Github {...ICON} />,
      external(deps.links.github),
      { keywords: "github code" },
    ),
  ];

  const account: CommandItem[] = [
    cmd(
      "shortcuts",
      "Keyboard shortcuts",
      <KeyboardIcon {...ICON} />,
      fire(deps.openShortcuts),
      { keywords: "keys hotkeys" },
    ),
    cmd("logout", "Sign out", <Logout02Icon {...ACTION_ICON} />, deps.logout, {
      destructive: true,
      keywords: "logout exit",
    }),
  ];

  return [
    {
      id: "actions",
      heading: "Quick actions",
      icon: <BubbleChatAddIcon {...ICON} />,
      accent: "text-emerald-400",
      kind: "actions",
      items: quickActions,
    },
    {
      id: "community",
      heading: "Community",
      icon: <DiscordIcon {...ICON} />,
      accent: "text-indigo-400",
      kind: "actions",
      items: community,
    },
    {
      id: "resources",
      heading: "Resources",
      icon: <BookBookmark02Icon {...ICON} />,
      accent: "text-teal-400",
      kind: "actions",
      items: resources,
    },
    {
      id: "account",
      heading: "Account",
      icon: <KeyboardIcon {...ICON} />,
      accent: "text-zinc-400",
      kind: "actions",
      items: account,
    },
  ];
}
