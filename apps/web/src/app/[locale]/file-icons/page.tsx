"use client";

import { useState } from "react";

import FilePreview, {
  type UploadedFilePreview,
} from "@/features/chat/components/files/FilePreview";
import { FileTypeIcon } from "@/features/chat/components/files/FileTypeIcon";

interface FileTypeMeta {
  ext: string;
  name: string;
  mime: string;
}

const FILE_TYPES: readonly FileTypeMeta[] = [
  { ext: "pdf", name: "PDF", mime: "application/pdf" },
  { ext: "docx", name: "Word", mime: "wordprocessingml.document" },
  { ext: "doc", name: "Word legacy", mime: "application/msword" },
  { ext: "rtf", name: "Rich text", mime: "text/rtf" },
  { ext: "xlsx", name: "Excel", mime: "spreadsheetml.sheet" },
  { ext: "csv", name: "Spreadsheet", mime: "text/csv" },
  { ext: "pptx", name: "PowerPoint", mime: "presentationml.presentation" },
  { ext: "txt", name: "Plain text", mime: "text/plain" },
  { ext: "md", name: "Markdown", mime: "text/markdown" },
  { ext: "json", name: "JSON", mime: "application/json" },
  { ext: "epub", name: "E-book", mime: "application/epub+zip" },
  { ext: "odt", name: "OpenDocument text", mime: "opendocument.text" },
  { ext: "ods", name: "OpenDocument sheet", mime: "opendocument.spreadsheet" },
  { ext: "odp", name: "OpenDocument show", mime: "opendocument.presentation" },
  { ext: "png", name: "Image", mime: "image/png" },
  { ext: "jpg", name: "Image", mime: "image/jpeg" },
  { ext: "gif", name: "Image", mime: "image/gif" },
  { ext: "webp", name: "Image", mime: "image/webp" },
  { ext: "bmp", name: "Image", mime: "image/bmp" },
];

const SAMPLE_FILES: UploadedFilePreview[] = [
  {
    id: "1",
    url: "",
    name: "annual-report.pdf",
    type: "application/pdf",
    size: 2_516_582,
  },
  {
    id: "2",
    url: "",
    name: "quarterly-sales.xlsx",
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    size: 88_064,
  },
  {
    id: "3",
    url: "",
    name: "strategy-deck.pptx",
    type: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    size: 3_250_432,
  },
  {
    id: "4",
    url: "",
    name: "research-notes.md",
    type: "text/markdown",
    size: 12_288,
  },
  {
    id: "5",
    url: "",
    name: "config.json",
    type: "application/json",
    size: 4_096,
  },
  {
    id: "6",
    url: "",
    name: "resume.doc",
    type: "application/msword",
    size: 65_536,
  },
  {
    id: "7",
    url: "",
    name: "invoice.docx",
    type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    size: 38_912,
  },
  { id: "8", url: "", name: "readme.txt", type: "text/plain", size: 6_144 },
  {
    id: "9",
    url: "",
    name: "data-export.csv",
    type: "text/csv",
    size: 1_572_864,
  },
  { id: "10", url: "", name: "notes.rtf", type: "text/rtf", size: 22_528 },
  {
    id: "11",
    url: "",
    name: "ebook.epub",
    type: "application/epub+zip",
    size: 860_160,
  },
  {
    id: "12",
    url: "",
    name: "report.odt",
    type: "application/vnd.oasis.opendocument.text",
    size: 112_640,
  },
  {
    id: "13",
    url: "",
    name: "budget.ods",
    type: "application/vnd.oasis.opendocument.spreadsheet",
    size: 59_392,
  },
  {
    id: "14",
    url: "",
    name: "pitch.odp",
    type: "application/vnd.oasis.opendocument.presentation",
    size: 1_992_294,
  },
];

export default function FileIconsPrototypePage() {
  const [files, setFiles] = useState(SAMPLE_FILES);

  const removeFile = (id: string) =>
    setFiles((prev) => prev.filter((file) => file.id !== id));

  return (
    <main className="min-h-screen bg-zinc-900 px-10 py-12 text-zinc-100">
      <header className="mb-12 max-w-3xl">
        <p className="mb-2 text-xs font-medium tracking-widest text-primary uppercase">
          Dev prototype
        </p>
        <h1 className="mb-2 text-3xl font-semibold tracking-tight text-white">
          Composer file icons
        </h1>
        <p className="text-sm leading-relaxed text-zinc-400">
          macOS-style file icons for every upload-allowed format. The chips
          below are the real composer component — stacked gradient documents
          with a clean gaia-icon glyph, resolved from the backend allowlist.
        </p>
      </header>

      <section className="mb-14">
        <h2 className="mb-5 text-sm font-semibold tracking-wide text-zinc-300">
          Full icon set
        </h2>
        <div className="flex flex-wrap gap-x-8 gap-y-9">
          {FILE_TYPES.map((fileType) => (
            <div
              key={fileType.ext}
              className="flex w-32 flex-col items-center gap-3"
            >
              <FileTypeIcon extension={fileType.ext} size={96} />
              <div className="flex flex-col items-center gap-1">
                <span className="text-base font-semibold text-white">
                  {fileType.ext.toUpperCase()}
                </span>
                <span className="text-sm text-zinc-400">{fileType.mime}</span>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-5 text-sm font-semibold tracking-wide text-zinc-300">
          In the composer file selection
        </h2>
        <div className="rounded-2xl border border-zinc-700/60 bg-zinc-800/60 p-4">
          <FilePreview files={files} onRemove={removeFile} />
        </div>
        <p className="mt-3 text-xs text-zinc-500">
          The real composer FilePreview component — icons resolve from MIME via
          the backend allowlist, size label is readable, and chips are
          removable.
        </p>
      </section>
    </main>
  );
}
