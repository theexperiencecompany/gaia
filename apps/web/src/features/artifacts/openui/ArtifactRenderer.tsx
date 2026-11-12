"use client";

import { type ParseResult, Renderer } from "@openuidev/react-lang";
import { createTheme, ThemeProvider } from "@openuidev/react-ui/ThemeProvider";
import { useCallback, useState } from "react";
import { OpenUIErrorBoundary } from "@/config/openui/OpenUIErrorBoundary";
import "@/config/openui/openui.css";
import { GroundingContext } from "./GroundedText";
import { buildIndex, type GroundingIndex } from "./grounding";
import { artifactLibrary } from "./library";
import {
  ArtifactAppearanceContext,
  type ArtifactDensity,
  ArtifactDensityContext,
} from "./renderContext";

export type ArtifactAppearance = "dark" | "light";

interface ArtifactRendererProps {
  program: string;
  isStreaming?: boolean;
  /** "light" renders a paper copy (print and PDF) inside the dark app. */
  appearance?: ArtifactAppearance;
  density?: ArtifactDensity;
}

const lightTheme = createTheme({});

/** Render an artifact-OpenUI program; text fills its {slots} from the program's own data. */
export function ArtifactRenderer({
  program,
  isStreaming = false,
  appearance = "dark",
  density = "page",
}: ArtifactRendererProps) {
  const [index, setIndex] = useState<GroundingIndex>(new Map());
  const [parsed, setParsed] = useState(false);
  const onParseResult = useCallback((result: ParseResult | null) => {
    setIndex(buildIndex(result?.root));
    setParsed(Boolean(result?.root) && !result?.meta.incomplete);
  }, []);
  const onError = useCallback((errors: unknown[]) => {
    if (errors.length)
      console.error("[ArtifactRenderer] validation errors:", errors);
  }, []);

  // the PDF export waits for this marker before printing (app/services/render/pdf.py)
  const tree = (
    <div data-artifact-ready={parsed && !isStreaming ? "" : undefined}>
      <OpenUIErrorBoundary code={program}>
        <GroundingContext.Provider value={index}>
          <ArtifactDensityContext.Provider value={density}>
            <ArtifactAppearanceContext.Provider value={appearance}>
              <Renderer
                response={program}
                library={artifactLibrary}
                isStreaming={isStreaming}
                onParseResult={onParseResult}
                onError={onError}
              />
            </ArtifactAppearanceContext.Provider>
          </ArtifactDensityContext.Provider>
        </GroundingContext.Provider>
      </OpenUIErrorBoundary>
    </div>
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
