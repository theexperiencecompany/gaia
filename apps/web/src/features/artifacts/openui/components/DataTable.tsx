import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableColumn,
  TableHeader,
  TableRow,
} from "@heroui/table";
import { ArrowDown01Icon, ArrowRight01Icon } from "@icons";
import { defineComponent } from "@openuidev/react-lang";
import type { z } from "zod";
import { TABLE_FILTER_MIN_ROWS } from "../constants";
import { GroundedText } from "../GroundedText";
import { type TableRow as Row, useTableRows } from "../hooks/useTableRows";
import { dataTableSchema, describeArtifactComponent } from "../specs";

const ROW_TONE: Record<Row["kind"], string> = {
  row: "",
  child: "text-default-500",
  total: "font-semibold",
};

interface FirstCellProps {
  row: Row;
  isOpen: boolean;
  onToggle: () => void;
}

function FirstCell({ row, isOpen, onToggle }: FirstCellProps) {
  const label = row.cells[0]?.value ?? "";
  if (row.kind === "child") return <span className="pl-6">{label}</span>;
  if (!row.hasDetails) return <>{label}</>;
  return (
    <Button
      size="sm"
      variant="light"
      className="-ml-2 h-auto min-w-0 gap-1 px-2 py-1 font-semibold"
      aria-expanded={isOpen}
      startContent={
        isOpen ? (
          <ArrowDown01Icon className="size-4" />
        ) : (
          <ArrowRight01Icon className="size-4" />
        )
      }
      onPress={onToggle}
    >
      {label}
    </Button>
  );
}

function DataTableView(props: z.infer<typeof dataTableSchema>) {
  const { rows, sort, setSort, query, setQuery, isOpen, toggle } =
    useTableRows(props);
  const numeric = (j: number) => props.numeric?.includes(j) ?? false;
  const headers = props.columns.map((label, j) => ({
    id: String(j),
    label,
    end: numeric(j),
  }));
  return (
    <div className="flex min-w-0 flex-col gap-3">
      {props.caption ? (
        <p className="font-semibold text-foreground">
          <GroundedText text={props.caption} />
        </p>
      ) : null}
      {props.rows.length > TABLE_FILTER_MIN_ROWS ? (
        <Input
          size="sm"
          aria-label="Filter rows"
          placeholder={`Filter ${props.rows.length} rows`}
          value={query}
          onValueChange={setQuery}
          className="max-w-xs"
        />
      ) : null}
      <Table
        aria-label={props.caption ?? "Table"}
        removeWrapper
        sortDescriptor={sort}
        onSortChange={setSort}
        classNames={{
          base: "max-w-full overflow-x-auto print:overflow-visible",
          table: "min-w-[36rem]",
          th: "first:sticky first:left-0 first:z-10",
          td: "first:sticky first:left-0 first:z-10 first:bg-background",
        }}
      >
        <TableHeader>
          {headers.map((header) => (
            <TableColumn
              key={header.id}
              allowsSorting
              align={header.end ? "end" : "start"}
            >
              {header.label}
            </TableColumn>
          ))}
        </TableHeader>
        <TableBody items={rows}>
          {(row) => (
            <TableRow key={row.key} className={ROW_TONE[row.kind]}>
              {row.cells.map((cell) => (
                <TableCell
                  key={cell.column}
                  className={
                    numeric(Number(cell.column))
                      ? "text-right tabular-nums"
                      : undefined
                  }
                >
                  {cell.column === "0" ? (
                    <FirstCell
                      row={row}
                      isOpen={isOpen(row.source)}
                      onToggle={() => toggle(row.source)}
                    />
                  ) : (
                    cell.value
                  )}
                </TableCell>
              ))}
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}

export const dataTableDef = defineComponent({
  name: "DataTable",
  description: describeArtifactComponent("DataTable"),
  props: dataTableSchema,
  component: ({ props }) => <DataTableView {...props} />,
});
