"use client";

import { useEffect, useState } from "react";

import { ScenarioSchema, type Scenario } from "../types/scenario";
import { useScenarioPlayer } from "../hooks/useScenarioPlayer";
import RecordingChatLayout from "./RecordingChatLayout";

interface RecordingPageProps {
  scenarioId: string;
}

type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; scenario: Scenario };

export default function RecordingPage({ scenarioId }: RecordingPageProps) {
  const [pageState, setPageState] = useState<PageState>({ status: "loading" });

  useEffect(() => {
    fetch(`/scenarios/${scenarioId}.json`)
      .then((res) => {
        if (!res.ok)
          throw new Error(
            `Scenario "${scenarioId}" not found (${res.status})`,
          );
        return res.json();
      })
      .then((data) => {
        const result = ScenarioSchema.safeParse(data);
        if (!result.success) {
          throw new Error(
            `Invalid scenario: ${result.error.issues
              .map((i) => `${i.path.join(".")}: ${i.message}`)
              .join(", ")}`,
          );
        }
        setPageState({ status: "ready", scenario: result.data });
      })
      .catch((err: Error) => {
        setPageState({ status: "error", message: err.message });
      });
  }, [scenarioId]);

  if (pageState.status === "loading") {
    return (
      <div className="flex items-center justify-center h-screen bg-background text-muted-foreground text-sm">
        Loading scenario...
      </div>
    );
  }

  if (pageState.status === "error") {
    return (
      <div className="flex items-center justify-center h-screen bg-background p-8">
        <div className="text-sm font-mono max-w-md space-y-3">
          <p className="text-red-400 font-bold text-base">Scenario Error</p>
          <p className="text-muted-foreground">
            Scenario ID: <span className="text-white">{scenarioId}</span>
          </p>
          <p className="text-muted-foreground">
            Expected file:{" "}
            <span className="text-white">
              /public/scenarios/{scenarioId}.json
            </span>
          </p>
          <p className="text-red-400 mt-4">{pageState.message}</p>
        </div>
      </div>
    );
  }

  return <RecordingScenarioRunner scenario={pageState.scenario} />;
}

function RecordingScenarioRunner({ scenario }: { scenario: Scenario }) {
  const { messages, partialMessage, loadingState, phase, play } =
    useScenarioPlayer(scenario, { autoPlay: false });

  useEffect(() => {
    document.title = "recording:idle";
  }, []);

  useEffect(() => {
    if (phase === "playing") {
      document.title = "recording:started";
    } else if (phase === "done") {
      document.title = "recording:done";
    }
  }, [phase]);

  // Auto-play with delay to give Playwright time to start recording
  useEffect(() => {
    const id = setTimeout(() => play(), 800);
    return () => clearTimeout(id);
  }, [play]);

  return (
    <div
      style={{
        width: scenario.viewport?.width ?? 390,
        height: scenario.viewport?.height ?? 844,
        overflow: "hidden",
        position: "relative",
      }}
      data-recording-phase={phase}
    >
      <RecordingChatLayout
        messages={messages}
        partialMessage={partialMessage}
        loadingState={loadingState}
      />
    </div>
  );
}
