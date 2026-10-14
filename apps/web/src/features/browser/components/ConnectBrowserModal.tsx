"use client";

import { Button } from "@heroui/button";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { Skeleton } from "@heroui/skeleton";
import { Tab, Tabs } from "@heroui/tabs";
import { type ReactNode, useEffect, useState } from "react";
import CopyButton from "@/components/ui/CopyButton";
import { type ConnectRunner, SAVED_LOGIN_TTL_DAYS } from "../constants";
import { useImportToken } from "../hooks/useImportToken";
import {
  buildConnectCommand,
  connectApiOverride,
  connectRunnersFor,
  formatCountdown,
} from "../utils";

/** Countdown turns amber inside the last minute so the user acts before it dies. */
const EXPIRY_WARNING_SECONDS = 60;

/** Tab labels; curl comes first because it needs nothing installed. */
const RUNNER_TITLES: Record<ConnectRunner, string> = {
  curl: "curl",
  npx: "npx",
  pnpm: "pnpm",
  bun: "bun",
  source: "from source",
};

const FACTS: readonly string[] = [
  "Cookies only, never passwords. Your OS may ask permission once.",
  "It detects your browser and asks which sites to sync.",
  `Encrypted. Expires ${SAVED_LOGIN_TTL_DAYS} days after last use; forget any site here.`,
];

/** A tonal card: zinc-800 on the dialog, per the dark-card contract. */
function Surface({
  label,
  children,
  glass = false,
}: {
  label?: string;
  children: ReactNode;
  glass?: boolean;
}) {
  return (
    <section
      className={`flex flex-col gap-3 rounded-2xl p-4 ${glass ? "bg-zinc-800/40" : "bg-zinc-800"}`}
    >
      {label && <p className="text-xs text-zinc-500">{label}</p>}
      {children}
    </section>
  );
}

/** One line, never wrapped: a long code scrolls sideways rather than breaking. */
function CommandBlock({ command }: { command: string }) {
  return (
    <div className="flex items-center gap-2 rounded-xl bg-zinc-900 py-2 pr-2 pl-3">
      <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap text-primary text-xs">
        {command}
      </code>
      <CopyButton textToCopy={command} />
    </div>
  );
}

function CodeStatus({
  text,
  action,
  onAction,
}: {
  text: string;
  action: string;
  onAction: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl bg-zinc-900 p-3 text-sm text-zinc-400">
      <span>{text}</span>
      <Button size="sm" color="primary" onPress={onAction}>
        {action}
      </Button>
    </div>
  );
}

/** The code panel's one visible state: loading, failed, expired, or the command. */
function CommandPanel({
  command,
  runner,
  secondsLeft,
  isMinting,
  isExpired,
  error,
  onMint,
}: {
  command: string | null;
  runner: ConnectRunner;
  secondsLeft: number;
  isMinting: boolean;
  isExpired: boolean;
  error: Error | null;
  onMint: () => void;
}) {
  if (isMinting || (!command && !error && !isExpired)) {
    return <Skeleton className="h-10 w-full rounded-xl" />;
  }
  if (error) {
    return (
      <CodeStatus
        text="Couldn't get a code."
        action="Try again"
        onAction={onMint}
      />
    );
  }
  if (isExpired || !command) {
    return (
      <CodeStatus text="Code expired." action="New code" onAction={onMint} />
    );
  }
  const warning = secondsLeft <= EXPIRY_WARNING_SECONDS;
  return (
    <>
      <CommandBlock command={command} />
      <p
        className={`text-xs ${warning ? "text-amber-400/80" : "text-zinc-500"}`}
      >
        {runner === "source" ? "Run from the repo root. " : ""}
        Expires in {formatCountdown(secondsLeft)}
      </p>
    </>
  );
}

function FactsList() {
  return (
    <ul className="flex flex-col gap-2">
      {FACTS.map((fact) => (
        <li key={fact} className="flex items-center gap-2.5">
          <span className="size-1.5 shrink-0 rounded-full bg-zinc-600" />
          <span className="text-xs text-zinc-400">{fact}</span>
        </li>
      ))}
    </ul>
  );
}

/**
 * Rendered inside `<ModalContent>`, so it unmounts when the modal closes: a
 * fresh code is minted on every open and nothing needs resetting.
 */
function ConnectBrowserBody({ onClose }: { onClose: () => void }) {
  const { token, secondsLeft, isExpired, isMinting, error, mint } =
    useImportToken();
  const [runner, setRunner] = useState<ConnectRunner>("curl");

  useEffect(() => {
    mint();
  }, [mint]);

  const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  const apiOrigin = apiBaseUrl ? connectApiOverride(apiBaseUrl) : null;
  const runners = connectRunnersFor(apiOrigin);
  const command =
    token && apiBaseUrl
      ? buildConnectCommand({ token, apiOrigin, runner })
      : null;

  return (
    <>
      <ModalHeader>Import browser logins</ModalHeader>
      <ModalBody className="gap-3">
        <Surface label="Run in Terminal">
          <Tabs
            size="sm"
            radius="full"
            aria-label="How to run it"
            selectedKey={runner}
            onSelectionChange={(key) => setRunner(key as ConnectRunner)}
            classNames={{ tabList: "bg-zinc-900" }}
          >
            {runners.map((r) => (
              <Tab key={r} title={RUNNER_TITLES[r]} />
            ))}
          </Tabs>
          <CommandPanel
            command={command}
            runner={runner}
            secondsLeft={secondsLeft}
            isMinting={isMinting}
            isExpired={isExpired}
            error={error}
            onMint={mint}
          />
        </Surface>

        <Surface glass>
          <FactsList />
        </Surface>
      </ModalBody>
      <ModalFooter className="items-center justify-between">
        <p className="text-xs text-zinc-500">
          macOS or Linux, with Chromium browsers and Firefox.
        </p>
        <Button color="primary" size="sm" onPress={onClose}>
          Done
        </Button>
      </ModalFooter>
    </>
  );
}

interface ConnectBrowserModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function ConnectBrowserModal({
  isOpen,
  onClose,
}: ConnectBrowserModalProps) {
  return (
    <Modal isOpen={isOpen} onClose={onClose} size="lg" scrollBehavior="inside">
      <ModalContent>
        <ConnectBrowserBody onClose={onClose} />
      </ModalContent>
    </Modal>
  );
}
