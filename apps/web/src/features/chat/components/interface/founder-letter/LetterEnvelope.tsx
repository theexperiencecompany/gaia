"use client";

import * as m from "motion/react-m";
import Image from "next/image";

/** The sealed envelope the letter arrives in: the artwork file as it is. */
const ENVELOPE_IMAGE = "/images/icons/sealed-envelope.webp";
const ENVELOPE_WIDTH = 1536;
const ENVELOPE_HEIGHT = 1024;

interface LetterEnvelopeProps {
  /** Once the letter has been read, the envelope settles and offers dismissal. */
  hasOpened: boolean;
  reduceMotion: boolean | null;
  onOpen: () => void;
  onDismiss: () => void;
}

/** A folded letter, waiting in the bottom-right corner above the composer. */
export function LetterEnvelope({
  hasOpened,
  reduceMotion,
  onOpen,
  onDismiss,
}: LetterEnvelopeProps) {
  const still = reduceMotion || hasOpened;

  return (
    <div className="fixed right-4 bottom-[calc(9.5rem+env(safe-area-inset-bottom))] z-40 flex flex-col items-end gap-1 sm:bottom-24">
      <m.button
        type="button"
        onClick={onOpen}
        aria-label="A letter from Aryan Randeriya"
        title="A letter from Aryan"
        className="isolate cursor-pointer rounded-md outline-none focus-visible:ring-2 focus-visible:ring-[#00bbff]"
        initial={false}
        whileHover={reduceMotion ? undefined : { scale: 1.06 }}
        whileTap={reduceMotion ? undefined : { scale: 0.94 }}
        // A jump, not a float: two hops, then it sits still long enough to
        // stop being noise.
        // It jumps for attention until it has been read, then settles.
        animate={still ? undefined : { y: [0, -16, 0, -7, 0] }}
        transition={
          still
            ? undefined
            : {
                y: {
                  duration: 1.1,
                  times: [0, 0.28, 0.52, 0.72, 0.9],
                  ease: "easeOut",
                  repeat: Number.POSITIVE_INFINITY,
                  repeatDelay: 2.6,
                },
              }
        }
      >
        <Image
          src={ENVELOPE_IMAGE}
          alt=""
          width={ENVELOPE_WIDTH}
          height={ENVELOPE_HEIGHT}
          priority
          className="block w-14 rotate-[-3deg] sm:w-20"
        />
      </m.button>
      {hasOpened && (
        <button
          type="button"
          onClick={onDismiss}
          className="cursor-pointer pr-1 text-[11px] font-normal text-zinc-400 outline-none transition-colors hover:text-zinc-200 focus-visible:ring-2 focus-visible:ring-[#00bbff]"
        >
          Don't show again
        </button>
      )}
    </div>
  );
}
