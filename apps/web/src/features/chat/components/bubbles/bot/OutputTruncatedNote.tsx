import { InformationCircleIcon } from "@icons";
import { outputTruncatedNote } from "@shared/conversation";

interface OutputTruncatedNoteProps {
  originalLength: number;
}

/** The quiet line under a tool's output or a subagent's result that the server cut. */
export function OutputTruncatedNote({
  originalLength,
}: Readonly<OutputTruncatedNoteProps>) {
  return (
    <p className="mt-2 flex items-center gap-1 text-zinc-500">
      <InformationCircleIcon className="shrink-0" height={12} width={12} />
      <span>{outputTruncatedNote(originalLength)}</span>
    </p>
  );
}
