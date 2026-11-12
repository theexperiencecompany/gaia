import type { SortDescriptor } from "@react-types/shared";
import { useMemo, useState } from "react";
import type { z } from "zod";
import type { ArtifactCell, dataTableSchema } from "../specs";

type TableProps = z.infer<typeof dataTableSchema>;

export interface TableCellValue {
  /** The column index as a string: a cell's identity is its column. */
  column: string;
  value: ArtifactCell;
}

export interface TableRow {
  key: string;
  cells: TableCellValue[];
  /** Index into the program's rows; -1 for the total row. */
  source: number;
  kind: "row" | "child" | "total";
  hasDetails: boolean;
}

const byColumn = (cells: ArtifactCell[]): TableCellValue[] =>
  cells.map((value, j) => ({ column: String(j), value }));

const asNumber = (cell: ArtifactCell): number =>
  typeof cell === "number"
    ? cell
    : Number(String(cell).replace(/[^0-9.-]/g, ""));

function detailsByRow(
  details: TableProps["details"],
): Record<string, ArtifactCell[][]> {
  if (!details) return {};
  if (Array.isArray(details)) {
    return Object.fromEntries(
      details.map((rows, i) => [String(i), rows ?? []]),
    );
  }
  return details;
}

/** Filtered, sorted rows with each open row's drill-down children under it, then the total. */
export function useTableRows(props: TableProps) {
  // the program's own row order until the reader sorts
  const [sort, setSort] = useState<SortDescriptor | undefined>(undefined);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<ReadonlySet<number>>(new Set());

  const details = useMemo(() => detailsByRow(props.details), [props.details]);

  const rows = useMemo(() => {
    const needle = query.toLowerCase();
    const matching = props.rows
      .map((cells, source) => ({ cells, source }))
      .filter(
        ({ cells }) =>
          !needle || cells.join(" ").toLowerCase().includes(needle),
      );
    if (sort) {
      const column = Number(sort.column);
      const numeric = props.numeric?.includes(column) ?? false;
      matching.sort((a, b) => {
        const x = a.cells[column];
        const y = b.cells[column];
        const order = numeric
          ? asNumber(x) - asNumber(y)
          : String(x ?? "").localeCompare(String(y ?? ""));
        return sort.direction === "ascending" ? order : -order;
      });
    }
    const flat: TableRow[] = matching.flatMap(({ cells, source }) => {
      const children = details[String(source)] ?? [];
      const row: TableRow = {
        key: `r${source}`,
        cells: byColumn(cells),
        source,
        kind: "row",
        hasDetails: children.length > 0,
      };
      if (!open.has(source)) return [row];
      return [
        row,
        ...children.map(
          (child, k): TableRow => ({
            key: `c${source}-${k}`,
            cells: byColumn(child),
            source,
            kind: "child",
            hasDetails: false,
          }),
        ),
      ];
    });
    if (props.total) {
      flat.push({
        key: "total",
        cells: byColumn(props.total),
        source: -1,
        kind: "total",
        hasDetails: false,
      });
    }
    return flat;
  }, [props.rows, props.numeric, props.total, details, sort, query, open]);

  const toggle = (source: number) =>
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(source)) next.delete(source);
      else next.add(source);
      return next;
    });

  return {
    rows,
    sort,
    setSort,
    query,
    setQuery,
    isOpen: (source: number) => open.has(source),
    toggle,
  };
}
