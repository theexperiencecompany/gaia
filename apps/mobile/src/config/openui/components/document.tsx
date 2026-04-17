import { defineComponent } from "@openuidev/react-lang";
import React from "react";
import { View } from "react-native";
import { z } from "zod";
import { MarkdownRenderer } from "@/components/ui/markdown-renderer";
import {
  Card,
  InnerCard,
  ItemTitle,
  MutedText,
  SectionTitle,
} from "./primitives";

export const textDocumentSchema = z.object({
  title: z.string(),
  body: z.string(),
  fields: z
    .array(z.object({ label: z.string(), value: z.string() }))
    .optional(),
});

export function TextDocumentView(props: z.infer<typeof textDocumentSchema>) {
  const { title, body, fields } = props;
  const hasFields = fields !== undefined && fields.length > 0;

  return (
    <Card>
      <SectionTitle>{title}</SectionTitle>

      {hasFields ? (
        <View className="gap-2">
          {fields.map((field) => (
            <InnerCard key={`${field.label}-${field.value}`}>
              <MutedText className="mb-1">{field.label}</MutedText>
              <ItemTitle>{field.value}</ItemTitle>
            </InnerCard>
          ))}
        </View>
      ) : null}

      {hasFields ? (
        <View
          style={{
            height: 1,
            backgroundColor: "#3f3f46",
            marginVertical: 12,
          }}
        />
      ) : null}

      <MarkdownRenderer content={body} />
    </Card>
  );
}

export const textDocumentDef = defineComponent({
  name: "TextDocument",
  description:
    "Editable rich text document card with optional metadata fields. Use for email drafts, document brainstorming, reports, and letters — never when sending a final email directly.",
  props: textDocumentSchema,
  component: ({ props }) => React.createElement(TextDocumentView, props),
});
