import { createContext, Fragment, useContext } from "react";
import { type GroundingIndex, resolveText } from "./grounding";

/** The parsed program's statements, so text can fill its {slots} from their data. */
export const GroundingContext = createContext<GroundingIndex>(new Map());

const BOLD = /(\*\*[^*]+\*\*)/g;

interface GroundedTextProps {
  text: string | null | undefined;
}

/** Text whose {slots} code fills from the program's data; an unknown slot stays visible. */
export function GroundedText({ text }: GroundedTextProps) {
  const index = useContext(GroundingContext);
  if (!text) return null;
  return <>{boldSpans(resolveText(text, index).text)}</>;
}

/** **bold** runs as <strong>, keyed by their offset in the text. */
function boldSpans(text: string) {
  let offset = 0;
  return text.split(BOLD).map((part) => {
    const key = offset;
    offset += part.length;
    return part.startsWith("**") && part.endsWith("**") ? (
      <strong key={key} className="font-semibold text-foreground">
        {part.slice(2, -2)}
      </strong>
    ) : (
      <Fragment key={key}>{part}</Fragment>
    );
  });
}
