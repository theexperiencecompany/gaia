"use client";

import type { ReactNode } from "react";
import { useState } from "react";

import RightSidebarSlot, {
  RightSidebarSlotProvider,
} from "@/components/layout/sidebar/RightSidebarSlot";
import { BASE_MESSAGE_SCHEMA } from "@/config/registries/baseMessageRegistry";
import FileArtifactSection from "@/features/chat/components/bubbles/bot/FileArtifactSection";
import ChatBubbleUser from "@/features/chat/components/bubbles/user/ChatBubbleUser";
import { FileCard } from "@/features/chat/components/files/FileCard";
import FilePreview, {
  type UploadedFilePreview,
} from "@/features/chat/components/files/FilePreview";
import { FileTypeIcon } from "@/features/chat/components/files/FileTypeIcon";
import { FILE_TYPE_STYLES } from "@/features/chat/components/files/fileTypeConfig";
import type { ArtifactData } from "@/types/features/toolDataTypes";
import type { AttachedFileData } from "@/types/shared/fileTypes";

const SESSION_ID = "dev-files-showcase";
const LONG_NAME =
  "q3-board-meeting-notes-final-final-v7-with-appendix-and-financials.md";
const SAMPLE_IMAGE = "/images/screenshot.webp";
const SAMPLE_MARKDOWN_URL = `data:text/markdown;charset=utf-8,${encodeURIComponent(
  "# Launch plan\n\n- Ship the file cards\n- Fold the brief\n- Celebrate",
)}`;
const SAMPLE_CSV_URL = `data:text/csv;charset=utf-8,${encodeURIComponent(
  "name,plan\nAda,pro\nGrace,free",
)}`;

const COMPOSER_FILES: UploadedFilePreview[] = [
  {
    id: "c1",
    url: SAMPLE_MARKDOWN_URL,
    name: "launch-plan.md",
    type: "text/markdown",
    size: 4_812,
  },
  {
    id: "c2",
    url: SAMPLE_IMAGE,
    name: "screenshot.webp",
    type: "image/webp",
    size: 284_311,
  },
  {
    id: "c3",
    url: "",
    name: "annual-report.pdf",
    type: "application/pdf",
    size: 2_516_582,
    isUploading: true,
  },
  {
    id: "c4",
    url: SAMPLE_MARKDOWN_URL,
    name: LONG_NAME,
    type: "text/markdown",
    size: 18_204,
  },
];

const USER_FILES: AttachedFileData[] = [
  {
    fileId: "u1",
    url: SAMPLE_CSV_URL,
    filename: "customers.csv",
    type: "text/csv",
    size: 18_422,
  },
  {
    fileId: "u2",
    url: "",
    filename: "contract.pdf",
    type: "application/pdf",
    size: 382_104,
  },
  {
    fileId: "u3",
    url: SAMPLE_MARKDOWN_URL,
    filename: LONG_NAME,
    type: "text/markdown",
    size: 18_204,
  },
];

const USER_IMAGE: AttachedFileData[] = [
  {
    fileId: "u4",
    url: SAMPLE_IMAGE,
    filename: "screenshot.webp",
    type: "image/webp",
  },
];

function artifact(
  path: string,
  sizeBytes: number,
  body?: string,
  contentType?: string,
): ArtifactData {
  return {
    session_id: SESSION_ID,
    event: "upsert",
    path,
    size_bytes: sizeBytes,
    body,
    content_type: contentType,
  };
}

const GENERATED_FILES: ArtifactData[] = [
  artifact("weekly-summary.md", 3_204, "# Weekly summary\n\nAll green."),
  artifact("landing.html", 12_480, "<h1>Hello</h1>", "text/html"),
  artifact("report.pdf", 482_104),
  artifact("revenue.csv", 18_422, "month,revenue\nJan,120\nFeb,140"),
  artifact("chart.png", 96_220),
  artifact("cleanup.py", 2_048, "print('hello')"),
  artifact("schema.ts", 1_312, "export type A = 1;"),
  artifact(`notes/${LONG_NAME}`, 18_204, "# Notes"),
];

function Section({
  title,
  note,
  children,
}: {
  title: string;
  note: string;
  children: ReactNode;
}) {
  return (
    <section className="mb-14">
      <h2 className="text-sm font-semibold text-zinc-200">{title}</h2>
      <p className="mt-1 mb-5 max-w-2xl text-xs text-zinc-500">{note}</p>
      {children}
    </section>
  );
}

export default function FilesShowcasePage() {
  const [composerFiles, setComposerFiles] = useState(COMPOSER_FILES);

  return (
    <RightSidebarSlotProvider>
      <div className="relative flex h-screen w-full bg-primary-bg dark">
        <main className="min-w-0 flex-1 overflow-y-auto px-10 py-12 text-zinc-100">
          <header className="mb-12 max-w-3xl">
            <h1 className="text-2xl font-semibold tracking-tight text-white">
              Files and attachments
            </h1>
            <p className="mt-2 text-sm text-zinc-400">
              Every surface renders the same FileCard: composer uploads, the
              user&apos;s sent attachments, and the files GAIA writes.
            </p>
          </header>

          <Section
            title="Composer upload"
            note="The real composer FilePreview: thumbnail for images, spinner while uploading. Hover swaps the size for a click-to-open hint and shows remove; click opens the file viewer."
          >
            <div className="max-w-2xl rounded-3xl bg-zinc-800 p-1">
              <FilePreview
                files={composerFiles}
                onRemove={(id) =>
                  setComposerFiles((prev) =>
                    prev.filter((file) => file.id !== id),
                  )
                }
              />
            </div>
          </Section>

          <Section
            title="User message attachments"
            note="The real ChatBubbleUser: files sit on the user's side above the bubble and open in the viewer; images show inline."
          >
            <div className="flex max-w-3xl flex-col gap-6">
              <ChatBubbleUser
                {...BASE_MESSAGE_SCHEMA}
                message_id="dev-user-files"
                text="Can you clean these up and summarise?"
                fileData={USER_FILES}
                disableActions
              />
              <ChatBubbleUser
                {...BASE_MESSAGE_SCHEMA}
                message_id="dev-user-image"
                text="What is in this screenshot?"
                fileData={USER_IMAGE}
                disableActions
              />
            </div>
          </Section>

          <Section
            title="GAIA-generated files and artifacts"
            note="The real artifact_data renderer. Click opens the file viewer; share and download appear on hover."
          >
            <div className="max-w-3xl">
              <FileArtifactSection artifact_data={GENERATED_FILES} />
            </div>
          </Section>

          <Section
            title="Every type"
            note="One card per extension FileTypeIcon knows, so a missing style is obvious."
          >
            <div className="flex max-w-5xl flex-wrap gap-2">
              {Object.keys(FILE_TYPE_STYLES).map((extension) => (
                <FileCard
                  key={extension}
                  name={`example.${extension}`}
                  sizeBytes={24_576}
                />
              ))}
            </div>
          </Section>

          <Section title="Icon set" note="FileTypeIcon at full size.">
            <div className="flex flex-wrap gap-8">
              {Object.keys(FILE_TYPE_STYLES).map((extension) => (
                <FileTypeIcon key={extension} extension={extension} size={72} />
              ))}
            </div>
          </Section>
        </main>
        <RightSidebarSlot />
      </div>
    </RightSidebarSlotProvider>
  );
}
