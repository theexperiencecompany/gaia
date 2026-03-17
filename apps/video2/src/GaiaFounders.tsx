import type React from "react";
import {
  linearTiming,
  springTiming,
  TransitionSeries,
} from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { slide } from "@remotion/transitions/slide";
import { Audio, Sequence } from "remotion";
import { SPRINGS } from "./constants";
import { SFX } from "./sfx";
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

// Absolute frame offsets for slide transitions (fades are silent)
// S02→S03, S03→S04, S04→S05, S05→S06, S06→S07, S07→S08, S08→S09(slide), S10→S11
const WHOOSH_FRAMES = [400, 628, 856, 1024, 1222, 1330, 1498, 1868] as const;

export const GaiaFounders: React.FC = () => {
  return (
    <>
      <TransitionSeries>
        {/* S01: 180f */}
        <TransitionSeries.Sequence durationInFrames={180}>
          <S01_Notification />
        </TransitionSeries.Sequence>

        {/* S01→S02: fade 8f (silent) */}
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: 8 })}
        />

        {/* S02: 240f */}
        <TransitionSeries.Sequence durationInFrames={240}>
          <S02_TheReply />
        </TransitionSeries.Sequence>

        {/* S02→S03: slide from-right 12f */}
        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={springTiming({ config: SPRINGS.natural, durationInFrames: 12 })}
        />

        {/* S03: 240f */}
        <TransitionSeries.Sequence durationInFrames={240}>
          <S03_Research />
        </TransitionSeries.Sequence>

        {/* S03→S04: slide from-right 12f */}
        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={springTiming({ config: SPRINGS.natural, durationInFrames: 12 })}
        />

        {/* S04: 240f */}
        <TransitionSeries.Sequence durationInFrames={240}>
          <S04_DeckUpdated />
        </TransitionSeries.Sequence>

        {/* S04→S05: slide from-right 12f */}
        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={springTiming({ config: SPRINGS.natural, durationInFrames: 12 })}
        />

        {/* S05: 180f */}
        <TransitionSeries.Sequence durationInFrames={180}>
          <S05_DataRoom />
        </TransitionSeries.Sequence>

        {/* S05→S06: slide from-right 12f */}
        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={springTiming({ config: SPRINGS.natural, durationInFrames: 12 })}
        />

        {/* S06: 210f */}
        <TransitionSeries.Sequence durationInFrames={210}>
          <S06_PrepDoc />
        </TransitionSeries.Sequence>

        {/* S06→S07: slide from-right 12f */}
        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={springTiming({ config: SPRINGS.natural, durationInFrames: 12 })}
        />

        {/* S07: 120f */}
        <TransitionSeries.Sequence durationInFrames={120}>
          <S07_SlackNotify />
        </TransitionSeries.Sequence>

        {/* S07→S08: slide from-right 12f */}
        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={springTiming({ config: SPRINGS.natural, durationInFrames: 12 })}
        />

        {/* S08: 180f */}
        <TransitionSeries.Sequence durationInFrames={180}>
          <S08_CalendarSlots />
        </TransitionSeries.Sequence>

        {/* S08→S09: slide from-right 12f */}
        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={springTiming({ config: SPRINGS.natural, durationInFrames: 12 })}
        />

        {/* S09: 150f */}
        <TransitionSeries.Sequence durationInFrames={150}>
          <S09_ReplyDrafted />
        </TransitionSeries.Sequence>

        {/* S09→S10: fade 8f (silent) */}
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: 8 })}
        />

        {/* S10: 240f */}
        <TransitionSeries.Sequence durationInFrames={240}>
          <S10_TheBeat />
        </TransitionSeries.Sequence>

        {/* S10→S11: slide from-right 12f */}
        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={springTiming({ config: SPRINGS.natural, durationInFrames: 12 })}
        />

        {/* S11: 360f */}
        <TransitionSeries.Sequence durationInFrames={360}>
          <S11_Close />
        </TransitionSeries.Sequence>
      </TransitionSeries>

      {/* Global whoosh SFX for slide transitions */}
      {WHOOSH_FRAMES.map((f) => (
        <Sequence key={f} from={f}>
          <Audio src={SFX.whoosh} volume={0.25} />
        </Sequence>
      ))}
    </>
  );
};
