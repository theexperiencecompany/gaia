import type React from "react";
import { useEffect, useState } from "react";

const PX_PER_MINUTE = 64 / 60;

// Horizontal line that spans across all calendar columns
export const CurrentTimeLine: React.FC = () => {
  const [now, setNow] = useState<Date>(new Date());

  useEffect(() => {
    const interval = setInterval(() => {
      setNow(new Date());
    }, 60000); // Update every minute
    return () => clearInterval(interval);
  }, []);

  const currentHour = now.getHours();
  const currentMinute = now.getMinutes();
  const currentTimeTop = (currentHour * 60 + currentMinute) * PX_PER_MINUTE;

  return (
    <div
      className="absolute right-0 left-20 z-[1] h-[1px] bg-primary/50"
      style={{ top: `${currentTimeTop}px` }}
    />
  );
};

// Time label that shows in the left time column
export const CurrentTimeLabel: React.FC = () => {
  const [now, setNow] = useState<Date>(new Date());

  useEffect(() => {
    const interval = setInterval(() => {
      setNow(new Date());
    }, 60000); // Update every minute
    return () => clearInterval(interval);
  }, []);

  const currentHour = now.getHours();
  const currentMinute = now.getMinutes();
  const currentTimeLabel = now.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
  const currentTimeTop = (currentHour * 60 + currentMinute) * PX_PER_MINUTE;

  return (
    <div
      className="absolute left-0 z-[12] flex w-20 flex-shrink-0 items-center justify-end bg-[#1a1a1a] pr-3 text-xs text-primary"
      style={{ top: `${currentTimeTop - 8}px` }}
    >
      {currentTimeLabel}
    </div>
  );
};
