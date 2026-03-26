import { defineComponent } from "@openuidev/react-lang";
import { parseDiffFromFile } from "@pierre/diffs";
import type { FileDiffMetadata } from "@pierre/diffs/react";
import { FileDiff } from "@pierre/diffs/react";
import React from "react";
import { z } from "zod";

// ---------------------------------------------------------------------------
// Schema
// ---------------------------------------------------------------------------

export const codeDiffSchema = z.object({
  filename: z.string(),
  oldCode: z.string(),
  newCode: z.string(),
  diffStyle: z.enum(["unified", "split"]).optional(),
  title: z.string().optional(),
});

// ---------------------------------------------------------------------------
// View
// ---------------------------------------------------------------------------

export function CodeDiffView(props: z.infer<typeof codeDiffSchema>) {
  const [fileDiff, setFileDiff] = React.useState<FileDiffMetadata | null>(null);

  React.useEffect(() => {
    const diff = parseDiffFromFile(
      { name: props.filename, contents: props.oldCode },
      { name: props.filename, contents: props.newCode },
    );
    setFileDiff(diff);
  }, [props.filename, props.oldCode, props.newCode]);

  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full min-w-fit max-w-2xl">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
      )}
      <div className="rounded-xl overflow-hidden">
        {fileDiff ? (
          <FileDiff
            fileDiff={fileDiff}
            options={{
              diffStyle: props.diffStyle ?? "unified",
              theme: { dark: "github-dark", light: "github-light" },
              themeType: "dark",
              disableLineNumbers: false,
              overflow: "scroll",
            }}
          />
        ) : (
          <div className="bg-zinc-900 p-3 text-xs text-zinc-500">
            Loading diff…
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component definition
// ---------------------------------------------------------------------------

export const codeDiffDef = defineComponent({
  name: "CodeDiff",
  description: "Side-by-side or unified code diff with syntax highlighting.",
  props: codeDiffSchema,
  component: ({ props }) => React.createElement(CodeDiffView, props),
});
