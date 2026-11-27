"use client";

import { Tabs } from "@heroui/react";
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
          <Tabs.List>
            <Tabs.Tab id="launch">
              Launch dashboard
              <Tabs.Indicator />
            </Tabs.Tab>
            <Tabs.Tab id="report">
              Research report
              <Tabs.Indicator />
            </Tabs.Tab>
          </Tabs.List>
        </Tabs>
        <Tabs
          aria-label="Appearance"
          selectedKey={appearance}
          onSelectionChange={(key) => setAppearance(key as ArtifactAppearance)}
        >
          <Tabs.List>
            <Tabs.Tab id="dark">
              Dark
              <Tabs.Indicator />
            </Tabs.Tab>
            <Tabs.Tab id="light">
              Light
              <Tabs.Indicator />
            </Tabs.Tab>
          </Tabs.List>
        </Tabs>
      </div>
      <ArtifactRenderer
        program={ARTIFACT_SAMPLES[sample]}
        appearance={appearance}
      />
    </div>
  );
}
