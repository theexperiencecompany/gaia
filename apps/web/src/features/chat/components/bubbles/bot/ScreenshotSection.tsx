import { ComputerIcon } from "@icons";
import type React from "react";
import type { ScreenshotData } from "@/types/features/desktopToolTypes";

interface ScreenshotSectionProps {
  screenshot_data: ScreenshotData;
}

/** Card shown when GAIA looked at the user's screen via the desktop app. */
const ScreenshotSection: React.FC<ScreenshotSectionProps> = ({
  screenshot_data,
}) => {
  if (!screenshot_data?.thumbnail) return null;

  return (
    <div className="max-w-sm rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center gap-2">
        <ComputerIcon className="size-4 text-zinc-400" />
        <span className="text-sm text-zinc-400">Looked at your screen</span>
      </div>
      {/* Raw data URL from the local capture — next/image can't optimize it. */}
      {/* biome-ignore lint/performance/noImgElement: data-URL screenshot */}
      <img
        src={screenshot_data.thumbnail}
        alt="Screenshot of your screen"
        width={screenshot_data.width}
        height={screenshot_data.height}
        className="w-full rounded-xl"
      />
    </div>
  );
};

export default ScreenshotSection;
