import { createLibrary } from "@openuidev/react-lang";
import {
  openuiComponentGroups,
  openuiLibrary,
} from "@openuidev/react-ui/genui-lib";
import {
  audioPlayerDef,
  imageGalleryDef,
  mapBlockDef,
  numberTickerDef,
  videoBlockDef,
} from "./components/content";
import { textDocumentDef } from "./components/document";
import {
  copyableContentDef,
  fileTreeDef,
  kbdRowDef,
} from "./components/layout";
import { avatarDef, progressDef } from "./components/primitives";
import { timelineDef } from "./components/timeline";

/**
 * Merged OpenUI component library.
 *
 * Base: `@openuidev/react-ui`'s `openuiLibrary` (Stack, Card, Charts, Table,
 * forms, …), themed via `<ThemeProvider darkTheme={gaiaOpenUITheme}>`. Plus
 * GAIA-only components react-ui lacks; `ImageGallery` overrides react-ui's
 * variant to resolve uploaded session-file artifacts via `resolveArtifactSrc`.
 * The prompt is generated from this same set (`scripts/openui/generate-prompt.ts`).
 */
const gaiaComponents = [
  mapBlockDef,
  timelineDef,
  fileTreeDef,
  textDocumentDef,
  numberTickerDef,
  audioPlayerDef,
  videoBlockDef,
  progressDef,
  avatarDef,
  copyableContentDef,
  kbdRowDef,
  imageGalleryDef,
];

const gaiaComponentNames = new Set(gaiaComponents.map((c) => c.name));

// react-ui components, minus anything GAIA overrides by name (ImageGallery).
const reactUiComponents = Object.values(openuiLibrary.components).filter(
  (c) => !gaiaComponentNames.has(c.name),
);

const gaiaComponentGroups = [
  {
    name: "GAIA",
    components: [
      "MapBlock",
      "Timeline",
      "FileTree",
      "TextDocument",
      "NumberTicker",
      "AudioPlayer",
      "VideoBlock",
      "Progress",
      "Avatar",
      "CopyableContent",
      "KbdRow",
    ],
    notes: [
      "MapBlock: geographic map with markers, routes, and arcs.",
      "Timeline: chronological event feed with actor, links, and actions.",
      "TextDocument: editable rich-text card for drafts, reports, and letters.",
    ],
  },
];

export const genericLibrary = createLibrary({
  components: [...reactUiComponents, ...gaiaComponents],
  componentGroups: [...(openuiComponentGroups ?? []), ...gaiaComponentGroups],
  root: "Stack",
});
