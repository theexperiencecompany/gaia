"use client";

import { Table } from "@heroui/react";

export interface ComparisonColumn {
  key: string;
  label: string;
  /** Applied to the <Table.Column> header cell */
  headerClassName?: string;
  /** Applied to each <Table.Cell> in this column */
  cellClassName?: string;
}

interface Props {
  readonly columns: ComparisonColumn[];
  readonly rows: readonly { readonly [key: string]: string }[];
  readonly ariaLabel?: string;
}

export default function ComparisonTable({ columns, rows, ariaLabel }: Props) {
  return (
    <Table className="overflow-hidden rounded-3xl bg-zinc-800">
      <Table.Content
        aria-label={ariaLabel ?? "Feature comparison"}
        className="min-w-full"
      >
        <Table.Header className="[&>tr]:border-b [&>tr]:border-zinc-700">
          {columns.map((col) => (
            <Table.Column
              key={col.key}
              id={col.key}
              className={`bg-zinc-800 text-sm font-medium ${col.headerClassName ?? ""}`}
            >
              {col.label}
            </Table.Column>
          ))}
        </Table.Header>
        <Table.Body>
          {rows.map((row) => (
            <Table.Row
              key={row[columns[0]?.key ?? ""] ?? ""}
              id={row[columns[0]?.key ?? ""] ?? ""}
              className="border-b border-zinc-700/50 transition-colors hover:bg-white/[0.02]"
            >
              {columns.map((col) => (
                <Table.Cell
                  key={col.key}
                  className={`text-sm ${col.cellClassName ?? ""}`}
                >
                  {row[col.key] ?? ""}
                </Table.Cell>
              ))}
            </Table.Row>
          ))}
        </Table.Body>
      </Table.Content>
    </Table>
  );
}
