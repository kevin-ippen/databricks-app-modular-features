/**
 * Cell value formatting utilities for DataTable.
 *
 * Each formatter converts a raw value to a display string. The `formatCell`
 * function dispatches on the format hint from the column definition.
 */

export function formatCell(value: any, format?: string): string {
  if (value == null) return "\u2014"; // em-dash
  switch (format) {
    case "money":
      return `$${Number(value).toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}`;
    case "percent":
      return `${Number(value).toFixed(1)}%`;
    case "number":
      return Number(value).toLocaleString();
    case "date":
      return new Date(value).toLocaleDateString();
    default:
      return String(value);
  }
}
