"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Divider } from "@heroui/divider";
import {
  BookOpen01Icon,
  BrainIcon,
  Delete02Icon,
  Edit02Icon,
  FileEmpty02Icon,
  Folder01Icon,
  Search01Icon,
} from "@icons";
import { formatDistanceToNow } from "date-fns";
import { useState } from "react";
import type { MemoryData } from "@/config/registries/toolRegistry";
import type { MemoryEntry } from "@/features/memory/api/types";
import { CORE_DOCUMENTS } from "@/features/memory/constants";

interface MemoryCardProps {
  items: MemoryData[];
}

// ─── helpers ────────────────────────────────────────────────────────────────

function outcomeLabel(outcome: "new" | "updated" | "extended" | "duplicate") {
  const map = {
    new: { label: "Saved", color: "success" } as const,
    updated: { label: "Updated", color: "primary" } as const,
    extended: { label: "Extended", color: "primary" } as const,
    duplicate: { label: "Already known", color: "default" } as const,
  };
  return map[outcome];
}

function folderLabel(path: string): string {
  // Show only the last segment for compactness, e.g. "people/family" -> "family"
  const parts = path.split("/").filter(Boolean);
  return parts[parts.length - 1] ?? path;
}

function docTypeName(docType: string): string {
  const found = CORE_DOCUMENTS.find((d) => d.docType === docType);
  return found ? found.fileName : docType;
}

function relativeDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: true });
  } catch {
    return null;
  }
}

// ─── sub-components ─────────────────────────────────────────────────────────

function MemoryRow({ memory }: { memory: MemoryEntry }) {
  const ts = memory.updated_at ?? memory.created_at ?? memory.mentioned_at;
  const rel = relativeDate(ts);
  return (
    <div className="flex flex-col gap-0.5 rounded-2xl bg-zinc-900 p-3">
      <p className="text-sm leading-snug text-zinc-100">{memory.content}</p>
      <div className="flex flex-wrap items-center gap-1.5 pt-1">
        {memory.category_path && (
          <div className="flex items-center gap-1">
            <Folder01Icon className="size-3 text-zinc-600" />
            <span className="text-xs text-zinc-500">
              {folderLabel(memory.category_path)}
            </span>
          </div>
        )}
        {rel && <span className="text-xs text-zinc-600">{rel}</span>}
        {memory.version > 1 && (
          <span className="text-xs text-zinc-600">v{memory.version}</span>
        )}
      </div>
    </div>
  );
}

// ─── action sections ─────────────────────────────────────────────────────────

function AddSection({
  item,
}: {
  item: Extract<MemoryData, { action: "add" }>;
}) {
  const { label, color } = outcomeLabel(item.outcome);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <BrainIcon className="size-4 text-zinc-400" />
          <span className="text-xs font-medium text-zinc-300">
            Memory stored
          </span>
          {item.folder && (
            <div className="flex items-center gap-1">
              <Folder01Icon className="size-3 text-zinc-600" />
              <span className="text-xs text-zinc-500">
                {folderLabel(item.folder)}
              </span>
            </div>
          )}
        </div>
        <Chip
          size="sm"
          variant="flat"
          color={color}
          classNames={{ content: "text-xs font-medium" }}
        >
          {label}
        </Chip>
      </div>
      <div className="flex flex-col gap-1.5">
        {item.memories.map((m, i) => (
          <MemoryRow key={m.id ?? i} memory={m} />
        ))}
      </div>
    </div>
  );
}

function SearchSection({
  item,
}: {
  item: Extract<MemoryData, { action: "search" }>;
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <Search01Icon className="size-4 text-zinc-400" />
        <span className="text-xs font-medium text-zinc-300">Memory recall</span>
        {item.folder && (
          <div className="flex items-center gap-1">
            <Folder01Icon className="size-3 text-zinc-600" />
            <span className="text-xs text-zinc-500">
              {folderLabel(item.folder)}
            </span>
          </div>
        )}
        <Chip
          size="sm"
          variant="flat"
          classNames={{
            base: "ml-auto",
            content: "text-xs text-zinc-400",
          }}
        >
          {item.memories.length} result{item.memories.length !== 1 ? "s" : ""}
        </Chip>
      </div>
      {item.memories.length > 0 ? (
        <div className="flex flex-col gap-1.5">
          {item.memories.map((m, i) => (
            <MemoryRow key={m.id ?? i} memory={m} />
          ))}
        </div>
      ) : (
        <div className="rounded-2xl bg-zinc-900 p-3">
          <p className="text-xs text-zinc-500">Nothing found for this query</p>
        </div>
      )}
    </div>
  );
}

function UpdateSection({
  item,
}: {
  item: Extract<MemoryData, { action: "update" }>;
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <Edit02Icon className="size-4 text-zinc-400" />
        <span className="text-xs font-medium text-zinc-300">
          Memory updated
        </span>
      </div>
      <div className="flex flex-col gap-1.5">
        {item.memories.map((m, i) => (
          <MemoryRow key={m.id ?? i} memory={m} />
        ))}
      </div>
    </div>
  );
}

function ForgetSection({
  item,
}: {
  item: Extract<MemoryData, { action: "forget" }>;
}) {
  return (
    <div className="flex items-center gap-2">
      <Delete02Icon className="size-4 text-zinc-500" />
      <p className="text-sm text-zinc-400">{item.message}</p>
    </div>
  );
}

function JournalSection({
  item,
}: {
  item: Extract<MemoryData, { action: "journal" }>;
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <BookOpen01Icon className="size-4 text-zinc-400" />
        <span className="text-xs font-medium text-zinc-300">Journal</span>
        {item.query && (
          <span className="truncate text-xs text-zinc-500">{item.query}</span>
        )}
      </div>
      <div className="flex flex-col gap-1.5">
        {item.episodes.map((ep) => (
          <div key={ep.date} className="rounded-2xl bg-zinc-900 p-3">
            <p className="mb-1.5 text-xs font-medium text-zinc-400">
              {ep.date}
            </p>
            <div className="flex flex-col gap-1">
              {ep.entries.map((entry, i) => (
                <div
                  key={`${entry.time ?? i}-${entry.text.slice(0, 20)}`}
                  className="flex gap-2"
                >
                  {entry.time && (
                    <span className="shrink-0 text-xs text-zinc-600">
                      {entry.time}
                    </span>
                  )}
                  <p className="text-sm leading-snug text-zinc-200">
                    {entry.text}
                  </p>
                </div>
              ))}
            </div>
            {ep.summary && (
              <p className="mt-2 text-xs leading-relaxed text-zinc-500">
                {ep.summary}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function DocumentSection({
  item,
}: {
  item: Extract<MemoryData, { action: "document" }>;
}) {
  const [expanded, setExpanded] = useState(false);
  const { document: doc, updated } = item;
  const displayName = docTypeName(doc.doc_type);
  const preview = doc.content.slice(0, 280);
  const hasMore = doc.content.length > 280;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <FileEmpty02Icon className="size-4 text-zinc-400" />
          <span className="text-xs font-medium text-zinc-300">
            {displayName}
          </span>
        </div>
        <Chip
          size="sm"
          variant="flat"
          color={updated ? "primary" : "default"}
          classNames={{ content: "text-xs font-medium" }}
        >
          {updated ? "Updated" : "Read"}
        </Chip>
      </div>
      <div className="rounded-2xl bg-zinc-900 p-3">
        <p className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-zinc-300">
          {expanded ? doc.content : preview}
        </p>
        {hasMore && (
          <Button
            size="sm"
            variant="light"
            radius="full"
            onPress={() => setExpanded((v) => !v)}
            className="mt-2 h-auto min-w-0 px-2 py-1 text-xs text-zinc-500 data-[hover=true]:bg-transparent data-[hover=true]:text-zinc-300"
          >
            {expanded ? "Show less" : "Show more"}
          </Button>
        )}
      </div>
    </div>
  );
}

// ─── main component ──────────────────────────────────────────────────────────

export default function MemoryCard({ items }: MemoryCardProps) {
  if (items.length === 0) return null;

  return (
    <div className="flex w-full max-w-md flex-col gap-0 overflow-hidden rounded-2xl bg-zinc-800">
      <div className="flex flex-col gap-3 p-4">
        {items.map((item, i) => (
          <div key={`${item.action}-${i}`}>
            {i > 0 && <Divider className="mb-3 bg-zinc-700/50" />}
            {item.action === "add" && <AddSection item={item} />}
            {item.action === "search" && <SearchSection item={item} />}
            {item.action === "update" && <UpdateSection item={item} />}
            {item.action === "forget" && <ForgetSection item={item} />}
            {item.action === "journal" && <JournalSection item={item} />}
            {item.action === "document" && <DocumentSection item={item} />}
          </div>
        ))}
      </div>
    </div>
  );
}
