/**
 * The bordered card a run ends with: a headline, then labelled rows, the
 * primary row's URL emphasised. `gaia up` and `gaia uninstall` share it.
 * @module ui/components/ResultCard
 */

import { Box, Text } from "ink";
import type React from "react";
import type { SummaryRow } from "../../commands/up/summary.types.js";
import { wrapToWidth } from "../../lib/terminal-text.js";
import { BOX_BORDER, MARK } from "../constants.js";
import { useCardWidth } from "./use-card-width.js";

const ROW_LABEL_WIDTH = 16;
/** Columns the card's border (1 each side) and paddingX (2 each side) take. */
const CARD_FRAME_WIDTH = 6;

const ROW_COLOR: Record<NonNullable<SummaryRow["tone"]>, string | undefined> = {
  primary: undefined,
  warn: "yellow",
  dim: "gray",
};

/** A row's text wrapped to its column, with its URL bold, underlined and cyan. */
const RowText: React.FC<{ row: SummaryRow; width: number }> = ({
  row,
  width,
}) => {
  const color = row.tone ? ROW_COLOR[row.tone] : undefined;
  const text = wrapToWidth(row.text, width);
  if (!row.url) return <Text color={color}>{text}</Text>;
  const [before, after] = text.split(row.url);
  return (
    <Text color={color}>
      {before}
      <Text color="cyan" bold underline>
        {row.url}
      </Text>
      {after}
    </Text>
  );
};

export const ResultCard: React.FC<{
  headline: string;
  rows: readonly SummaryRow[];
  accent: string;
  success: boolean;
}> = ({ headline, rows, accent, success }) => {
  const width = useCardWidth();
  return (
    <Box
      flexDirection="column"
      borderStyle={BOX_BORDER}
      borderColor={accent}
      paddingX={2}
      paddingY={1}
      width={width}
    >
      <Text bold color={accent}>
        {success ? `${MARK.ok} ` : ""}
        {headline}
      </Text>
      <Box flexDirection="column" marginTop={1}>
        {rows.map((row) => (
          <Box key={row.label} marginBottom={row.tone === "primary" ? 1 : 0}>
            <Box width={ROW_LABEL_WIDTH} flexShrink={0}>
              <Text bold={row.tone === "primary"}>{row.label}</Text>
            </Box>
            <RowText
              row={row}
              width={width - CARD_FRAME_WIDTH - ROW_LABEL_WIDTH}
            />
          </Box>
        ))}
      </Box>
    </Box>
  );
};
