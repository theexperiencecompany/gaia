"use client";

import { useEffect, useState } from "react";
import { useUserStore } from "@/stores/userStore";
import { useScenarioPlayer } from "../hooks/useScenarioPlayer";
import { type Scenario, ScenarioSchema } from "../types/scenario";
import RecordingChatLayout from "./RecordingChatLayout";
import RecordingDesktopFrame from "./RecordingDesktopFrame";

const RECORDING_USER = {
  userId: "recording-demo",
  name: "Aryan",
  email: "aryan@heygaia.io",
  profilePicture: "https://github.com/aryanranderiya.png",
} as const;

interface RecordingPageProps {
  scenarioId: string;
  scenarioData?: unknown;
}

function parseScenario(
  data: unknown,
): { scenario: Scenario } | { error: string } {
  const result = ScenarioSchema.safeParse(data);
  if (!result.success) {
    return {
      error: result.error.issues
        .map((i) => `${i.path.join(".")}: ${i.message}`)
        .join(", "),
    };
  }
  return { scenario: result.data };
}

export default function RecordingPage({
  scenarioId,
  scenarioData,
}: RecordingPageProps) {
  const [state, setState] = useState<
    | { status: "loading" }
    | { status: "error"; message: string }
    | { status: "ready"; scenario: Scenario }
  >(() => {
    // If server passed data, parse immediately — no loading flash
    if (scenarioData !== null && scenarioData !== undefined) {
      const parsed = parseScenario(scenarioData);
      if ("error" in parsed)
        return {
          status: "error",
          message: `Invalid scenario: ${parsed.error}`,
        };
      return { status: "ready", scenario: parsed.scenario };
    }
    return { status: "loading" };
  });

  // Client-side fallback fetch only if server didn't pre-load
  useEffect(() => {
    if (state.status !== "loading") return;
    fetch(`/scenarios/${scenarioId}.json`)
      .then((res) => {
        if (!res.ok)
          throw new Error(`Scenario "${scenarioId}" not found (${res.status})`);
        return res.json();
      })
      .then((data) => {
        const parsed = parseScenario(data);
        if ("error" in parsed) {
          setState({
            status: "error",
            message: `Invalid scenario: ${parsed.error}`,
          });
        } else {
          setState({ status: "ready", scenario: parsed.scenario });
        }
      })
      .catch((err: Error) => {
        setState({ status: "error", message: err.message });
      });
  }, [scenarioId, state.status]);

  if (state.status === "loading") {
    // Blank — server should have pre-loaded; this is a fallback during hydration
    return <div className="h-screen" style={{ backgroundColor: "#111111" }} />;
  }

  if (state.status === "error") {
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
          <p className="text-red-400 mt-4">{state.message}</p>
        </div>
      </div>
    );
  }

  return <RecordingScenarioRunner scenario={state.scenario} />;
}

function RecordingScenarioRunner({ scenario }: { scenario: Scenario }) {
  const { messages, partialMessage, loadingState, phase, play } =
    useScenarioPlayer(scenario, { autoPlay: false });

  // Set user profile for avatar rendering in chat bubbles + sidebar
  useEffect(() => {
    useUserStore.getState().setUser(RECORDING_USER);
  }, []);

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

  // Auto-play with short delay to let Playwright start recording
  useEffect(() => {
    const id = setTimeout(() => play(), 100);
    return () => clearTimeout(id);
  }, [play]);

  const logicalWidth = scenario.viewport?.width ?? 390;
  const logicalHeight = scenario.viewport?.height ?? 844;
  const isDesktop = logicalWidth >= 900;

  // The browser viewport is the full physical resolution (e.g. 2880×1800).
  // CSS zoom on <html> makes layout happen at the logical size (e.g. 1440×900).
  // This is necessary because CDP screencast captures at CSS pixel resolution —
  // deviceScaleFactor does NOT increase capture resolution.
  useEffect(() => {
    const zoom = window.innerWidth / logicalWidth;
    if (Math.abs(zoom - 1) < 0.01) return; // no zoom needed
    document.documentElement.style.zoom = String(zoom);
    return () => {
      document.documentElement.style.zoom = "";
    };
  }, [logicalWidth]);

  const chatContent = (
    <RecordingChatLayout
      messages={messages}
      partialMessage={partialMessage}
      loadingState={loadingState}
      isDesktop={isDesktop}
    />
  );

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        overflow: "hidden",
        position: "relative",
      }}
      data-recording-phase={phase}
      data-recording-viewport={isDesktop ? "desktop" : "mobile"}
    >
      {isDesktop ? (
        <RecordingDesktopFrame>{chatContent}</RecordingDesktopFrame>
      ) : (
        chatContent
      )}
    </div>
  );
}
