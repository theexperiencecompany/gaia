"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableColumn,
  TableHeader,
  TableRow,
} from "@heroui/table";
import {
  AiBrain01Icon,
  Calendar01Icon,
  ComputerIcon,
  ConnectIcon,
  Home01Icon,
  SquareLock02Icon,
  UserCircle02Icon,
  ZapIcon,
} from "@icons";
import { shuffle } from "lodash";
import Image from "next/image";
import Link from "next/link";
import { useMemo } from "react";
import { RaisedButton } from "@/components/ui/raised-button";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

interface Integration {
  id: string;
  name: string;
}

interface ComparisonFeature {
  key: string;
  icon: React.ReactNode;
  title: string;
  gaia: React.ReactNode;
  chatgpt: React.ReactNode;
  gemini: React.ReactNode;
}

interface ComparisonTableProps {
  integrations: Integration[];
  isLoading: boolean;
  hasMessages: boolean;
}

function AppConnectionsIcons({
  integrations = [],
  isLoading = false,
  hasMessages = false,
}: {
  integrations: Integration[];
  isLoading: boolean;
  hasMessages: boolean;
}) {
  const shuffled = useMemo(
    () => shuffle(integrations.slice(0, 6)),
    [integrations],
  );
  if (isLoading || integrations.length === 0 || hasMessages) return null;
  return (
    <div className="flex items-center gap-1">
      {shuffled.map((integration) => (
        <span
          key={integration.id}
          title={integration.name}
          className="opacity-80"
        >
          {getToolCategoryIcon(integration.id, {
            size: 16,
            width: 16,
            height: 16,
            showBackground: false,
            className: "h-4 w-4 object-contain",
          })}
        </span>
      ))}
    </div>
  );
}

function ColumnLabel({ name, logo }: { name: string; logo: string }) {
  return (
    <div className="flex items-center gap-2.5">
      <Image
        src={logo}
        alt={`${name} logo`}
        width={24}
        height={24}
        className="h-6 w-6 shrink-0 rounded-md object-cover"
      />
      <span>{name}</span>
    </div>
  );
}

export function ComparisonTable({
  integrations = [],
  isLoading = false,
  hasMessages = false,
}: ComparisonTableProps) {
  const features: ComparisonFeature[] = [
    {
      key: "email",
      icon: <AiBrain01Icon className="h-4 w-4 text-zinc-500" />,
      title: "Overwhelmed by email",
      gaia: "Sorts, labels, and drafts replies for you.",
      chatgpt: "Paste the email in here.",
      gemini: "Paste the email in here.",
    },
    {
      key: "reminders",
      icon: <Calendar01Icon className="h-4 w-4 text-zinc-500" />,
      title: "Forgetting things",
      gaia: "Already on your calendar.",
      chatgpt: "Ask it to remind you first.",
      gemini: "You remind it.",
    },
    {
      key: "repeat",
      icon: <ZapIcon className="h-4 w-4 text-zinc-500" />,
      title: "Repeating tasks",
      gaia: "Runs them daily on its own.",
      chatgpt: "Prompt it again each time.",
      gemini: "Prompt it again each time.",
    },
    {
      key: "reports",
      icon: <ComputerIcon className="h-4 w-4 text-zinc-500" />,
      title: "Need fast reports",
      gaia: "Doc is ready. Check your drive.",
      chatgpt: "Explains how. Doesn't ship.",
      gemini: "Tells you. Doesn't do.",
    },
    {
      key: "privacy",
      icon: <SquareLock02Icon className="h-4 w-4 text-zinc-500" />,
      title: "Privacy",
      gaia: "Open source. Self host if you want.",
      chatgpt: "Closed box. Hope they're careful.",
      gemini: "Lives in Google's pipeline.",
    },
    {
      key: "memory",
      icon: <UserCircle02Icon className="h-4 w-4 text-zinc-500" />,
      title: "Memory",
      gaia: "Remembers you across sessions.",
      chatgpt: "Forgets between chats.",
      gemini: "Short memory, per session.",
    },
    {
      key: "work",
      icon: <AiBrain01Icon className="h-4 w-4 text-zinc-500" />,
      title: "Getting work done",
      gaia: "Done. Check in if you want.",
      chatgpt: "Tells you what to do.",
      gemini: "Tells you what to do.",
    },
    {
      key: "customize",
      icon: <Home01Icon className="h-4 w-4 text-zinc-500" />,
      title: "Make it yours",
      gaia: "Tweak anything. Self host. Fork.",
      chatgpt: "What they ship is what you get.",
      gemini: "What they ship is what you get.",
    },
    {
      key: "connections",
      icon: <ConnectIcon className="h-4 w-4 text-zinc-500" />,
      title: "App connections",
      gaia: (
        <AppConnectionsIcons
          integrations={integrations}
          isLoading={isLoading}
          hasMessages={hasMessages}
        />
      ),
      chatgpt: "Can describe your stack. Can't touch it.",
      gemini: "Read only Google access.",
    },
    {
      key: "proactive",
      icon: <ZapIcon className="h-4 w-4 text-zinc-500" />,
      title: "Proactive help",
      gaia: "Acts before you ask.",
      chatgpt: "Waits for a prompt.",
      gemini: "Waits for a prompt.",
    },
  ];

  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-20">
      <div className="mb-12 flex w-full flex-col items-center justify-center gap-3 text-center">
        <h2 className="font-serif text-5xl font-normal tracking-tight text-white sm:text-6xl">
          Your AI should be doing the work, not describing it.
        </h2>
        <span className="max-w-2xl text-center text-xl font-light text-zinc-100">
          Every other assistant stops at "here's how." GAIA keeps going until
          it's shipped.
        </span>
      </div>

      <Table
        aria-label="GAIA vs ChatGPT vs Gemini"
        removeWrapper
        classNames={{
          base: "rounded-[2.5rem] bg-zinc-900 p-3",
          table: "border-separate border-spacing-0",
          th: "bg-zinc-800 text-[13px] font-medium text-zinc-400 py-2.5 px-6 h-auto",
          td: "py-6 px-6 text-[14px] leading-snug align-top",
          tr: "[&>td]:border-b [&>td]:border-zinc-800 last:[&>td]:border-0",
        }}
      >
        <TableHeader>
          <TableColumn
            key="situation"
            // react-aria injects inline style="border-radius:0" so we force via inline style too.
            style={{
              borderTopLeftRadius: "1.75rem",
              borderTopRightRadius: 0,
              borderBottomLeftRadius: 0,
              borderBottomRightRadius: 0,
            }}
          >
            The situation
          </TableColumn>
          <TableColumn key="gaia" style={{ borderRadius: 0 }}>
            <ColumnLabel name="GAIA" logo="/images/logos/logo_bg_grey.png" />
          </TableColumn>
          <TableColumn key="chatgpt" style={{ borderRadius: 0 }}>
            <ColumnLabel name="ChatGPT" logo="/images/logos/chatgpt.png" />
          </TableColumn>
          <TableColumn
            key="gemini"
            style={{
              borderTopRightRadius: "1.75rem",
              borderTopLeftRadius: 0,
              borderBottomLeftRadius: 0,
              borderBottomRightRadius: 0,
            }}
          >
            <ColumnLabel name="Gemini" logo="/images/logos/gemini.png" />
          </TableColumn>
        </TableHeader>
        <TableBody items={features}>
          {(item) => (
            <TableRow key={item.key}>
              <TableCell>
                <div className="flex items-center gap-3 text-[15px] font-medium text-white">
                  {item.icon}
                  <span>{item.title}</span>
                </div>
              </TableCell>
              <TableCell>
                <span className="text-white">{item.gaia}</span>
              </TableCell>
              <TableCell>
                <span className="text-zinc-500">{item.chatgpt}</span>
              </TableCell>
              <TableCell>
                <span className="text-zinc-500">{item.gemini}</span>
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      <div className="mt-10 flex justify-center">
        <Link href="/signup">
          <RaisedButton
            size="lg"
            className="rounded-xl text-lg text-black!"
            color="#00bbff"
          >
            Try GAIA Free
          </RaisedButton>
        </Link>
      </div>
    </div>
  );
}
