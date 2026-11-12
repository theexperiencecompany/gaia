"use client";

import { Tab, Tabs } from "@heroui/tabs";
import dynamic from "next/dynamic";
import { useState } from "react";
import type { ArtifactAppearance } from "../openui/ArtifactRenderer";
import { ARTIFACT_SAMPLES, type ArtifactSampleName } from "./samples";

const ArtifactRenderer = dynamic(
  () => import("../openui/ArtifactRenderer").then((m) => m.ArtifactRenderer),
  { ssr: false },
);

/** Dev-only: the stored prototype programs through the real artifact renderer. */
export function ArtifactPlayground() {
  const [sample, setSample] = useState<ArtifactSampleName>("launch");
  const [appearance, setAppearance] = useState<ArtifactAppearance>("dark");
  return (
    <div className="min-h-screen">
      <div className="flex flex-wrap gap-3 p-4">
        <Tabs
          aria-label="Sample"
          selectedKey={sample}
          onSelectionChange={(key) => setSample(key as ArtifactSampleName)}
        >
          <Tab key="launch" title="Launch dashboard" />
          <Tab key="report" title="Research report" />
        </Tabs>
        <Tabs
          aria-label="Appearance"
          selectedKey={appearance}
          onSelectionChange={(key) => setAppearance(key as ArtifactAppearance)}
        >
          <Tab key="dark" title="Dark" />
          <Tab key="light" title="Light" />
        </Tabs>
      </div>
      <ArtifactRenderer
        program={ARTIFACT_SAMPLES[sample]}
        appearance={appearance}
      />
    </div>
  );
}
