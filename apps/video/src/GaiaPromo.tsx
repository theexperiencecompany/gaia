import React from "react";
import { TransitionSeries, linearTiming, springTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { slide } from "@remotion/transitions/slide";
import { wipe } from "@remotion/transitions/wipe";
import { TRANSITIONS, SPRINGS } from "./constants";

// Act 1 & 2
import { S01_OpeningStatement } from "./scenes/S01_OpeningStatement";
import { S02_ToolChaos } from "./scenes/S02_ToolChaos";
import { S03_BetterWay } from "./scenes/S03_BetterWay";
import { S05_MeetGaia } from "./scenes/S05_MeetGaia";

// Act 3: Workflow Creation via Chat (replaces modal scenes S06–S15)
import { S06_UserChat } from "./scenes/S06_UserChat";
import { S07_ChatToolCalls } from "./scenes/S07_ChatToolCalls";
import { S08_ChatResponse } from "./scenes/S08_ChatResponse";
import { S09_ChatWorkflowCreated } from "./scenes/S09_ChatWorkflowCreated";

// Act 4: Execution
import { S16_ModalToCard } from "./scenes/S16_ModalToCard";
import { S17_RunningToolStack } from "./scenes/S17_RunningToolStack";
import { S19_BotMessageStream } from "./scenes/S19_BotMessageStream";
import { S21_Completed } from "./scenes/S21_Completed";

// Act 5: Multi-Platform (removed S22–S24 unchanged)
import { S22_MacOSNotifications } from "./scenes/S22_MacOSNotifications";
import { S23_PlatformIcons } from "./scenes/S23_PlatformIcons";
import { S24_NotificationPreview } from "./scenes/S24_NotificationPreview";

// Act 6: Ecosystem + Integrations
import { S26_IntegrationBuilder } from "./scenes/S26_IntegrationBuilder";
import { S26c_IntegrationPage } from "./scenes/S26c_IntegrationPage";
import { S26d_IntegrationTagline } from "./scenes/S26d_IntegrationTagline";
import { S27_CommunityCards } from "./scenes/S27_CommunityCards";

// Act 7 & 8: Platform + Close
import { S28_DashboardReveal } from "./scenes/S28_DashboardReveal";
import { S29_OneDashboard } from "./scenes/S29_OneDashboard";
import { S31_NotJustAssistant } from "./scenes/S31_NotJustAssistant";
import { S32_ProductivityOS } from "./scenes/S32_ProductivityOS";
import { S34_SearchBarCTA } from "./scenes/S34_SearchBarCTA";

const T = TRANSITIONS;
const S = SPRINGS;

export const GaiaPromo: React.FC = () => {
  return (
    <TransitionSeries>
      {/* === ACT 1: THE HOOK === */}
      {/* S01 → S02: Hard smash cut into chaos */}
      <TransitionSeries.Sequence durationInFrames={55}>
        <S01_OpeningStatement />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={linearTiming({ durationInFrames: 4 })}
      />

      {/* S02 → S03: Tool chaos collapses into "Better Way" — slow spring fade */}
      <TransitionSeries.Sequence durationInFrames={100}>
        <S02_ToolChaos />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: S.natural, durationInFrames: 20 })}
      />

      {/* S03 → S05: Calm beat to logo reveal — clean snap dissolve */}
      <TransitionSeries.Sequence durationInFrames={102}>
        <S03_BetterWay />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: 20 })}
      />

      {/* === ACT 2: MEET GAIA === */}
      {/* S05 → S06: Logo zooms into chat — slide from bottom */}
      <TransitionSeries.Sequence durationInFrames={110}>
        <S05_MeetGaia />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={slide({ direction: "from-bottom" })}
        timing={springTiming({ config: S.natural, durationInFrames: 20 })}
      />

      {/* === ACT 3: WORKFLOW CREATION VIA CHAT === */}
      {/* User sends a long multi-tool request */}
      {/* DURATION TRIMMED: 240 → 120 */}
      <TransitionSeries.Sequence durationInFrames={120}>
        <S06_UserChat />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={slide({ direction: "from-right" })}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.fast })}
      />

      {/* GAIA runs tool calls */}
      <TransitionSeries.Sequence durationInFrames={150}>
        <S07_ChatToolCalls />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={slide({ direction: "from-bottom" })}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      {/* GAIA streams response + proposes workflow draft */}
      {/* DURATION TRIMMED: 210 → 180 */}
      <TransitionSeries.Sequence durationInFrames={180}>
        <S08_ChatResponse />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.fast })}
      />

      {/* User confirms — workflow created */}
      <TransitionSeries.Sequence durationInFrames={85}>
        <S09_ChatWorkflowCreated />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={slide({ direction: "from-bottom" })}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.fast })}
      />

      {/* === ACT 4: EXECUTION === */}
      <TransitionSeries.Sequence durationInFrames={102}>
        <S16_ModalToCard />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={slide({ direction: "from-right" })}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      <TransitionSeries.Sequence durationInFrames={150}>
        <S17_RunningToolStack />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.fast })}
      />

      {/* DURATION TRIMMED: 200 → 160 */}
      <TransitionSeries.Sequence durationInFrames={160}>
        <S19_BotMessageStream />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={wipe({ direction: "from-left" })}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      <TransitionSeries.Sequence durationInFrames={120}>
        <S21_Completed />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={wipe({ direction: "from-right" })}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      {/* === ACT 5: MULTI-PLATFORM === */}
      <TransitionSeries.Sequence durationInFrames={100}>
        <S23_PlatformIcons />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={slide({ direction: "from-top" })}
        timing={springTiming({ config: S.natural, durationInFrames: T.normal })}
      />

      <TransitionSeries.Sequence durationInFrames={132}>
        <S22_MacOSNotifications />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.fast })}
      />

      <TransitionSeries.Sequence durationInFrames={102}>
        <S24_NotificationPreview />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={wipe({ direction: "from-left" })}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      {/* === ACT 6: ECOSYSTEM + INTEGRATIONS === */}
      <TransitionSeries.Sequence durationInFrames={90}>
        <S27_CommunityCards />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={slide({ direction: "from-right" })}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      <TransitionSeries.Sequence durationInFrames={220}>
        <S26_IntegrationBuilder />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={slide({ direction: "from-bottom" })}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      <TransitionSeries.Sequence durationInFrames={110}>
        <S26c_IntegrationPage />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      <TransitionSeries.Sequence durationInFrames={90}>
        <S26d_IntegrationTagline />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={slide({ direction: "from-right" })}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      {/* === ACT 7: THE PLATFORM === */}
      <TransitionSeries.Sequence durationInFrames={105}>
        <S28_DashboardReveal />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.fast })}
      />

      <TransitionSeries.Sequence durationInFrames={85}>
        <S29_OneDashboard />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={linearTiming({ durationInFrames: 4 })}
      />

      {/* === ACT 8: THE CLOSE === */}
      <TransitionSeries.Sequence durationInFrames={50}>
        <S31_NotJustAssistant />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.fast })}
      />

      <TransitionSeries.Sequence durationInFrames={72}>
        <S32_ProductivityOS />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={slide({ direction: "from-right" })}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      {/* DURATION TRIMMED: 240 → 130 */}
      <TransitionSeries.Sequence durationInFrames={130}>
        <S34_SearchBarCTA />
      </TransitionSeries.Sequence>
    </TransitionSeries>
  );
};
