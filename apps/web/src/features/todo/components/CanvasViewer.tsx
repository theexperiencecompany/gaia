"use client";

import { Spinner } from "@heroui/spinner";
import { ActivityIcon, CanvasIcon } from "@icons";
import type React from "react";
import { useRef, useState } from "react";
import MarkdownViewerModal from "@/components/common/MarkdownViewerModal";
import { getTodoCanvas, type TodoNotes } from "@/features/todo/api/todoApi";

interface CanvasViewerProps {
  todoId: string;
  todoTitle: string;
}

type NotesFile = "canvas.md" | "activity.md";

const FILES: {
  name: NotesFile;
  hint: string;
  Icon: React.ComponentType<{ className?: string }>;
  pick: (notes: TodoNotes) => string;
}[] = [
  {
    name: "canvas.md",
    hint: "GAIA working memory",
    Icon: CanvasIcon,
    pick: (n) => n.content,
  },
  {
    name: "activity.md",
    hint: "What happened, in order",
    Icon: ActivityIcon,
    pick: (n) => n.activity,
  },
];

const CanvasViewer: React.FC<CanvasViewerProps> = ({ todoId, todoTitle }) => {
  const [openFile, setOpenFile] = useState<NotesFile | null>(null);
  const [notes, setNotes] = useState<TodoNotes | null>(null);
  // Which todo the notes above were fetched for. Compared at render time so
  // a late response for the previous todo can never render under the current
  // title (the sidebar keeps this component mounted across selections).
  const [notesTodoId, setNotesTodoId] = useState<string | null>(null);
  // Which request the spinner belongs to (null when idle). Loading is tied
  // to the request identity — not a bare flag — so a supplanted request can
  // never hide the spinner of the request that replaced it.
  const [loadingRequest, setLoadingRequest] = useState<number | null>(null);
  const [hasError, setHasError] = useState(false);
  const isLoading = loadingRequest !== null;
  // The sidebar keeps this component mounted across todo selections, so a
  // fetch started for todo A can resolve after todo B is selected. Only the
  // latest request may touch state.
  const requestId = useRef(0);

  const handleOpen = async (file: NotesFile) => {
    setOpenFile(file);
    // Always refetch on open so the viewer never shows a stale or wrong todo's
    // notes (the sidebar keeps this component mounted across selections).
    const current = todoId;
    const myRequest = ++requestId.current;
    const isCurrent = () => requestId.current === myRequest;
    setLoadingRequest(myRequest);
    setHasError(false);
    try {
      const fetched = await getTodoCanvas(current);
      if (isCurrent()) {
        setNotes(fetched);
        setNotesTodoId(current);
      }
    } catch {
      if (isCurrent()) setHasError(true);
    } finally {
      // Functional update: only the request that set the spinner may clear
      // it. Unconditional call, identity-checked transition — a late
      // loser cannot hide the winner's loading state.
      setLoadingRequest((active) => (active === myRequest ? null : active));
    }
  };

  const open = FILES.find((f) => f.name === openFile);

  return (
    <>
      <div className="flex flex-col gap-2">
        {FILES.map(({ name, hint, Icon }) => (
          <button
            key={name}
            type="button"
            onClick={() => handleOpen(name)}
            className="flex w-full items-center gap-3 rounded-2xl bg-zinc-800 px-3 py-2.5 text-left transition-colors hover:bg-zinc-700/70"
          >
            <div className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-violet-500/15">
              <Icon className="size-4 text-violet-400" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium text-zinc-300">{name}</p>
              <p className="truncate text-xs text-zinc-500">{hint}</p>
            </div>
            {isLoading && openFile === name && (
              <Spinner size="sm" color="default" />
            )}
          </button>
        ))}
      </div>

      <MarkdownViewerModal
        isOpen={openFile !== null}
        onClose={() => setOpenFile(null)}
        title={`${openFile ?? "canvas.md"} — ${todoTitle}`}
        content={
          notes && open && notesTodoId === todoId ? open.pick(notes) : null
        }
        isLoading={isLoading}
        hasError={hasError}
        errorMessage={`Couldn't load ${openFile ?? "the notes"}. Close and reopen to try again.`}
      />
    </>
  );
};

export default CanvasViewer;
