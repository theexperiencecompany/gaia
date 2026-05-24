import { defineComponent } from "@openuidev/react-lang";
import React from "react";
import { View } from "react-native";
import { z } from "zod";
import { CodeBlock } from "@/features/chat/components/code-block/CodeBlock";
import {
  Card,
  ItemTitle,
  MutedText,
  SectionTitle,
  StatusPill,
} from "./primitives";

export const codeDiffSchema = z.object({
  filename: z.string(),
  oldCode: z.string(),
  newCode: z.string(),
  title: z.string().optional(),
  diffStyle: z.enum(["unified", "split"]).optional(),
  lineDiffType: z.enum(["word", "char", "word-alt", "none"]).optional(),
  diffIndicators: z.enum(["bars", "classic", "none"]).optional(),
  lang: z.string().optional(),
  disableLineNumbers: z.boolean().optional(),
  disableFileHeader: z.boolean().optional(),
  expandUnchanged: z.boolean().optional(),
});

export function CodeDiffView(props: z.infer<typeof codeDiffSchema>) {
  const {
    filename,
    oldCode,
    newCode,
    title,
    lang,
    disableLineNumbers,
    disableFileHeader,
  } = props;
  const language = lang ?? filename.split(".").pop() ?? "text";
  const showLineNumbers = !disableLineNumbers;

  return (
    <Card>
      {title ? <SectionTitle>{title}</SectionTitle> : null}

      {disableFileHeader ? null : (
        <View className="flex-row items-center justify-between gap-2 mb-3">
          <View className="flex-1">
            <ItemTitle numberOfLines={1}>{filename}</ItemTitle>
          </View>
          <StatusPill kind="default">{language.toLowerCase()}</StatusPill>
        </View>
      )}

      <View className="gap-2">
        <View className="rounded-2xl bg-red-500/5 p-3">
          <MutedText className="mb-2">Before</MutedText>
          <CodeBlock
            code={oldCode}
            language={language}
            showLineNumbers={showLineNumbers}
          />
        </View>

        <View className="rounded-2xl bg-emerald-500/5 p-3">
          <MutedText className="mb-2">After</MutedText>
          <CodeBlock
            code={newCode}
            language={language}
            showLineNumbers={showLineNumbers}
          />
        </View>
      </View>
    </Card>
  );
}

export const codeDiffDef = defineComponent({
  name: "CodeDiff",
  description:
    "Syntax-highlighted code diff. diffStyle: 'unified' (default) or 'split' (side-by-side). lineDiffType: 'word' (default), 'char', or 'none'. diffIndicators: 'bars' (default), 'classic', or 'none'. lang overrides auto-detected language. disableLineNumbers, disableFileHeader, expandUnchanged are boolean toggles.",
  props: codeDiffSchema,
  component: ({ props }) => React.createElement(CodeDiffView, props),
});
