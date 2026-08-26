"use client";

import {
  AudioWave01Icon,
  BookBookmark02Icon,
  BubbleChatAddIcon,
  CircleArrowUp02Icon,
  CustomerSupportIcon,
  DiscordIcon,
  Home11Icon,
  KeyboardIcon,
  Layers01Icon,
  Logout02Icon,
  MapsIcon,
  News01Icon,
  PinIcon,
  QuillWrite01Icon,
  TaskAddIcon,
  WhatsappIcon,
} from "@icons";
import type { ReactNode } from "react";
import { Github } from "@/components/shared/icons";
import { prepareNewChat } from "@/features/chat/utils/newChatNavigation";
import { toast } from "@/lib/toast";
import { ACTION_ICON, ICON } from "../model/constants";
import type { BuildCtx, CommandGroup, CommandItem } from "../model/types";

const RELEASE_NOTES_URL = "https://docs.heygaia.io/release-notes";
const ROADMAP_URL = "https://gaia.featurebase.app/roadmap";

export interface CommandDeps {
  isSubscribed: boolean;
  openPricing: () => void;
  openShortcuts: () => void;
  openWhatsNew: () => void;
  enterVoiceMode: () => void;
  createTodo: (title: string) => Promise<void>;
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
  const external = (url: string) => () => {
    window.open(url, "_blank", "noopener,noreferrer");
    host.close();
  };
  // Link-backed commands are dropped when the URL isn't configured — a command
  // that only closes the palette must never reach the list.
  const linkCmd = (
    id: string,
    title: string,
    icon: ReactNode,
    url: string | undefined,
    opts?: Parameters<typeof cmd>[4],
  ): CommandItem | null =>
    url ? cmd(id, title, icon, external(url), opts) : null;
  const isPresent = (item: CommandItem | null): item is CommandItem =>
    item !== null;
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
    {
      id: "cmd:new-todo",
      type: "action",
      title: "New todo",
      icon: <TaskAddIcon {...ICON} />,
      keywords: "create task add reminder",
      primary: {
        id: "run",
        label: "New todo",
        icon: <TaskAddIcon {...ACTION_ICON} />,
        form: {
          placeholder: "e.g. Pay the electricity bill",
          submitLabel: "Create todo",
          submit: async (title) => {
            await deps.createTodo(title);
            toast.success("Todo created");
          },
        },
      },
      actions: [],
    },
    cmd(
      "voice-mode",
      "Start voice mode",
      <AudioWave01Icon {...ICON} />,
      () => {
        ctx.host.close();
        deps.enterVoiceMode();
      },
      { subtitle: "Talk to GAIA", keywords: "speak talk microphone audio" },
    ),
    cmd(
      "whats-new",
      "See what's new",
      <News01Icon {...ICON} />,
      fire(deps.openWhatsNew),
      { keywords: "changelog releases updates features" },
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
    linkCmd(
      "discord",
      "Join Discord",
      <DiscordIcon {...ICON} color="#5865F2" />,
      deps.links.discord,
      { keywords: "community chat", tint: "text-[#5865F2]" },
    ),
    linkCmd(
      "whatsapp",
      "WhatsApp Community",
      <WhatsappIcon {...ICON} color="#25d366" />,
      deps.links.whatsapp,
      { keywords: "community", tint: "text-[#25d366]" },
    ),
  ].filter(isPresent);

  const resources: CommandItem[] = [
    linkCmd(
      "docs",
      "Documentation",
      <BookBookmark02Icon {...ICON} />,
      deps.links.docs,
      { keywords: "help docs guide" },
    ),
    cmd("blog", "Blog", <QuillWrite01Icon {...ICON} />, ctx.navigate("/blog"), {
      keywords: "articles",
    }),
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
    linkCmd(
      "opensource",
      "Open source",
      <Github {...ICON} />,
      deps.links.github,
      { keywords: "github code" },
    ),
  ].filter(isPresent);

  const account: CommandItem[] = [
    cmd(
      "support",
      "Support & feedback",
      <CustomerSupportIcon {...ICON} />,
      ctx.navigate("/support"),
      { keywords: "help contact bug feature request" },
    ),
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

  const navigate: CommandItem[] = [
    cmd("home", "Home", <Home11Icon {...ICON} />, ctx.navigate("/dashboard"), {
      keywords: "dashboard overview start",
    }),
    cmd("pins", "Pins", <PinIcon {...ICON} />, ctx.navigate("/pins"), {
      keywords: "bookmarks saved messages",
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
      id: "navigate",
      heading: "Navigate",
      icon: <Home11Icon {...ICON} />,
      accent: "text-sky-400",
      kind: "actions",
      items: navigate,
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
