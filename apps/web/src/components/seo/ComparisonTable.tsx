"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableColumn,
  TableHeader,
  TableRow,
} from "@heroui/table";

export interface ComparisonColumn {
  key: string;
  label: string;
  /** Applied to the <TableColumn> header cell */
  headerClassName?: string;
  /** Applied to each <TableCell> in this column */
  cellClassName?: string;
}

interface Props {
  readonly columns: ComparisonColumn[];
  readonly rows: readonly { readonly [key: string]: string }[];
  readonly ariaLabel?: string;
}

export default function ComparisonTable({ columns, rows, ariaLabel }: Props) {
  return (
    <Table
      aria-label={ariaLabel ?? "Feature comparison"}
      removeWrapper
      classNames={{
        base: "overflow-hidden rounded-3xl bg-zinc-800",
        table: "min-w-full",
        thead: "[&>tr]:border-b [&>tr]:border-zinc-700",
        th: "bg-zinc-800 text-sm font-medium",
        tr: "border-b border-zinc-700/50 transition-colors hover:bg-white/[0.02]",
        td: "text-sm px-4 py-4",
      }}
    >
      <TableHeader>
        {columns.map((col) => (
          <TableColumn
            key={col.key}
            className={col.headerClassName ?? "text-zinc-400"}
          >
            {col.label}
          </TableColumn>
        ))}
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row[columns[0]?.key ?? ""] ?? ""}>
            {columns.map((col) => (
              <TableCell key={col.key} className={col.cellClassName}>
                {row[col.key] ?? ""}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
