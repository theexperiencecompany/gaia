import type React from "react";
import {
  linearTiming,
  springTiming,
  TransitionSeries,
} from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { slide } from "@remotion/transitions/slide";
import { wipe } from "@remotion/transitions/wipe";
import { S01_Notification } from "./scenes/S01_Notification";
import { S02_TheReply } from "./scenes/S02_TheReply";
import { S03_Research } from "./scenes/S03_Research";
import { S04_DeckUpdated } from "./scenes/S04_DeckUpdated";
import { S05_DataRoom } from "./scenes/S05_DataRoom";
import { S06_PrepDoc } from "./scenes/S06_PrepDoc";
import { S07_SlackNotify } from "./scenes/S07_SlackNotify";
import { S08_CalendarSlots } from "./scenes/S08_CalendarSlots";
import { S09_ReplyDrafted } from "./scenes/S09_ReplyDrafted";
import { S10_TheBeat } from "./scenes/S10_TheBeat";
import { S11_Close } from "./scenes/S11_Close";
import { SPRINGS } from "./constants";

// Duration math:
// Scenes:      80 + 120 + 100 + 110 + 90 + 120 + 80 + 100 + 130 + 150 + 210 = 1290
// Transitions: 12 + 15 + 15 + 15 + 15 + 12 + 15 + 15 + 12 + 12 = 138
// Total:       1290 - 138 = 1152

export const GaiaFounders: React.FC = () => {
  return (
    <TransitionSeries>
      {/* S01: 80f */}
      <TransitionSeries.Sequence durationInFrames={80}>
        <S01_Notification />
      </TransitionSeries.Sequence>

      {/* S01→S02: fade 12f — soft tone shift */}
      <TransitionSeries.Transition
        presentation={fade()}
        timing={linearTiming({ durationInFrames: 12 })}
      />

      {/* S02: 120f */}
      <TransitionSeries.Sequence durationInFrames={120}>
        <S02_TheReply />
      </TransitionSeries.Sequence>

      {/* S02→S03: wipe from-right 15f — card morph */}
      <TransitionSeries.Transition
        presentation={wipe({ direction: "from-right" })}
        timing={springTiming({ config: SPRINGS.snappy, durationInFrames: 15 })}
      />

      {/* S03: 100f */}
      <TransitionSeries.Sequence durationInFrames={100}>
        <S03_Research />
      </TransitionSeries.Sequence>

      {/* S03→S04: wipe from-right 15f */}
      <TransitionSeries.Transition
        presentation={wipe({ direction: "from-right" })}
        timing={springTiming({ config: SPRINGS.snappy, durationInFrames: 15 })}
      />

      {/* S04: 110f */}
      <TransitionSeries.Sequence durationInFrames={110}>
        <S04_DeckUpdated />
      </TransitionSeries.Sequence>

      {/* S04→S05: wipe from-right 15f */}
      <TransitionSeries.Transition
        presentation={wipe({ direction: "from-right" })}
        timing={springTiming({ config: SPRINGS.snappy, durationInFrames: 15 })}
      />

      {/* S05: 90f */}
      <TransitionSeries.Sequence durationInFrames={90}>
        <S05_DataRoom />
      </TransitionSeries.Sequence>

      {/* S05→S06: wipe from-right 15f */}
      <TransitionSeries.Transition
        presentation={wipe({ direction: "from-right" })}
        timing={springTiming({ config: SPRINGS.snappy, durationInFrames: 15 })}
      />

      {/* S06: 120f */}
      <TransitionSeries.Sequence durationInFrames={120}>
        <S06_PrepDoc />
      </TransitionSeries.Sequence>

      {/* S06→S07: slide from-right 12f — new medium (Slack) */}
      <TransitionSeries.Transition
        presentation={slide({ direction: "from-right" })}
        timing={springTiming({ config: SPRINGS.natural, durationInFrames: 12 })}
      />

      {/* S07: 80f */}
      <TransitionSeries.Sequence durationInFrames={80}>
        <S07_SlackNotify />
      </TransitionSeries.Sequence>

      {/* S07→S08: wipe from-right 15f — card morph */}
      <TransitionSeries.Transition
        presentation={wipe({ direction: "from-right" })}
        timing={springTiming({ config: SPRINGS.snappy, durationInFrames: 15 })}
      />

      {/* S08: 100f */}
      <TransitionSeries.Sequence durationInFrames={100}>
        <S08_CalendarSlots />
      </TransitionSeries.Sequence>

      {/* S08→S09: wipe from-right 15f — card morph */}
      <TransitionSeries.Transition
        presentation={wipe({ direction: "from-right" })}
        timing={springTiming({ config: SPRINGS.snappy, durationInFrames: 15 })}
      />

      {/* S09: 130f */}
      <TransitionSeries.Sequence durationInFrames={130}>
        <S09_ReplyDrafted />
      </TransitionSeries.Sequence>

      {/* S09→S10: fade 12f — dramatic tone shift */}
      <TransitionSeries.Transition
        presentation={fade()}
        timing={linearTiming({ durationInFrames: 12 })}
      />

      {/* S10: 150f */}
      <TransitionSeries.Sequence durationInFrames={150}>
        <S10_TheBeat />
      </TransitionSeries.Sequence>

      {/* S10→S11: slide from-right 12f — cinematic exit */}
      <TransitionSeries.Transition
        presentation={slide({ direction: "from-right" })}
        timing={springTiming({ config: SPRINGS.natural, durationInFrames: 12 })}
      />

      {/* S11: 210f */}
      <TransitionSeries.Sequence durationInFrames={210}>
        <S11_Close />
      </TransitionSeries.Sequence>
    </TransitionSeries>
  );
};
