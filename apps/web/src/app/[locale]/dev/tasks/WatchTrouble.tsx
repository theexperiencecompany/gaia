"use client";

import { Spinner } from "@heroui/react";
import { ViewOffIcon } from "@icons";
import { addHours, format, parseISO } from "date-fns";
import { useEffect, useRef, useState } from "react";

import { GaiaButton } from "@/components/shared/GaiaButton";
import { AskShell } from "./AskShell";
import { APP_NAMES } from "./demoTriggers";
import { CHECK_MS } from "./demoWatches";
import type { Task } from "./taskModel";
import { ago, BLIND, BLIND_PAUSE_HOURS } from "./watchModel";

/**
 * A watch that can't see what it watches: why, since when, and the one fix,
 * in the same place a question or an approval would be. Never silence.
 */
export default function WatchTrouble({
  task,
  update,
  onChangeWatch,
}: {
  task: Task;
  update: (patch: Partial<Task>) => void;
  /** Opens the When editor on the watch, to say what to watch instead. */
  onChangeWatch: () => void;
}) {
  const [isTrying, setIsTrying] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const watch = task.when.watch;
  if (!watch?.blind || task.state === "done") return null;
  // Stopped by you: the stopped banner says so, and nothing is asked.
  if (task.state === "paused" && !task.pauseReason) return null;

  const { source, blind, reading } = watch;
  const where = source.app
    ? (APP_NAMES[source.app] ?? source.app)
    : source.site;
  const { line, fix } = BLIND[blind.reason];
  const isPaused = task.state === "paused";
  const pausesOn = format(
    addHours(parseISO(blind.since), BLIND_PAUSE_HOURS),
    "EEE, MMM d",
  );

  // Seeing it again clears the reason and starts the watch where it left off.
  const seen = () =>
    update({
      state: "waiting",
      pauseReason: undefined,
      disconnected: undefined,
      when: {
        ...task.when,
        watch: {
          ...watch,
          blind: undefined,
          reading: reading && { ...reading, at: new Date().toISOString() },
        },
      },
    });

  const tryAgain = () => {
    setIsTrying(true);
    timer.current = setTimeout(() => {
      setIsTrying(false);
      seen();
    }, CHECK_MS);
  };

  return (
    <AskShell
      label={isPaused ? "Paused, can't see it" : "Can't see it"}
      Icon={ViewOffIcon}
    >
      <p className="text-sm leading-6 text-zinc-100">
        {line(where ?? "the site")}{" "}
        {isPaused
          ? `GAIA paused it after ${BLIND_PAUSE_HOURS / 24} days.`
          : `If it still can't by ${pausesOn}, GAIA pauses it.`}
      </p>
      {reading && (
        <p className="text-xs leading-5 text-zinc-500">
          Last seen {reading.value}, {ago(reading.at)}.
        </p>
      )}
      <div className="flex gap-2">
        {fix === "connect" && (
          <GaiaButton
            size="sm"
            variant="primary"
            className="font-medium"
            onPress={seen}
          >
            Reconnect {where}
          </GaiaButton>
        )}
        {fix === "retry" && (
          <GaiaButton
            size="sm"
            variant="primary"
            className="font-medium"
            isPending={isTrying}
            onPress={tryAgain}
          >
            {isTrying && <Spinner size="sm" color="current" />}
            Try again
          </GaiaButton>
        )}
        {fix === "change" && (
          <GaiaButton
            size="sm"
            variant="primary"
            className="font-medium"
            onPress={onChangeWatch}
          >
            Change what it watches
          </GaiaButton>
        )}
        <GaiaButton
          size="sm"
          variant="default-soft"
          onPress={() => update({ state: "paused", pauseReason: undefined })}
        >
          Stop
        </GaiaButton>
      </div>
    </AskShell>
  );
}
