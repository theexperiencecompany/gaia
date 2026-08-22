import { defineComponent } from "@openuidev/react-lang";
import React from "react";
import {
  copyableContentSchema,
  fileTreeSchema,
  kbdRowSchema,
} from "../promptSpecs";
import { CopyableContentView } from "./CopyableContentView";
import { FileTreeView } from "./FileTreeView";
import { KbdRowView } from "./KbdRowView";

// ---------------------------------------------------------------------------
// Component definitions
//
// This module is the registration surface consumed by ../genericLibrary; the
// views themselves live in their own files next to this one.
// ---------------------------------------------------------------------------

export const copyableContentDef = defineComponent({
  name: "CopyableContent",
  description:
    "Copyable non-code text content, supports inline chips and long form blocks.",
  props: copyableContentSchema,
  component: ({ props }) => React.createElement(CopyableContentView, props),
});

export const fileTreeDef = defineComponent({
  name: "FileTree",
  description:
    "File/directory tree (variant='file') or generic collapsible tree (variant='generic').",
  props: fileTreeSchema,
  component: ({ props }) => React.createElement(FileTreeView, props),
});

export const kbdRowDef = defineComponent({
  name: "KbdRow",
  description:
    "A single keyboard shortcut row — keys + description. Compose inside a Card for a shortcut table.",
  props: kbdRowSchema,
  component: ({ props }) => React.createElement(KbdRowView, props),
});
