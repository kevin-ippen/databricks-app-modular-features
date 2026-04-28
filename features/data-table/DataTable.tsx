/**
 * Generic sortable data table component.
 *
 * Features:
 *  - Sortable column headers with unicode arrow indicators
 *  - Type-aware cell formatting (money, percent, number, date, string)
 *  - Optional custom render function per column
 *  - Row click handler
 *  - Empty state message
 *  - Striped / compact modes
 *  - Inline styles only (no external CSS dependencies)
 *
 * Peer dependencies: react (>=17)
 */

import React, { useState, useMemo, CSSProperties } from "react";
import type { ColumnDef, DataTableProps } from "./types";
import { formatCell } from "./formatters";

type SortDir = "asc" | "desc";

/* ------------------------------------------------------------------ */
/*  Inline style helpers                                              */
/* ------------------------------------------------------------------ */

const baseTableStyle: CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
  fontSize: "0.875rem",
  lineHeight: 1.5,
};

const headerCellBase: CSSProperties = {
  textAlign: "left",
  fontSize: "0.75rem",
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: "0.05em",
  color: "#6b7280",
  whiteSpace: "nowrap",
  borderBottom: "1px solid #e5e7eb",
  userSelect: "none",
};

const bodyCellBase: CSSProperties = {
  color: "#374151",
  whiteSpace: "nowrap",
  borderBottom: "1px solid #f3f4f6",
};

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function DataTable<T extends Record<string, any>>({
  columns,
  data,
  onRowClick,
  emptyMessage = "No data available.",
  defaultSortKey,
  defaultSortDir = "asc",
  striped = false,
  compact = false,
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(defaultSortKey ?? null);
  const [sortDir, setSortDir] = useState<SortDir>(defaultSortDir);

  /* Sorting logic --------------------------------------------------- */

  const handleSort = (key: string, isSortable?: boolean) => {
    if (isSortable === false) return;
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const sortedData = useMemo(() => {
    if (!sortKey) return data;
    return [...data].sort((a, b) => {
      const aVal = a[sortKey];
      const bVal = b[sortKey];
      if (aVal === bVal) return 0;
      if (aVal == null) return 1;
      if (bVal == null) return -1;
      const cmp = aVal < bVal ? -1 : 1;
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [data, sortKey, sortDir]);

  /* Sort indicator -------------------------------------------------- */

  const sortIndicator = (key: string): string => {
    if (sortKey !== key) return " \u2195"; // up-down arrow
    return sortDir === "asc" ? " \u2191" : " \u2193"; // up / down arrow
  };

  /* Padding helper -------------------------------------------------- */

  const cellPad = compact ? "0.35rem 0.5rem" : "0.6rem 1rem";

  /* Empty state ----------------------------------------------------- */

  if (data.length === 0) {
    return (
      <div
        style={{
          textAlign: "center",
          padding: "2rem 0",
          fontSize: "0.875rem",
          color: "#9ca3af",
        }}
      >
        {emptyMessage}
      </div>
    );
  }

  /* Render ---------------------------------------------------------- */

  return (
    <div style={{ overflowX: "auto" }}>
      <table style={baseTableStyle}>
        <thead>
          <tr>
            {columns.map((col) => {
              const isSortable = col.sortable !== false;
              return (
                <th
                  key={col.key}
                  onClick={() => handleSort(col.key, col.sortable)}
                  style={{
                    ...headerCellBase,
                    padding: cellPad,
                    textAlign: col.align ?? "left",
                    width: col.width,
                    cursor: isSortable ? "pointer" : "default",
                  }}
                >
                  {col.label}
                  {isSortable && (
                    <span style={{ opacity: sortKey === col.key ? 1 : 0.35 }}>
                      {sortIndicator(col.key)}
                    </span>
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sortedData.map((row, rowIdx) => (
            <tr
              key={rowIdx}
              onClick={() => onRowClick?.(row)}
              style={{
                cursor: onRowClick ? "pointer" : "default",
                backgroundColor:
                  striped && rowIdx % 2 === 1
                    ? "rgba(249, 250, 251, 1)"
                    : "transparent",
                transition: "background-color 0.1s",
              }}
              onMouseEnter={(e) => {
                if (onRowClick) {
                  (e.currentTarget as HTMLElement).style.backgroundColor =
                    "#f9fafb";
                }
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLElement).style.backgroundColor =
                  striped && rowIdx % 2 === 1
                    ? "rgba(249, 250, 251, 1)"
                    : "transparent";
              }}
            >
              {columns.map((col) => {
                const raw = row[col.key];
                const content = col.render
                  ? col.render(raw, row)
                  : formatCell(raw, col.format);

                return (
                  <td
                    key={col.key}
                    style={{
                      ...bodyCellBase,
                      padding: cellPad,
                      textAlign: col.align ?? "left",
                    }}
                  >
                    {content}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default DataTable;
