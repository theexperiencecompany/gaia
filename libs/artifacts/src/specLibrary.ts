/**
 * The artifact library as schemas only (no React views), for Node: the prompt generator and
 * the server-side validator build the parser and the prompt from it. Same names, props and
 * descriptions as library.tsx, because both read specs.ts and react-ui's own definitions.
 */
import {
  createLibrary,
  defineComponent,
  type Library,
} from "@openuidev/react-lang";
import { openuiLibrary } from "@openuidev/react-ui/genui-lib";
import {
  ARTIFACT_COMPONENT_SPECS,
  ARTIFACT_ROOT,
  REACT_UI_ARTIFACT_COMPONENTS,
} from "./specs";

export const artifactSpecLibrary: Library = createLibrary({
  root: ARTIFACT_ROOT,
  components: [
    ...ARTIFACT_COMPONENT_SPECS.map((spec) =>
      defineComponent({
        name: spec.name,
        description: spec.description,
        props: spec.props,
        component: () => null,
      }),
    ),
    ...REACT_UI_ARTIFACT_COMPONENTS.map(
      (name) => openuiLibrary.components[name],
    ),
  ],
});
