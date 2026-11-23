import {
  dataTableSchema,
  describeArtifactComponent,
} from "@gaia/artifacts/specs";
import { Input, Table, TextField } from "@heroui/react";
import { ArrowDown01Icon, ArrowRight01Icon } from "@icons";
import { defineComponent } from "@openuidev/react-lang";
import type { z } from "zod";
import {
  inputVariants,
  tableVariants,
} from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { TABLE_FILTER_MIN_ROWS } from "../constants";
import { GroundedText } from "../GroundedText";
import { type TableRow as Row, useTableRows } from "../hooks/useTableRows";

const ROW_TONE: Record<Row["kind"], string> = {
  row: "",
  child: "text-muted",
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
    <GaiaButton
      size="sm"
      variant="ghost"
      inset="tight"
      className="-ml-2 h-auto min-w-0 gap-1 font-semibold"
      aria-expanded={isOpen}
      onPress={onToggle}
    >
      {isOpen ? (
        <ArrowDown01Icon className="size-4" />
      ) : (
        <ArrowRight01Icon className="size-4" />
      )}
      {label}
    </GaiaButton>
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
        <TextField
          aria-label="Filter rows"
          value={query}
          onChange={setQuery}
          className={inputVariants({ size: "sm", className: "max-w-xs" })}
        >
          <Input placeholder={`Filter ${props.rows.length} rows`} />
        </TextField>
      ) : null}
      <Table
        className={tableVariants({ surface: "plain", stickyFirstColumn: true })}
      >
        <Table.ScrollContainer className="max-w-full overflow-x-auto print:overflow-visible">
          <Table.Content
            aria-label={props.caption ?? "Table"}
            sortDescriptor={sort}
            onSortChange={setSort}
            className="min-w-[36rem]"
          >
            <Table.Header columns={headers}>
              {(header) => (
                <Table.Column
                  id={header.id}
                  allowsSorting
                  isRowHeader={header.id === "0"}
                  className={header.end ? "text-right" : undefined}
                >
                  {({ sortDirection }) => (
                    <Table.SortableColumnHeader sortDirection={sortDirection}>
                      {header.label}
                    </Table.SortableColumnHeader>
                  )}
                </Table.Column>
              )}
            </Table.Header>
            <Table.Body items={rows}>
              {(row) => (
                <Table.Row id={row.key} className={ROW_TONE[row.kind]}>
                  {row.cells.map((cell) => (
                    <Table.Cell
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
                    </Table.Cell>
                  ))}
                </Table.Row>
              )}
            </Table.Body>
          </Table.Content>
        </Table.ScrollContainer>
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
