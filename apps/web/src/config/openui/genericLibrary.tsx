import { createLibrary } from "@openuidev/react-lang";
import {
  openuiComponentGroups,
  openuiLibrary,
} from "@openuidev/react-ui/genui-lib";
import { briefingDef } from "./components/briefing";
import { chartDefs } from "./components/charts";
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
import "./openui.css";

/**
 * Merged OpenUI library: react-ui's `openuiLibrary` plus GAIA-only components. GAIA defs
 * override react-ui's by name: `ImageGallery` resolves session-file artifacts, and the charts
 * read the app theme (`components/charts.tsx`). The prompt is generated from the same set.
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
  briefingDef,
  ...chartDefs,
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
      "Briefing",
    ],
    notes: [
      "MapBlock: geographic map with markers, routes, and arcs.",
      "Timeline: chronological event feed with actor, links, and actions.",
      "TextDocument: editable rich-text card for drafts, reports, and letters.",
      "Briefing: GAIA's own daily/weekly briefing artifact; never hand-assemble one from other components.",
    ],
  },
];

export const genericLibrary = createLibrary({
  components: [...reactUiComponents, ...gaiaComponents],
  componentGroups: [...(openuiComponentGroups ?? []), ...gaiaComponentGroups],
  root: "Stack",
});
