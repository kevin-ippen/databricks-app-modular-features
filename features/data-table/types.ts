import React from "react";

export interface ColumnDef<T = any> {
  /** Property key on the data row object. */
  key: string;
  /** Display label for the column header. */
  label: string;
  /** Enable sorting for this column (default: true when DataTable.sortable). */
  sortable?: boolean;
  /** Built-in format hint for cell values. */
  format?: "number" | "money" | "percent" | "string" | "date";
  /** Text alignment within the cell. */
  align?: "left" | "center" | "right";
  /** Column width (CSS value). */
  width?: string | number;
  /** Custom render function -- overrides built-in formatting. */
  render?: (value: any, row: T) => React.ReactNode;
}

export interface DataTableProps<T = Record<string, any>> {
  /** Column definitions. */
  columns: ColumnDef<T>[];
  /** Row data. */
  data: T[];
  /** Callback when a row is clicked. */
  onRowClick?: (row: T) => void;
  /** Message displayed when data is empty. */
  emptyMessage?: string;
  /** Default column key to sort by on mount. */
  defaultSortKey?: string;
  /** Default sort direction (default: "asc"). */
  defaultSortDir?: "asc" | "desc";
  /** Alternate row background shading. */
  striped?: boolean;
  /** Compact row padding. */
  compact?: boolean;
}
