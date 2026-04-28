/**
 * Type definitions for the Vega-Lite spec compiler.
 *
 * Defines VizState, ResultEnvelope, ColumnMeta, and related types
 * needed by compileVegaLiteSpec.
 */

// ── Column metadata ──────────────────────────────────────────────────────────

export interface ColumnMeta {
  /** Column name as returned by the SQL query */
  name: string;
  /** Semantic type: "number" | "date" | "datetime" | "string" | "boolean" */
  type: string;
  /** Optional display label (falls back to name) */
  label?: string;
}

// ── Filters & transforms ─────────────────────────────────────────────────────

export type FilterOp =
  | "eq" | "neq"
  | "gt" | "gte" | "lt" | "lte"
  | "in" | "nin"
  | "contains" | "startswith" | "endswith";

export interface VizFilter {
  col: string;
  op: FilterOp;
  value: any;
}

export interface TimeGrain {
  col: string;
  grain: "hour" | "day" | "week" | "month" | "quarter" | "year";
}

export interface SortSpec {
  col: string;
  dir: "asc" | "desc";
}

export interface Transforms {
  filters: VizFilter[];
  sort: SortSpec | null;
  limit: number | null;
  timeGrain: TimeGrain | null;
}

// ── Encodings ────────────────────────────────────────────────────────────────

export interface Encodings {
  x: string | null;
  y: string | string[] | null;
  series: string | null;
}

// ── View options ─────────────────────────────────────────────────────────────

export interface ViewOptions {
  title?: string;
  subtitle?: string;
}

// ── Chart types ──────────────────────────────────────────────────────────────

export type ChartType =
  | "bar"
  | "line"
  | "area"
  | "pie"
  | "scatter"
  | "stacked_bar"
  | "heatmap"
  | "bump"
  | "boxplot"
  | "facet_bar"
  | "facet_line";

// ── VizState ─────────────────────────────────────────────────────────────────

export interface VizState {
  chartType: ChartType;
  encodings: Encodings;
  transforms: Transforms;
  view: ViewOptions;
}

// ── Result envelope ──────────────────────────────────────────────────────────

export interface ResultData {
  columns: ColumnMeta[];
  rows: any[][];
}

export interface ResultEnvelope {
  data: ResultData;
  /** Optional SQL that produced this result */
  sql?: string;
  /** Optional execution time in ms */
  executionTimeMs?: number;
}
