import { defineComponent } from "@openuidev/react-lang";
import React from "react";
import { textDocumentSchema } from "../promptSpecs";
import { TextDocumentView } from "./document";

export const textDocumentDef = defineComponent({
  name: "TextDocument",
  description:
    "Editable rich text document card with optional metadata fields. Use for email drafts, document brainstorming, reports, and letters — never when sending a final email directly.",
  props: textDocumentSchema,
  component: ({ props }) => React.createElement(TextDocumentView, props),
});
