"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableColumn,
  TableHeader,
  TableRow,
} from "@heroui/table";
import { cn } from "@/lib/utils";

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
    <div className="overflow-hidden rounded-3xl bg-zinc-800">
      <Table
        aria-label={ariaLabel ?? "Feature comparison"}
        removeWrapper
        classNames={{
          table: "min-w-full",
          th: "text-sm font-medium",
          td: "text-sm",
        }}
      >
        <TableHeader>
          {columns.map((col) => (
            <TableColumn key={col.key} className="text-zinc-400">
              <span className={col.headerClassName}>{col.label}</span>
            </TableColumn>
          ))}
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row[columns[0]?.key ?? ""] ?? ""}>
              {columns.map((col) => (
                <TableCell key={col.key}>
                  {/* Marketing rows stay airy; TableCell itself takes no spacing overrides. */}
                  <span className={cn("block px-1 py-2", col.cellClassName)}>
                    {row[col.key] ?? ""}
                  </span>
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
