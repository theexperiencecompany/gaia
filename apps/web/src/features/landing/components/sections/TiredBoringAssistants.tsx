import { Tooltip } from "@heroui/tooltip";
import Image from "next/image";

import GetStartedButton from "../shared/GetStartedButton";
import LargeHeader from "../shared/LargeHeader";

export default function Tired() {
  return (
    <div className="relative flex min-h-screen flex-col items-start justify-center  p-4 sm:p-6 lg:p-10 max-w-7xl mx-auto">
      <LargeHeader
        chipText="Not just a chatbot"
        headingText="Tired of Boring Assistants?"
        subHeadingText="Meet one that actually works."
      />

      <div className="flex w-full flex-1 flex-col gap-8 sm:flex-row sm:gap-20">
        {/* Left column: Paragraph */}
        <div className="flex flex-1 items-start justify-center">
          <p className="text-left text-base text-foreground-400 font-light sm:text-lg lg:text-xl relative top-14 flex flex-col gap-5">
            <span>
              Most digital assistants today are reactive and limited. Siri,
              Alexa, Google Assistant, and even ChatGPT answer questions, but
              they don’t understand your workload, remember context, handle
              follow-through, or take initiative.
            </span>
            <span>
              They also don’t sound and feel personal. They're generic and
              robotic, never adapting to how you think or work. They can’t read
              your inbox, pull out tasks, update your calendar, manage goals, or
              run processes without being told each step. They behave like chat
              interfaces, not real assistants, which is why people don’t rely on
              them for serious work.
            </span>
            <span>
              GAIA is built to solve this by being proactive, context-aware, and
              connected to your digital life so it can act, not just respond.
            </span>
          </p>
        </div>

        {/* Right column: Icons, GAIA logo, tooltips, button */}
        <div className="relative flex flex-1 flex-col items-center justify-start gap-6">
          <div className="relative z-[1] flex gap-6 pt-6 sm:gap-10 sm:pt-8 lg:gap-14 lg:pt-10">
            <Image
              src={"/images/icons/siri.webp"}
              alt="Siri Logo"
              width={70}
              height={70}
              className="size-[50px] translate-y-4 -rotate-8 rounded-xl sm:size-[60px] sm:translate-y-6 sm:rounded-2xl lg:size-[65px] lg:translate-y-7"
            />

            <div className="flex size-[60px] items-center justify-center overflow-hidden rounded-xl sm:size-[70px] sm:rounded-3xl lg:size-[80px]">
              <Image
                src={
                  "https://static.vecteezy.com/system/resources/previews/055/687/055/non_2x/rectangle-gemini-google-icon-symbol-logo-free-png.png"
                }
                alt="Gemini Logo"
                width={150}
                className="min-w-[90px]"
                height={150}
              />
            </div>

            <Image
              src={
                "https://static.vecteezy.com/system/resources/previews/024/558/807/non_2x/openai-chatgpt-logo-icon-free-png.png"
              }
              alt="ChatGPT Logo"
              width={70}
              height={70}
              className="size-[50px] translate-y-4 rotate-8 rounded-xl sm:size-[60px] sm:translate-y-6 sm:rounded-2xl lg:size-[65px] lg:translate-y-7"
            />
          </div>

          <Image
            src={"/images/logos/logo.webp"}
            alt="GAIA Logo"
            width={120}
            height={120}
            className="relative z-[1] my-8 h-[100px] w-[100px] rounded-2xl bg-gradient-to-b from-surface-200 to-surface-50 p-3 shadow-[0px_0px_100px_40px_rgba(0,_187,_255,_0.2)] outline-1 outline-surface-200 sm:my-10 sm:h-[110px] sm:w-[110px] sm:rounded-3xl sm:p-4 lg:my-14 lg:h-[120px] lg:w-[120px]"
          />

          {/* Tooltips */}
          <div className="relative flex w-full max-w-xs items-center px-4 sm:max-w-md sm:px-0 lg:max-w-lg">
            <Tooltip
              content="Truly personal AI: it understands your habits, learns your priorities, and keeps track of everything that matters to you."
              className="max-w-60 p-2"
              showArrow
              placement="bottom-end"
              offset={-10}
            >
              <div className="absolute bottom-8 left-0 -rotate-12 cursor-default rounded-lg bg-surface-200 px-2 py-1 text-xs text-foreground-400 sm:bottom-12 sm:rounded-xl sm:px-3 sm:py-2 sm:text-sm lg:bottom-16">
                Personalised
              </div>
            </Tooltip>

            <Tooltip
              content="From upcoming deadlines to important emails, GAIA acts ahead of time so you stay one step ahead."
              className="max-w-60 p-2"
              showArrow
              placement="bottom-start"
              offset={-10}
            >
              <div className="absolute right-0 bottom-8 rotate-12 cursor-default rounded-lg bg-surface-200 px-2 py-1 text-xs text-foreground-400 sm:bottom-12 sm:rounded-xl sm:px-3 sm:py-2 sm:text-sm lg:bottom-16">
                Proactive
              </div>
            </Tooltip>

            <Tooltip
              content="GAIA handles repetitive tasks automatically ,  scheduling, email triage, and task management ,  saving you hours every day."
              className="max-w-60 p-2"
              showArrow
              placement="left"
              offset={-1}
            >
              <div className="absolute bottom-20 left-6 rotate-12 cursor-default rounded-lg bg-surface-200 px-2 py-1 text-xs text-foreground-400 sm:bottom-28 sm:left-8 sm:rounded-xl sm:px-3 sm:py-2 sm:text-sm lg:bottom-40 lg:left-10">
                Automated
              </div>
            </Tooltip>

            <Tooltip
              content="Everything works together: GAIA keeps your tools synced, your data connected, and your day organized."
              className="max-w-60 p-2"
              showArrow
              placement="right"
              offset={-1}
            >
              <div className="absolute right-6 bottom-20 -rotate-12 cursor-default rounded-lg bg-surface-200 px-2 py-1 text-xs text-foreground-400 sm:right-8 sm:bottom-28 sm:rounded-xl sm:px-3 sm:py-2 sm:text-sm lg:right-10 lg:bottom-40">
                Integrated
              </div>
            </Tooltip>
          </div>

          <GetStartedButton text="See GAIA in Action" />
        </div>
      </div>
    </div>
  );
}
