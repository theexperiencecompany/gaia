import type { z } from "zod";
import { ToolCard } from "../primitives/ToolCard";
import type { audioPlayerSchema } from "../promptSpecs";

export function AudioPlayerView(props: z.infer<typeof audioPlayerSchema>) {
  return (
    <ToolCard size="compact" title={props.title} subtitle={props.description}>
      <audio src={props.src} controls className="w-full">
        <track kind="captions" />
      </audio>
    </ToolCard>
  );
}
