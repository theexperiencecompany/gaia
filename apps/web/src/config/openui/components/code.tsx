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
  title: z.string().optional(),
  /** "unified" (default) stacks deletions/additions; "split" shows side-by-side columns */
  diffStyle: z.enum(["unified", "split"]).optional(),
  /** Inline char/word diff highlighting. "word" (default) highlights changed words, "char" highlights individual chars, "none" disables */
  lineDiffType: z.enum(["word", "char", "word-alt", "none"]).optional(),
  /** Style of the +/- change indicators. "bars" (default) colored side bar, "classic" +/- prefix, "none" no indicators */
  diffIndicators: z.enum(["bars", "classic", "none"]).optional(),
  /** Force a specific syntax highlighting language (e.g. "typescript", "python"). Auto-detected from filename by default */
  lang: z.string().optional(),
  /** Hide line numbers. Default false */
  disableLineNumbers: z.boolean().optional(),
  /** Hide the filename header bar. Default false */
  disableFileHeader: z.boolean().optional(),
  /** Expand all unchanged context lines (no collapsed hunks). Default false */
  expandUnchanged: z.boolean().optional(),
});

// ---------------------------------------------------------------------------
// View
// ---------------------------------------------------------------------------

export function CodeDiffView(props: z.infer<typeof codeDiffSchema>) {
  const [fileDiff, setFileDiff] = React.useState<FileDiffMetadata | null>(null);

  React.useEffect(() => {
    const fileOpts = props.lang
      ? { lang: props.lang as Parameters<typeof parseDiffFromFile>[0]["lang"] }
      : {};
    const diff = parseDiffFromFile(
      { name: props.filename, contents: props.oldCode, ...fileOpts },
      { name: props.filename, contents: props.newCode, ...fileOpts },
    );
    setFileDiff(diff);
  }, [props.filename, props.oldCode, props.newCode, props.lang]);

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
              overflow: "scroll",
              lineDiffType: props.lineDiffType ?? "word",
              diffIndicators: props.diffIndicators ?? "bars",
              disableLineNumbers: props.disableLineNumbers ?? false,
              disableFileHeader: props.disableFileHeader ?? false,
              expandUnchanged: props.expandUnchanged ?? false,
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
  description:
    "Syntax-highlighted code diff. diffStyle: 'unified' (default) or 'split' (side-by-side). lineDiffType: 'word' (default), 'char', or 'none'. diffIndicators: 'bars' (default), 'classic', or 'none'. lang overrides auto-detected language. disableLineNumbers, disableFileHeader, expandUnchanged are boolean toggles.",
  props: codeDiffSchema,
  component: ({ props }) => React.createElement(CodeDiffView, props),
});
