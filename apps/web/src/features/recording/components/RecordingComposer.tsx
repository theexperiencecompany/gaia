"use client";

import { ArrowUp02Icon, PlusSignIcon, ToolsIcon } from "@icons";

export default function RecordingComposer() {
  return (
    <div className="searchbar_container relative flex w-full flex-col justify-center pb-1 px-2">
      <div className="searchbar relative rounded-3xl bg-zinc-800 px-1 pt-1 pb-2">
        {/* Input area — matches HeroUI Textarea inputWrapper with px-3, size="lg" */}
        <div className="px-3 py-2.5 min-h-[44px] flex items-center">
          <span className="text-base font-light text-zinc-500 select-none">
            What can I do for you today?
          </span>
        </div>
        {/* Toolbar row — matches ComposerToolbar layout */}
        <div className="flex items-center justify-between px-2 pt-1">
          {/* Left: + button + tools button — matches ComposerLeft */}
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="relative h-9 w-9 rounded-full border-none bg-zinc-700 p-0 flex items-center justify-center"
              aria-hidden="true"
              tabIndex={-1}
            >
              <PlusSignIcon className="min-h-[23px] min-w-[23px] text-zinc-400" />
            </button>
            <button
              type="button"
              className="relative h-9 w-9 rounded-full border-none bg-zinc-700 p-0 flex items-center justify-center text-zinc-400 fill-zinc-400"
              aria-hidden="true"
              tabIndex={-1}
            >
              <ToolsIcon className="min-h-[23px] min-w-[23px]" width={23} height={23} />
            </button>
          </div>
          {/* Right: send button (disabled) — matches ComposerRight */}
          <div className="ml-2 flex items-center gap-2">
            <button
              type="button"
              className="h-9 min-h-9 w-9 max-w-9 min-w-9 flex items-center justify-center rounded-full bg-zinc-700"
              aria-hidden="true"
              tabIndex={-1}
            >
              <ArrowUp02Icon color="gray" width={20} height={20} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
