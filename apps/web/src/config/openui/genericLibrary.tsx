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
 * Base: `@openuidev/react-ui`'s `openuiLibrary` — the official Generative UI
 * component set (Stack, Card, Charts, Table, forms, …) — themed to GAIA via
 * `<ThemeProvider darkTheme={gaiaOpenUITheme}>` (see ./theme.ts).
 *
 * Plus the GAIA-only components react-ui has no equivalent for. `ImageGallery`
 * overrides react-ui's variant so uploaded session-file artifacts still resolve
 * via `resolveArtifactSrc`.
 *
 * The backend LLM prompt is generated from this same component set — see
 * `scripts/openui/generate-prompt.ts`.
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
      "MapBlock — geographic map with markers, routes, and arcs.",
      "Timeline — chronological event feed with actor, links, and actions.",
      "TextDocument — editable rich-text card for drafts, reports, and letters.",
    ],
  },
];

export const genericLibrary = createLibrary({
  components: [...reactUiComponents, ...gaiaComponents],
  componentGroups: [...(openuiComponentGroups ?? []), ...gaiaComponentGroups],
  root: "Stack",
});
