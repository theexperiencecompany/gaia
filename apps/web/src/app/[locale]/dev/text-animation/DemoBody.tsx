"use client";

import {
  Button,
  Select,
  SelectItem,
  type Selection,
  Slider,
  Switch,
  Textarea,
} from "@heroui/react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ANIMATION_PRESETS,
  type AnimationPreset,
  StreamingText,
} from "./StreamingText";

const TIMING_FUNCTIONS = [
  "ease",
  "ease-out",
  "ease-in-out",
  "linear",
  "cubic-bezier(0.22, 1, 0.36, 1)",
];

const SAMPLE_USER =
  "What's the weather in London today, and should I take an umbrella?";
const SAMPLE_BOT =
  "It's currently 14°C and overcast in London, with light rain expected from around 3pm. " +
  "Yes — I'd take an umbrella; the chance of showers this afternoon is about 70%.";

const firstKey = (keys: Selection, fallback: string): string => {
  const k = keys === "all" ? undefined : Array.from(keys)[0];
  return typeof k === "string" ? k : fallback;
};

/** Progressively reveal `full` word-by-word when streaming; else show it whole. */
function useStreamedText(
  full: string,
  streaming: boolean,
  speedMs: number,
  runId: number,
) {
  const [shown, setShown] = useState(full);
  useEffect(() => {
    if (!streaming) {
      setShown(full);
      return;
    }
    const words = full.split(/(\s+)/);
    let i = 0;
    setShown("");
    const id = setInterval(() => {
      i += 1;
      setShown(words.slice(0, i).join(""));
      if (i >= words.length) clearInterval(id);
    }, speedMs);
    return () => clearInterval(id);
  }, [full, streaming, speedMs, runId]);
  return shown;
}

export default function DemoBody() {
  const [animation, setAnimation] = useState<AnimationPreset>("blurIn");
  const [sep, setSep] = useState<"word" | "char">("word");
  const [durationSec, setDurationSec] = useState(0.5);
  const [timingFunction, setTimingFunction] = useState(TIMING_FUNCTIONS[2]);
  const [streaming, setStreaming] = useState(true);
  const [speedMs, setSpeedMs] = useState(70);
  const [userText, setUserText] = useState(SAMPLE_USER);
  const [botText, setBotText] = useState(SAMPLE_BOT);
  const [runId, setRunId] = useState(0);

  const replay = useCallback(() => setRunId((n) => n + 1), []);
  // Re-run the reveal whenever a knob changes so the effect is immediately visible.
  useEffect(() => {
    replay();
  }, [replay]);

  const userShown = useStreamedText(userText, streaming, speedMs, runId);
  const botShown = useStreamedText(botText, streaming, speedMs, runId);

  const common = useMemo(
    () => ({ sep, animation, durationSec, timingFunction }),
    [sep, animation, durationSec, timingFunction],
  );

  return (
    <div className="mx-auto flex min-h-dvh w-full max-w-5xl flex-col gap-6 p-6">
      <div>
        <h1 className="text-xl font-medium text-white">
          Streaming text animation
        </h1>
        <p className="mt-1 text-sm text-zinc-500">
          Configurable preview of per-word/char streaming animations in the user
          and bot bubbles. Dependency-free (flowtoken-style CSS presets). Toggle
          Stream to simulate tokens arriving; each new segment animates once.
        </p>
      </div>

      {/* Controls */}
      <div className="grid grid-cols-1 gap-4 rounded-2xl bg-zinc-900 p-4 sm:grid-cols-2 lg:grid-cols-3">
        <Select
          label="Animation"
          selectedKeys={[animation]}
          onSelectionChange={(k) =>
            setAnimation(firstKey(k, "blurIn") as AnimationPreset)
          }
        >
          {ANIMATION_PRESETS.map((p) => (
            <SelectItem key={p}>{p}</SelectItem>
          ))}
        </Select>

        <Select
          label="Split by"
          selectedKeys={[sep]}
          onSelectionChange={(k) =>
            setSep(firstKey(k, "word") as "word" | "char")
          }
        >
          <SelectItem key="word">word</SelectItem>
          <SelectItem key="char">char</SelectItem>
        </Select>

        <Select
          label="Timing function"
          selectedKeys={[timingFunction]}
          onSelectionChange={(k) =>
            setTimingFunction(firstKey(k, TIMING_FUNCTIONS[2]))
          }
        >
          {TIMING_FUNCTIONS.map((t) => (
            <SelectItem key={t}>{t}</SelectItem>
          ))}
        </Select>

        <Slider
          label="Duration"
          minValue={0.1}
          maxValue={2}
          step={0.05}
          value={durationSec}
          onChange={(v) => setDurationSec(Array.isArray(v) ? v[0] : v)}
          getValue={(v) => `${Number(v).toFixed(2)}s`}
        />

        <Slider
          label="Stream speed (ms/word)"
          minValue={10}
          maxValue={300}
          step={10}
          value={speedMs}
          onChange={(v) => setSpeedMs(Array.isArray(v) ? v[0] : v)}
          getValue={(v) => `${v}ms`}
          isDisabled={!streaming}
        />

        <div className="flex items-center justify-between gap-3">
          <Switch isSelected={streaming} onValueChange={setStreaming}>
            Stream
          </Switch>
          <Button color="primary" onPress={replay}>
            Replay
          </Button>
        </div>
      </div>

      {/* Editable content */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Textarea
          label="User message"
          value={userText}
          onValueChange={setUserText}
          minRows={2}
        />
        <Textarea
          label="Bot message"
          value={botText}
          onValueChange={setBotText}
          minRows={2}
        />
      </div>

      {/* Previews */}
      <div className="flex flex-col gap-4 rounded-2xl bg-zinc-950 p-6">
        {/* User bubble — right-aligned filled bubble */}
        <div className="flex w-full justify-end">
          <div className="max-w-[80%] rounded-3xl rounded-br-md bg-zinc-800 px-4 py-2.5 text-[15px] text-white">
            <StreamingText key={`u-${runId}`} text={userShown} {...common} />
          </div>
        </div>

        {/* Bot bubble — left-aligned plain prose */}
        <div className="flex w-full justify-start gap-3">
          <div className="mt-1 h-7 w-7 shrink-0 rounded-full bg-zinc-700" />
          <div className="max-w-[80%] text-[15px] leading-relaxed text-zinc-100">
            <StreamingText key={`b-${runId}`} text={botShown} {...common} />
          </div>
        </div>
      </div>
    </div>
  );
}
