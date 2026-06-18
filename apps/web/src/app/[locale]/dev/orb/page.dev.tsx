"use client";

import { Button } from "@heroui/button";
import { useState } from "react";
import GaiaOrb, { type GaiaOrbState } from "@/components/ui/orb/GaiaOrb";

const STATES: GaiaOrbState[] = ["idle", "listening", "thinking", "speaking"];

/** Dev playground for the GAIA WebGL orb (dev-only route). */
export default function OrbDevPage() {
  const [state, setState] = useState<GaiaOrbState>("listening");
  const [large, setLarge] = useState(false);

  return (
    <div className="flex h-screen flex-col items-center justify-center gap-10 bg-[#111111]">
      <GaiaOrb state={state} className={large ? "size-[28rem]" : "size-48"} />

      <div className="flex items-center gap-2">
        {STATES.map((s) => (
          <Button
            key={s}
            size="sm"
            radius="full"
            variant={state === s ? "solid" : "flat"}
            color={state === s ? "primary" : "default"}
            onPress={() => setState(s)}
          >
            {s}
          </Button>
        ))}
        <Button
          size="sm"
          radius="full"
          variant="flat"
          onPress={() => setLarge((v) => !v)}
        >
          {large ? "small" : "large"}
        </Button>
      </div>
      <p className="font-mono text-xs text-zinc-500">
        /dev/orb — GaiaOrb WebGL2 shader playground
      </p>
    </div>
  );
}
