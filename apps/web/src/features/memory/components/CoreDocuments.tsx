"use client";

import { Button } from "@heroui/button";
import { Divider } from "@heroui/divider";
import { Textarea } from "@heroui/input";
import { Skeleton } from "@heroui/skeleton";
import { Tab, Tabs } from "@heroui/tabs";
import { FileEmpty02Icon, PencilEdit02Icon } from "@icons";
import { formatDistanceToNow } from "date-fns";
import { useEffect, useState, useTransition } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { memoryApi } from "@/features/memory/api/memoryApi";
import type {
  MemoryDocType,
  MemoryDocument,
} from "@/features/memory/api/types";
import { MemoryEmptyState } from "@/features/memory/components/MemoryEmptyState";
import { CORE_DOCUMENTS } from "@/features/memory/constants";
import { toast } from "@/lib/toast";

export function CoreDocuments() {
  const [documents, setDocuments] = useState<MemoryDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedDocType, setSelectedDocType] =
    useState<MemoryDocType>("user_md");
  const [draft, setDraft] = useState<string | null>(null);
  const [isSaving, startSaving] = useTransition();

  useEffect(() => {
    let cancelled = false;
    const fetchDocuments = async () => {
      try {
        const response = await memoryApi.getDocuments();
        if (!cancelled) setDocuments(response.documents ?? []);
      } catch {
        if (!cancelled) setDocuments([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchDocuments();
    return () => {
      cancelled = true;
    };
  }, []);

  const meta = CORE_DOCUMENTS.find((doc) => doc.docType === selectedDocType);
  const document = documents.find((doc) => doc.doc_type === selectedDocType);

  const handleSave = () => {
    if (draft === null) return;
    const content = draft;

    startSaving(async () => {
      try {
        const updated = await memoryApi.updateDocument(
          selectedDocType,
          content,
        );
        setDocuments((previous) => {
          const rest = previous.filter(
            (doc) => doc.doc_type !== selectedDocType,
          );
          return [...rest, updated];
        });
        setDraft(null);
        toast.success("Document saved");
      } catch {
        toast.error("Failed to save document");
      }
    });
  };

  if (loading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-9 w-2/3 rounded-xl" />
        <Skeleton className="h-64 w-full rounded-2xl" />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Inner doc tabs — same variant/size as the main memory tabs */}
      <Tabs
        variant="solid"
        radius="full"
        selectedKey={selectedDocType}
        onSelectionChange={(key) => {
          setSelectedDocType(key as MemoryDocType);
          setDraft(null);
        }}
      >
        {CORE_DOCUMENTS.map((doc) => (
          <Tab key={doc.docType} title={doc.fileName} />
        ))}
      </Tabs>

      <div className="rounded-2xl bg-zinc-800 px-5 py-4">
        {/* Description row */}
        {meta?.description && (
          <p className="text-sm text-zinc-300">{meta.description}</p>
        )}

        {/* Meta row — version + updated timestamp, separated by divider */}
        {document && (
          <>
            <Divider className="my-3 bg-zinc-700/50" />
            <div className="flex items-center justify-between gap-3">
              <p className="flex items-center gap-1.5 text-xs text-zinc-500">
                <span>v{document.version}</span>
                <span className="size-0.5 rounded-full bg-zinc-600" />
                <span>
                  updated{" "}
                  {formatDistanceToNow(new Date(document.updated_at), {
                    addSuffix: true,
                  })}
                </span>
              </p>
              {draft === null && (
                <Button
                  size="sm"
                  variant="flat"
                  className="shrink-0 rounded-xl"
                  startContent={<PencilEdit02Icon className="size-4" />}
                  onPress={() => setDraft(document.content)}
                >
                  Edit
                </Button>
              )}
            </div>
          </>
        )}

        {/* No document yet — show edit button in description area */}
        {!document && draft === null && <div className="mt-3" />}

        <div className={document || draft !== null ? "mt-4" : "mt-2"}>
          {draft !== null ? (
            <div className="space-y-3">
              <Textarea
                value={draft}
                onValueChange={setDraft}
                minRows={12}
                maxRows={24}
                autoFocus
              />
              <div className="flex justify-end gap-2">
                <Button
                  size="sm"
                  variant="light"
                  className="rounded-xl"
                  onPress={() => setDraft(null)}
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  color="primary"
                  className="rounded-xl"
                  onPress={handleSave}
                  isLoading={isSaving}
                >
                  Save
                </Button>
              </div>
            </div>
          ) : document ? (
            <DocumentMarkdown content={document.content} />
          ) : (
            <MemoryEmptyState
              icon={FileEmpty02Icon}
              title="GAIA hasn't written this document yet"
              description="It fills in automatically as GAIA learns about you"
            />
          )}
        </div>
      </div>
    </div>
  );
}

function DocumentMarkdown({ content }: { content: string }) {
  return (
    <div className="text-sm leading-relaxed text-zinc-300">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => (
            <h1 className="mt-4 mb-2 text-base font-semibold text-white first:mt-0">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="mt-4 mb-2 text-sm font-semibold text-white first:mt-0">
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="mt-3 mb-1 text-sm font-medium text-white first:mt-0">
              {children}
            </h3>
          ),
          p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
          ul: ({ children }) => (
            <ul className="mb-2 list-disc space-y-1 pl-5">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="mb-2 list-decimal space-y-1 pl-5">{children}</ol>
          ),
          li: ({ children }) => <li>{children}</li>,
          strong: ({ children }) => (
            <strong className="font-semibold text-zinc-100">{children}</strong>
          ),
          code: ({ children }) => (
            <code className="rounded bg-zinc-900 px-1 py-0.5 font-mono text-xs">
              {children}
            </code>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
