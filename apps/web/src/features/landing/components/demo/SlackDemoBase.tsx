import { useInView } from "motion/react";
import * as m from "motion/react-m";
import Image from "next/image";
import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

const ease = [0.22, 1, 0.36, 1] as const;

interface SlackDemoBaseProps {
  channel: string;
  phase1Content: ReactNode;
  phase1Time?: string;
  phase2Time: string;
  phase2Question: string;
  phase3Time: string;
  phase3Response: ReactNode;
}

export function SlackDemoBase({
  channel,
  phase1Content,
  phase1Time = "9:00 AM",
  phase2Time,
  phase2Question,
  phase3Time,
  phase3Response,
}: SlackDemoBaseProps) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.3 });
  const [phase, setPhase] = useState(1);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    if (!inView) return;

    const t2 = setTimeout(() => setPhase(2), 800);
    const t3 = setTimeout(() => setPhase(3), 1800);
    timersRef.current.push(t2, t3);

    const captured = timersRef.current;
    return () => {
      for (const t of captured) clearTimeout(t);
    };
  }, [inView]);

  return (
    <div
      ref={ref}
      className="flex flex-col overflow-hidden rounded-3xl bg-zinc-900 text-left max-h-140"
    >
      <div className="flex shrink-0 items-center gap-1.5 border-b border-zinc-800 px-5 py-3">
        <span className="text-sm font-semibold text-zinc-500">#</span>
        <span className="text-sm font-semibold text-zinc-200">{channel}</span>
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5 no-scrollbar">
        {phase >= 1 && (
          <m.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease }}
            className="flex items-start gap-3"
          >
            <div className="h-9 w-9 shrink-0 overflow-hidden rounded-lg">
              <Image
                src="/images/logos/logo.webp"
                width={36}
                height={36}
                alt="GAIA"
                className="h-full w-full object-cover"
              />
            </div>
            <div className="min-w-0 flex-1">
              <div className="mb-1.5 flex items-baseline gap-2">
                <span className="text-sm font-bold text-zinc-100">GAIA</span>
                <span className="rounded-sm bg-primary/15 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                  App
                </span>
                <span className="text-[11px] text-zinc-600">{phase1Time}</span>
              </div>
              {phase1Content}
            </div>
          </m.div>
        )}

        {phase >= 2 && (
          <m.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease }}
            className="flex items-start gap-3"
          >
            <div className="h-9 w-9 shrink-0 overflow-hidden rounded-lg">
              <Image
                src="/images/avatars/aryan.webp"
                width={36}
                height={36}
                alt="You"
                className="h-full w-full object-cover"
              />
            </div>
            <div>
              <div className="mb-1 flex items-baseline gap-2">
                <span className="text-sm font-bold text-zinc-100">You</span>
                <span className="text-[11px] text-zinc-600">{phase2Time}</span>
              </div>
              <p className="text-sm text-zinc-300">
                <span className="font-semibold text-primary">@GAIA</span>{" "}
                {phase2Question}
              </p>
            </div>
          </m.div>
        )}

        {phase >= 3 && (
          <m.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease }}
            className="flex items-start gap-3"
          >
            <div className="h-9 w-9 shrink-0 overflow-hidden rounded-lg">
              <Image
                src="/images/logos/logo.webp"
                width={36}
                height={36}
                alt="GAIA"
                className="h-full w-full object-cover"
              />
            </div>
            <div>
              <div className="mb-1 flex items-baseline gap-2">
                <span className="text-sm font-bold text-zinc-100">GAIA</span>
                <span className="rounded-sm bg-primary/15 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                  App
                </span>
                <span className="text-[11px] text-zinc-600">{phase3Time}</span>
              </div>
              <p className="text-sm text-zinc-300">{phase3Response}</p>
            </div>
          </m.div>
        )}
      </div>
    </div>
  );
}
