"use client";

import { Button } from "@heroui/button";
import { Slider } from "@heroui/slider";
import { useState } from "react";
import LogoTraceLoader from "@/components/common/LogoTraceLoader";

/**
 * Dev playground for LogoTraceLoader (dev-only route). Drives a live instance
 * through loading → resolved with an adjustable draw speed, and shows static
 * variants at different sizes plus the monochrome (currentColor) mode.
 */
export default function LogoTraceDevPage() {
  const [runId, setRunId] = useState(0);
  const [loading, setLoading] = useState(true);
  const [doneCount, setDoneCount] = useState(0);
  const [loopDurationSeconds, setLoopDurationSeconds] = useState(2.4);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-12 bg-[#111111] p-8 text-zinc-100">
      <div className="flex flex-col items-center gap-6">
        <LogoTraceLoader
          key={runId}
          loading={loading}
          size={112}
          strokeWidth={30}
          loopDurationSeconds={loopDurationSeconds}
          onDone={() => setDoneCount((count) => count + 1)}
        />
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            radius="full"
            color="primary"
            isDisabled={!loading}
            onPress={() => setLoading(false)}
          >
            Complete
          </Button>
          <Button
            size="sm"
            radius="full"
            variant="flat"
            onPress={() => {
              setLoading(true);
              setRunId((id) => id + 1);
              setDoneCount(0);
            }}
          >
            Restart
          </Button>
        </div>
        <div className="flex w-64 flex-col gap-1">
          <div className="flex items-center justify-between">
            <span className="text-sm text-zinc-400">Draw speed</span>
            <span className="font-mono text-xs text-zinc-500">
              {loopDurationSeconds.toFixed(1)}s / layer
            </span>
          </div>
          <Slider
            size="sm"
            step={0.1}
            minValue={0.5}
            maxValue={6}
            value={loopDurationSeconds}
            onChange={(value) => setLoopDurationSeconds(value as number)}
          />
        </div>
        <p className="font-mono text-xs text-zinc-500">
          onDone fired: {doneCount}
        </p>
      </div>

      <div className="flex items-end gap-12">
        <div className="flex flex-col items-center gap-3">
          <LogoTraceLoader loading size={64} strokeWidth={20} />
          <span className="text-xs text-zinc-400">64px · looping</span>
        </div>
        <div className="flex flex-col items-center gap-3">
          <LogoTraceLoader loading size={96} strokeWidth={26} />
          <span className="text-xs text-zinc-400">96px · looping</span>
        </div>
        <div className="flex flex-col items-center gap-3">
          <LogoTraceLoader size={128} strokeWidth={32} isComplete />
          <span className="text-xs text-zinc-400">128px · resolved</span>
        </div>
        <div className="flex flex-col items-center gap-3">
          <LogoTraceLoader
            monochrome
            loading
            size={96}
            strokeWidth={26}
            className="text-zinc-100"
          />
          <span className="text-xs text-zinc-400">96px · monochrome</span>
        </div>
      </div>

      <p className="font-mono text-xs text-zinc-500">
        /dev/logo-trace — LogoTraceLoader playground
      </p>
    </div>
  );
}
