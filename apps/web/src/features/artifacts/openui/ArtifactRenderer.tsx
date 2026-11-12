"use client";

import { type ParseResult, Renderer } from "@openuidev/react-lang";
import { createTheme, ThemeProvider } from "@openuidev/react-ui/ThemeProvider";
import { useCallback, useState } from "react";
import { OpenUIErrorBoundary } from "@/config/openui/OpenUIErrorBoundary";
import "@/config/openui/openui.css";
import { GroundingContext } from "./GroundedText";
import { buildIndex, type GroundingIndex } from "./grounding";
import { artifactLibrary } from "./library";

export type ArtifactAppearance = "dark" | "light";

interface ArtifactRendererProps {
  program: string;
  isStreaming?: boolean;
  /** "light" renders a paper copy (print and PDF) inside the dark app. */
  appearance?: ArtifactAppearance;
}

const lightTheme = createTheme({});

/** Render an artifact-OpenUI program; text fills its {slots} from the program's own data. */
export function ArtifactRenderer({
  program,
  isStreaming = false,
  appearance = "dark",
}: ArtifactRendererProps) {
  const [index, setIndex] = useState<GroundingIndex>(new Map());
  const onParseResult = useCallback((result: ParseResult | null) => {
    setIndex(buildIndex(result?.root));
  }, []);
  const onError = useCallback((errors: unknown[]) => {
    if (errors.length)
      console.error("[ArtifactRenderer] validation errors:", errors);
  }, []);

  const tree = (
    <OpenUIErrorBoundary code={program}>
      <GroundingContext.Provider value={index}>
        <Renderer
          response={program}
          library={artifactLibrary}
          isStreaming={isStreaming}
          onParseResult={onParseResult}
          onError={onError}
        />
      </GroundingContext.Provider>
    </OpenUIErrorBoundary>
  );

  if (appearance === "dark") return tree;
  return (
    <div className="light bg-background text-foreground">
      <ThemeProvider mode="light" lightTheme={lightTheme}>
        {tree}
      </ThemeProvider>
    </div>
  );
}
