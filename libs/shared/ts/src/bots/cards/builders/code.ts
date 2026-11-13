import type { CodeData } from "../../../chat/types";
import { truncateText } from "../../../utils/formatters";
import type { Card, CardBlock } from "../types";
import { chartBlocks } from "./chart";

const RAN_TITLE = "Code run";
const FAILED_TITLE = "Code failed";
const ERROR_HEADING = "Error";
const OUTPUT_HEADING = "Output";
/** Enough to read; a chat message has a size limit and the full run is in GAIA. */
const CODE_MAX = 2000;
const OUTPUT_MAX = 1500;
const ERROR_MAX = 600;

/** What the run printed and returned, in the order the web card shows it. */
function outputText(data: CodeData): string {
  const output = data.output;
  return [output?.stdout, ...(output?.results ?? []), output?.stderr]
    .map((part) => part?.trim())
    .filter((part): part is string => Boolean(part))
    .join("\n");
}

/** The code that ran, what it printed, the error if it failed, and any chart it drew. */
export function buildCodeCards(data: CodeData): Card[] {
  const code = data.code?.trim();
  const output = outputText(data);
  const error = (data.error ?? data.output?.error)?.trim();
  const blocks: CardBlock[] = [];
  if (code) {
    blocks.push({
      kind: "code",
      code: truncateText(code, CODE_MAX),
      language: data.language,
    });
  }
  if (output) {
    blocks.push(
      { kind: "text", markdown: `**${OUTPUT_HEADING}**` },
      { kind: "code", code: truncateText(output, OUTPUT_MAX) },
    );
  }
  if (error) {
    blocks.push(
      { kind: "text", markdown: `**${ERROR_HEADING}**` },
      { kind: "code", code: truncateText(error, ERROR_MAX) },
    );
  }
  blocks.push(...(data.charts ?? []).flatMap(chartBlocks));
  if (blocks.length === 0) return [];
  const failed = Boolean(error) || data.status === "error";
  return [
    {
      title: failed ? FAILED_TITLE : RAN_TITLE,
      accent: failed ? "warning" : "brand",
      blocks,
      actions: [],
    },
  ];
}

/** Only a finished run is posted; the executing frame has no output yet. */
export function isCodePosted(data: CodeData): boolean {
  return data.status !== "executing";
}
