import type React from "react";
import { useEffect, useState } from "react";

const PX_PER_MINUTE = 64 / 60;

// Module-scope formatter — constructing Intl formatters is slow. `undefined`
// locale resolves to the runtime's default locale, matching the previous
// `toLocaleTimeString([], ...)` behavior.
const CURRENT_TIME_FORMATTER = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
});

// Current wall-clock time, refreshed every minute, plus its label formatted
// inside the update tick. Starts as null/empty so nothing time-dependent is
// rendered on the server; both values are first set after mount, avoiding
// hydration mismatches from server/client clock or locale differences.
interface CurrentTime {
  now: Date | null;
  label: string;
}

function useCurrentTime(): CurrentTime {
  const [time, setTime] = useState<CurrentTime>({ now: null, label: "" });

  useEffect(() => {
    const update = () => {
      const now = new Date();
      setTime({ now, label: CURRENT_TIME_FORMATTER.format(now) });
    };
    update();
    const interval = setInterval(update, 60000); // Update every minute
    return () => clearInterval(interval);
  }, []);

  return time;
}

// Horizontal line that spans across all calendar columns
export const CurrentTimeLine: React.FC = () => {
  const { now } = useCurrentTime();

  const currentTimeTop = now
    ? (now.getHours() * 60 + now.getMinutes()) * PX_PER_MINUTE
    : 0;

  return (
    <div
      className="absolute right-0 left-20 z-[1] h-[1px] bg-primary/50"
      style={{ top: `${currentTimeTop}px` }}
    />
  );
};

// Time label that shows in the left time column
export const CurrentTimeLabel: React.FC = () => {
  const { now, label } = useCurrentTime();

  const currentTimeTop = now
    ? (now.getHours() * 60 + now.getMinutes()) * PX_PER_MINUTE
    : 0;

  return (
    <div
      className="absolute left-0 z-[12] flex w-20 flex-shrink-0 items-center justify-end bg-primary-bg pr-3 text-xs text-primary"
      style={{ top: `${currentTimeTop - 8}px` }}
    >
      {label}
    </div>
  );
};
