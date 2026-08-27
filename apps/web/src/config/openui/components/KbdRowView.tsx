import { Kbd } from "@heroui/react";
import type { z } from "zod";
import type { kbdRowSchema } from "../promptSpecs";

export function KbdRowView(props: z.infer<typeof kbdRowSchema>) {
  return (
    <div className="flex items-center justify-between gap-4">
      {props.description && (
        <span className="text-xs text-zinc-400 flex-1">
          {props.description}
        </span>
      )}
      <div className="flex items-center gap-1 shrink-0">
        {props.keys.map((key) => (
          <Kbd key={key}>{key}</Kbd>
        ))}
      </div>
    </div>
  );
}
