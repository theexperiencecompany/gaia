import { StopCircleIcon } from "@icons";

/** The quiet line under a turn the user stopped, in the same strip style as "Response was cut short". */
export default function StoppedNote() {
  return (
    <div className="mt-1 flex items-center gap-2 text-zinc-400">
      <StopCircleIcon className="shrink-0" height={15} width={15} />
      <span className="text-xs">Stopped</span>
    </div>
  );
}
