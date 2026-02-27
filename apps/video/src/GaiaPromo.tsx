import React from "react";
import { TransitionSeries, linearTiming, springTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { slide } from "@remotion/transitions/slide";
import { wipe } from "@remotion/transitions/wipe";
import { TRANSITIONS } from "./constants";

// Act 1 & 2
import { S01_OpeningStatement } from "./scenes/S01_OpeningStatement";
import { S02_ToolChaos } from "./scenes/S02_ToolChaos";
import { S03_BetterWay } from "./scenes/S03_BetterWay";
import { S04_LogoBloom } from "./scenes/S04_LogoBloom";
import { S05_MeetGaia } from "./scenes/S05_MeetGaia";

// Act 3: Workflow Creation via Chat (replaces modal scenes S06–S15)
import { S06_UserChat } from "./scenes/S06_UserChat";
import { S07_ChatToolCalls } from "./scenes/S07_ChatToolCalls";
import { S08_ChatResponse } from "./scenes/S08_ChatResponse";
import { S09_ChatWorkflowCreated } from "./scenes/S09_ChatWorkflowCreated";

// Act 4: Execution
import { S16_ModalToCard } from "./scenes/S16_ModalToCard";
import { S17_RunningToolStack } from "./scenes/S17_RunningToolStack";
import { S18_ToolCallsExpand } from "./scenes/S18_ToolCallsExpand";
import { S19_BotMessageStream } from "./scenes/S19_BotMessageStream";
import { S21_Completed } from "./scenes/S21_Completed";

// Act 5: Multi-Platform
import { S22_MacOSNotifications } from "./scenes/S22_MacOSNotifications";
import { S23_PlatformIcons } from "./scenes/S23_PlatformIcons";
import { S24_NotificationPreview } from "./scenes/S24_NotificationPreview";

// Act 6: Ecosystem
import { S25_AllYourTools } from "./scenes/S25_AllYourTools";
import { S27_CommunityCards } from "./scenes/S27_CommunityCards";

// Act 7 & 8: Platform + Close
import { S28_DashboardReveal } from "./scenes/S28_DashboardReveal";
import { S29_OneDashboard } from "./scenes/S29_OneDashboard";
import { S30_FourPillars } from "./scenes/S30_FourPillars";
import { S31_NotJustAssistant } from "./scenes/S31_NotJustAssistant";
import { S32_ProductivityOS } from "./scenes/S32_ProductivityOS";
import { S33_CTAClose } from "./scenes/S33_CTAClose";
import { S34_SearchBarCTA } from "./scenes/S34_SearchBarCTA";

const T = TRANSITIONS;

export const GaiaPromo: React.FC = () => {
  return (
    <TransitionSeries>
      {/* === ACT 1: THE HOOK === */}
      <TransitionSeries.Sequence durationInFrames={120}>
        <S01_OpeningStatement />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.fast })}
      />

      <TransitionSeries.Sequence durationInFrames={100}>
        <S02_ToolChaos />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      <TransitionSeries.Sequence durationInFrames={102}>
        <S03_BetterWay />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={linearTiming({ durationInFrames: T.normal })}
      />

      <TransitionSeries.Sequence durationInFrames={102}>
        <S04_LogoBloom />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      {/* === ACT 2: MEET GAIA === */}
      <TransitionSeries.Sequence durationInFrames={110}>
        <S05_MeetGaia />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.slow })}
      />

      {/* === ACT 3: WORKFLOW CREATION VIA CHAT === */}
      {/* User sends a long multi-tool request */}
      <TransitionSeries.Sequence durationInFrames={240}>
        <S06_UserChat />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      {/* GAIA runs tool calls */}
      <TransitionSeries.Sequence durationInFrames={150}>
        <S07_ChatToolCalls />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      {/* GAIA streams response + proposes workflow draft */}
      <TransitionSeries.Sequence durationInFrames={210}>
        <S08_ChatResponse />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      {/* User confirms — workflow created */}
      <TransitionSeries.Sequence durationInFrames={130}>
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
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      <TransitionSeries.Sequence durationInFrames={132}>
        <S17_RunningToolStack />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      <TransitionSeries.Sequence durationInFrames={102}>
        <S18_ToolCallsExpand />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      <TransitionSeries.Sequence durationInFrames={162}>
        <S19_BotMessageStream />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      <TransitionSeries.Sequence durationInFrames={90}>
        <S21_Completed />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={wipe({ direction: "from-right" })}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      {/* === ACT 5: MULTI-PLATFORM === */}
      <TransitionSeries.Sequence durationInFrames={132}>
        <S23_PlatformIcons />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      <TransitionSeries.Sequence durationInFrames={132}>
        <S22_MacOSNotifications />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      <TransitionSeries.Sequence durationInFrames={102}>
        <S24_NotificationPreview />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.slow })}
      />

      {/* === ACT 6: ECOSYSTEM === */}
      <TransitionSeries.Sequence durationInFrames={132}>
        <S25_AllYourTools />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      <TransitionSeries.Sequence durationInFrames={180}>
        <S27_CommunityCards />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      {/* === ACT 7: THE PLATFORM === */}
      <TransitionSeries.Sequence durationInFrames={132}>
        <S28_DashboardReveal />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      <TransitionSeries.Sequence durationInFrames={102}>
        <S29_OneDashboard />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.normal })}
      />

      <TransitionSeries.Sequence durationInFrames={102}>
        <S30_FourPillars />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={linearTiming({ durationInFrames: T.reveal })}
      />

      {/* === ACT 8: THE CLOSE === */}
      <TransitionSeries.Sequence durationInFrames={72}>
        <S31_NotJustAssistant />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.fast })}
      />

      <TransitionSeries.Sequence durationInFrames={102}>
        <S32_ProductivityOS />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.slow })}
      />

      <TransitionSeries.Sequence durationInFrames={102}>
        <S33_CTAClose />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={fade()}
        timing={springTiming({ config: { damping: 200 }, durationInFrames: T.slow })}
      />
      <TransitionSeries.Sequence durationInFrames={120}>
        <S34_SearchBarCTA />
      </TransitionSeries.Sequence>
    </TransitionSeries>
  );
};
