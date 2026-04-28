/**
 * Vega-Lite Spec Compiler
 *
 * Compiles a VizState + ResultEnvelope into a Vega-Lite specification.
 * Auto-tunes visualization based on data characteristics.
 *
 * Supports 11 chart types: bar, line, area, pie, scatter, stacked_bar,
 * heatmap, bump, boxplot, facet_bar, facet_line.
 */

import { TopLevelSpec } from "vega-lite";
import {
  VizState,
  ResultEnvelope,
  VizFilter,
  ColumnMeta,
} from "./types";

// =============================================================================
// Constants
// =============================================================================

const MODERN_COLORS = [
  "#6366f1", "#22c55e", "#f59e0b", "#ec4899", "#06b6d4",
  "#8b5cf6", "#f97316", "#14b8a6", "#ef4444", "#84cc16",
];

const PRIMARY_COLOR = "#6366f1";

const BASE_CONFIG = {
  background: "transparent",
  font: "Inter, system-ui, sans-serif",
  padding: { left: 16, right: 16, top: 16, bottom: 16 },
  view: { stroke: "transparent" },
  title: {
    fontSize: 14,
    fontWeight: 600,
    color: "#f1f5f9",
    subtitleFontSize: 12,
    subtitleColor: "#94a3b8",
    anchor: "start",
    offset: 16,
  },
};

// =============================================================================
// Data Transformation
// =============================================================================

export function applyClientSideTransforms(
  rows: any[][],
  columns: ColumnMeta[],
  transforms: VizState["transforms"]
): Record<string, any>[] {
  let data = rows.map((row) => {
    const obj: Record<string, any> = {};
    columns.forEach((col, i) => {
      obj[col.name] = row[i];
    });
    return obj;
  });

  if (transforms.filters.length > 0) {
    data = data.filter((row) =>
      transforms.filters.every((filter) => applyFilter(row, filter))
    );
  }

  if (transforms.sort) {
    const { col, dir } = transforms.sort;
    data.sort((a, b) => {
      const aVal = a[col];
      const bVal = b[col];
      if (aVal === bVal) return 0;
      if (aVal == null) return 1;
      if (bVal == null) return -1;
      return dir === "asc" ? (aVal < bVal ? -1 : 1) : (aVal > bVal ? -1 : 1);
    });
  }

  if (transforms.limit && transforms.limit > 0) {
    data = data.slice(0, transforms.limit);
  }

  return data;
}

function applyFilter(row: Record<string, any>, filter: VizFilter): boolean {
  const value = row[filter.col];
  switch (filter.op) {
    case "eq": return value === filter.value;
    case "neq": return value !== filter.value;
    case "gt": return value > filter.value;
    case "gte": return value >= filter.value;
    case "lt": return value < filter.value;
    case "lte": return value <= filter.value;
    case "in": return Array.isArray(filter.value) && filter.value.includes(value);
    case "nin": return Array.isArray(filter.value) && !filter.value.includes(value);
    case "contains": return String(value).toLowerCase().includes(String(filter.value).toLowerCase());
    case "startswith": return String(value).toLowerCase().startsWith(String(filter.value).toLowerCase());
    case "endswith": return String(value).toLowerCase().endsWith(String(filter.value).toLowerCase());
    default: return true;
  }
}

// =============================================================================
// Helpers
// =============================================================================

function formatFieldName(field: string): string {
  return field.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function getVegaType(colType: string | undefined): string {
  switch (colType) {
    case "number": return "quantitative";
    case "date":
    case "datetime": return "temporal";
    default: return "nominal";
  }
}

function getTimeUnit(grain: string | undefined): string | undefined {
  const map: Record<string, string> = {
    hour: "yearmonthdatehours",
    day: "yearmonthdate",
    week: "yearweek",
    month: "yearmonth",
    quarter: "yearquarter",
    year: "year",
  };
  return grain ? map[grain] : undefined;
}

// =============================================================================
// Main Compiler
// =============================================================================

export function compileVegaLiteSpec(
  envelope: ResultEnvelope,
  vizState: VizState
): TopLevelSpec {
  const { data } = envelope;
  const hasSeries = !!vizState.encodings.series;

  // Transform data
  const transformedData = applyClientSideTransforms(
    data.rows,
    data.columns,
    vizState.transforms
  );

  // Get field info
  const xField = vizState.encodings.x;
  const yField = Array.isArray(vizState.encodings.y) ? vizState.encodings.y[0] : vizState.encodings.y;
  const seriesField = vizState.encodings.series;

  // Get column types
  const colTypeMap = new Map<string, string>(data.columns.map((c: ColumnMeta) => [c.name, c.type]));
  const xType = xField ? colTypeMap.get(xField) : undefined;

  // Analyze data for auto-tuning
  let maxLabelLength = 0;
  let uniqueXCount = 0;
  if (xField && transformedData.length > 0) {
    const xValues = new Set<string>();
    transformedData.forEach((row) => {
      const val = String(row[xField] ?? "");
      xValues.add(val);
      if (val.length > maxLabelLength) maxLabelLength = val.length;
    });
    uniqueXCount = xValues.size;
  }

  // Count series values
  let seriesCount = 0;
  if (seriesField) {
    const seriesValues = new Set<string>();
    transformedData.forEach((row) => seriesValues.add(String(row[seriesField] ?? "")));
    seriesCount = seriesValues.size;
  }

  // Determine label angle
  const labelAngle = (maxLabelLength > 10 || uniqueXCount > 6) ? -45 : 0;

  // Show data labels only for simple charts
  const showDataLabels = transformedData.length <= 12 && !hasSeries;

  // Guard: if we don't have required fields, return a fallback message spec
  if (!xField && !yField) {
    return {
      $schema: "https://vega.github.io/schema/vega-lite/v5.json",
      data: { values: [{ message: "No data fields available" }] },
      mark: { type: "text", fontSize: 14, color: "#94a3b8" },
      encoding: {
        text: { field: "message", type: "nominal" },
      },
      width: "container",
      height: 200,
      config: BASE_CONFIG,
    } as TopLevelSpec;
  }

  // Ensure we have valid field names (use first available column as fallback)
  const safeXField = xField || data.columns[0]?.name || "x";
  const safeYField = yField || data.columns.find((c: ColumnMeta) => c.type === "number")?.name || data.columns[1]?.name || "y";

  // === Build Spec Based on Chart Type ===

  // BAR CHART
  if (vizState.chartType === "bar") {
    const encoding: any = {
      x: {
        field: safeXField,
        type: getVegaType(xType),
        axis: {
          title: formatFieldName(safeXField),
          labelAngle,
          labelLimit: 120,
          labelFontSize: 11,
          labelColor: "#94a3b8",
          titleColor: "#e2e8f0",
          titleFontSize: 12,
          titleFontWeight: 600,
          gridOpacity: 0,
          domainColor: "#475569",
        },
      },
      y: {
        field: safeYField,
        type: "quantitative",
        axis: {
          title: formatFieldName(safeYField),
          format: "~s",
          labelFontSize: 11,
          labelColor: "#94a3b8",
          titleColor: "#e2e8f0",
          titleFontSize: 12,
          titleFontWeight: 600,
          gridColor: "#334155",
          gridOpacity: 0.5,
        },
      },
      color: hasSeries
        ? { field: seriesField, type: "nominal", scale: { range: MODERN_COLORS }, legend: { title: formatFieldName(seriesField || ""), orient: "bottom", labelColor: "#94a3b8", titleColor: "#e2e8f0" } }
        : { value: PRIMARY_COLOR },
      tooltip: [
        { field: safeXField, type: getVegaType(xType), title: formatFieldName(safeXField) },
        { field: safeYField, type: "quantitative", title: formatFieldName(safeYField), format: ",.0f" },
        ...(seriesField ? [{ field: seriesField, type: "nominal", title: formatFieldName(seriesField) }] : []),
      ],
    };

    if (showDataLabels) {
      return {
        $schema: "https://vega.github.io/schema/vega-lite/v5.json",
        data: { values: transformedData },
        width: "container",
        height: 280,
        autosize: { type: "fit", contains: "padding" },
        config: BASE_CONFIG,
        title: vizState.view.title ? { text: vizState.view.title, subtitle: vizState.view.subtitle } : undefined,
        layer: [
          { mark: { type: "bar", cornerRadiusTopLeft: 4, cornerRadiusTopRight: 4 }, encoding },
          {
            mark: { type: "text", align: "center", baseline: "bottom", dy: -6, fontSize: 11, fontWeight: 500, color: "#e2e8f0" },
            encoding: { x: encoding.x, y: encoding.y, text: { field: safeYField, type: "quantitative", format: ".3~s" } },
          },
        ],
      } as TopLevelSpec;
    }

    return {
      $schema: "https://vega.github.io/schema/vega-lite/v5.json",
      data: { values: transformedData },
      mark: { type: "bar", cornerRadiusTopLeft: 4, cornerRadiusTopRight: 4 },
      encoding,
      width: "container",
      height: 280,
      autosize: { type: "fit", contains: "padding" },
      config: BASE_CONFIG,
      title: vizState.view.title ? { text: vizState.view.title, subtitle: vizState.view.subtitle } : undefined,
    } as TopLevelSpec;
  }

  // LINE CHART
  if (vizState.chartType === "line") {
    return {
      $schema: "https://vega.github.io/schema/vega-lite/v5.json",
      data: { values: transformedData },
      mark: { type: "line", point: { filled: true, size: 60 }, strokeWidth: 2.5, interpolate: "monotone" },
      encoding: {
        x: {
          field: safeXField,
          type: getVegaType(xType),
          axis: { title: formatFieldName(safeXField), labelAngle, labelFontSize: 11, labelColor: "#94a3b8", titleColor: "#e2e8f0", gridOpacity: 0 },
          ...(vizState.transforms.timeGrain?.grain ? { timeUnit: getTimeUnit(vizState.transforms.timeGrain.grain) } : {}),
        },
        y: {
          field: safeYField,
          type: "quantitative",
          axis: { title: formatFieldName(safeYField), format: "~s", labelColor: "#94a3b8", titleColor: "#e2e8f0", gridColor: "#334155", gridOpacity: 0.5 },
        },
        color: hasSeries
          ? { field: seriesField, type: "nominal", scale: { range: MODERN_COLORS }, legend: { title: formatFieldName(seriesField || ""), orient: seriesCount > 5 ? "right" : "bottom", labelColor: "#94a3b8", titleColor: "#e2e8f0" } }
          : { value: PRIMARY_COLOR },
        tooltip: [
          { field: safeXField, type: getVegaType(xType), title: formatFieldName(safeXField) },
          { field: safeYField, type: "quantitative", title: formatFieldName(safeYField), format: ",.0f" },
          ...(seriesField ? [{ field: seriesField, type: "nominal", title: formatFieldName(seriesField) }] : []),
        ],
      },
      width: "container",
      height: 280,
      autosize: { type: "fit", contains: "padding" },
      config: BASE_CONFIG,
      title: vizState.view.title ? { text: vizState.view.title, subtitle: vizState.view.subtitle } : undefined,
    } as TopLevelSpec;
  }

  // AREA CHART
  if (vizState.chartType === "area") {
    return {
      $schema: "https://vega.github.io/schema/vega-lite/v5.json",
      data: { values: transformedData },
      mark: { type: "area", line: { strokeWidth: 2 }, opacity: 0.5, interpolate: "monotone" },
      encoding: {
        x: {
          field: safeXField,
          type: getVegaType(xType),
          axis: { title: formatFieldName(safeXField), labelAngle, labelColor: "#94a3b8", titleColor: "#e2e8f0", gridOpacity: 0 },
        },
        y: {
          field: safeYField,
          type: "quantitative",
          axis: { title: formatFieldName(safeYField), format: "~s", labelColor: "#94a3b8", titleColor: "#e2e8f0", gridColor: "#334155", gridOpacity: 0.5 },
        },
        color: hasSeries
          ? { field: seriesField, type: "nominal", scale: { range: MODERN_COLORS }, legend: { orient: "bottom", labelColor: "#94a3b8", titleColor: "#e2e8f0" } }
          : { value: PRIMARY_COLOR },
        tooltip: [
          { field: safeXField, type: getVegaType(xType), title: formatFieldName(safeXField) },
          { field: safeYField, type: "quantitative", title: formatFieldName(safeYField), format: ",.0f" },
        ],
      },
      width: "container",
      height: 280,
      autosize: { type: "fit", contains: "padding" },
      config: BASE_CONFIG,
      title: vizState.view.title ? { text: vizState.view.title, subtitle: vizState.view.subtitle } : undefined,
    } as TopLevelSpec;
  }

  // PIE CHART
  if (vizState.chartType === "pie") {
    return {
      $schema: "https://vega.github.io/schema/vega-lite/v5.json",
      data: { values: transformedData },
      width: 320,
      height: 320,
      config: BASE_CONFIG,
      title: vizState.view.title ? { text: vizState.view.title, subtitle: vizState.view.subtitle } : undefined,
      layer: [
        {
          mark: { type: "arc", innerRadius: 70, outerRadius: 130, padAngle: 0.02, cornerRadius: 4 },
          encoding: {
            theta: { field: safeYField, type: "quantitative", stack: true },
            color: { field: safeXField, type: "nominal", scale: { range: MODERN_COLORS }, legend: { title: formatFieldName(safeXField), orient: "right", labelColor: "#94a3b8", titleColor: "#e2e8f0" } },
            tooltip: [
              { field: safeXField, type: "nominal", title: formatFieldName(safeXField) },
              { field: safeYField, type: "quantitative", title: formatFieldName(safeYField), format: ",.0f" },
            ],
          },
        },
        {
          mark: { type: "text", radius: 155, fontSize: 11, fontWeight: 500, color: "#e2e8f0" },
          encoding: {
            theta: { field: safeYField, type: "quantitative", stack: true },
            text: { field: safeYField, type: "quantitative", format: ".0%" },
            color: { value: "#e2e8f0" },
          },
          transform: [
            { window: [{ op: "sum", field: safeYField, as: "total" }], frame: [null, null] },
            { calculate: `datum['${safeYField}'] / datum.total`, as: safeYField },
          ],
        },
      ],
    } as TopLevelSpec;
  }

  // SCATTER CHART
  if (vizState.chartType === "scatter") {
    return {
      $schema: "https://vega.github.io/schema/vega-lite/v5.json",
      data: { values: transformedData },
      mark: { type: "point", filled: true, size: 120, opacity: 0.7 },
      encoding: {
        x: {
          field: safeXField,
          type: "quantitative",
          axis: { title: formatFieldName(safeXField), labelColor: "#94a3b8", titleColor: "#e2e8f0", gridColor: "#334155", gridOpacity: 0.3 },
        },
        y: {
          field: safeYField,
          type: "quantitative",
          axis: { title: formatFieldName(safeYField), format: "~s", labelColor: "#94a3b8", titleColor: "#e2e8f0", gridColor: "#334155", gridOpacity: 0.3 },
        },
        color: hasSeries
          ? { field: seriesField, type: "nominal", scale: { range: MODERN_COLORS }, legend: { orient: "right", labelColor: "#94a3b8", titleColor: "#e2e8f0" } }
          : { value: PRIMARY_COLOR },
        tooltip: [
          { field: safeXField, type: "quantitative", title: formatFieldName(safeXField) },
          { field: safeYField, type: "quantitative", title: formatFieldName(safeYField), format: ",.0f" },
          ...(seriesField ? [{ field: seriesField, type: "nominal", title: formatFieldName(seriesField) }] : []),
        ],
      },
      width: "container",
      height: 280,
      autosize: { type: "fit", contains: "padding" },
      config: BASE_CONFIG,
      title: vizState.view.title ? { text: vizState.view.title, subtitle: vizState.view.subtitle } : undefined,
    } as TopLevelSpec;
  }

  // STACKED BAR
  if (vizState.chartType === "stacked_bar") {
    return {
      $schema: "https://vega.github.io/schema/vega-lite/v5.json",
      data: { values: transformedData },
      mark: { type: "bar" },
      encoding: {
        x: {
          field: safeXField,
          type: getVegaType(xType),
          axis: { title: formatFieldName(safeXField), labelAngle, labelColor: "#94a3b8", titleColor: "#e2e8f0", gridOpacity: 0 },
        },
        y: {
          field: safeYField,
          type: "quantitative",
          axis: { title: formatFieldName(safeYField), format: "~s", labelColor: "#94a3b8", titleColor: "#e2e8f0", gridColor: "#334155", gridOpacity: 0.5 },
        },
        color: {
          field: seriesField,
          type: "nominal",
          scale: { range: MODERN_COLORS },
          legend: { title: formatFieldName(seriesField || ""), orient: "bottom", labelColor: "#94a3b8", titleColor: "#e2e8f0" },
        },
        tooltip: [
          { field: safeXField, type: getVegaType(xType), title: formatFieldName(safeXField) },
          { field: safeYField, type: "quantitative", title: formatFieldName(safeYField), format: ",.0f" },
          { field: seriesField, type: "nominal", title: formatFieldName(seriesField || "") },
        ],
      },
      width: "container",
      height: 280,
      autosize: { type: "fit", contains: "padding" },
      config: BASE_CONFIG,
      title: vizState.view.title ? { text: vizState.view.title, subtitle: vizState.view.subtitle } : undefined,
    } as TopLevelSpec;
  }

  // HEATMAP
  if (vizState.chartType === "heatmap") {
    return {
      $schema: "https://vega.github.io/schema/vega-lite/v5.json",
      data: { values: transformedData },
      mark: { type: "rect" },
      encoding: {
        x: {
          field: safeXField,
          type: getVegaType(xType),
          axis: { title: formatFieldName(safeXField), labelAngle, labelColor: "#94a3b8", titleColor: "#e2e8f0" },
        },
        y: {
          field: safeYField,
          type: "nominal",
          axis: { title: formatFieldName(safeYField), labelColor: "#94a3b8", titleColor: "#e2e8f0" },
        },
        color: {
          field: seriesField || safeYField,
          type: "quantitative",
          scale: { scheme: "blues" },
          legend: { labelColor: "#94a3b8", titleColor: "#e2e8f0" },
        },
        tooltip: [
          { field: safeXField, type: getVegaType(xType), title: formatFieldName(safeXField) },
          { field: safeYField, type: "nominal", title: formatFieldName(safeYField) },
          ...(seriesField ? [{ field: seriesField, type: "quantitative", title: formatFieldName(seriesField), format: ",.0f" }] : []),
        ],
      },
      width: "container",
      height: 280,
      autosize: { type: "fit", contains: "padding" },
      config: BASE_CONFIG,
      title: vizState.view.title ? { text: vizState.view.title, subtitle: vizState.view.subtitle } : undefined,
    } as TopLevelSpec;
  }

  // BUMP CHART
  if (vizState.chartType === "bump") {
    return {
      $schema: "https://vega.github.io/schema/vega-lite/v5.json",
      data: { values: transformedData },
      layer: [
        {
          mark: { type: "line", strokeWidth: 2.5, point: { filled: true, size: 80 } },
          encoding: {
            x: {
              field: safeXField,
              type: getVegaType(xType),
              axis: { title: formatFieldName(safeXField), labelAngle, labelColor: "#94a3b8", titleColor: "#e2e8f0", gridOpacity: 0 },
            },
            y: {
              field: safeYField,
              type: "quantitative",
              sort: "ascending",
              scale: { reverse: true },
              axis: {
                title: formatFieldName(safeYField),
                labelColor: "#94a3b8",
                titleColor: "#e2e8f0",
                gridColor: "#334155",
                gridOpacity: 0.4,
                tickMinStep: 1,
              },
            },
            color: hasSeries
              ? { field: seriesField, type: "nominal", scale: { range: MODERN_COLORS }, legend: { title: formatFieldName(seriesField || ""), orient: "right", labelColor: "#94a3b8", titleColor: "#e2e8f0" } }
              : { value: PRIMARY_COLOR },
            tooltip: [
              { field: safeXField, type: getVegaType(xType), title: formatFieldName(safeXField) },
              { field: safeYField, type: "quantitative", title: "Rank" },
              ...(seriesField ? [{ field: seriesField, type: "nominal", title: formatFieldName(seriesField) }] : []),
            ],
          },
        },
      ],
      width: "container",
      height: 280,
      autosize: { type: "fit", contains: "padding" },
      config: BASE_CONFIG,
      title: vizState.view.title ? { text: vizState.view.title, subtitle: vizState.view.subtitle } : undefined,
    } as TopLevelSpec;
  }

  // BOXPLOT
  if (vizState.chartType === "boxplot") {
    return {
      $schema: "https://vega.github.io/schema/vega-lite/v5.json",
      data: { values: transformedData },
      mark: { type: "boxplot", extent: "min-max", ticks: true },
      encoding: {
        x: {
          field: safeXField,
          type: "nominal",
          axis: { title: formatFieldName(safeXField), labelAngle, labelColor: "#94a3b8", titleColor: "#e2e8f0" },
        },
        y: {
          field: safeYField,
          type: "quantitative",
          axis: { title: formatFieldName(safeYField), format: "~s", labelColor: "#94a3b8", titleColor: "#e2e8f0", gridColor: "#334155", gridOpacity: 0.5 },
        },
        color: hasSeries
          ? { field: seriesField, type: "nominal", scale: { range: MODERN_COLORS }, legend: { labelColor: "#94a3b8", titleColor: "#e2e8f0" } }
          : { value: PRIMARY_COLOR },
      },
      width: "container",
      height: 280,
      autosize: { type: "fit", contains: "padding" },
      config: BASE_CONFIG,
      title: vizState.view.title ? { text: vizState.view.title, subtitle: vizState.view.subtitle } : undefined,
    } as TopLevelSpec;
  }

  // FACET BAR
  if (vizState.chartType === "facet_bar") {
    const facetField = seriesField || safeXField;
    return {
      $schema: "https://vega.github.io/schema/vega-lite/v5.json",
      data: { values: transformedData },
      facet: {
        field: facetField,
        type: "nominal",
        header: {
          title: null,
          labelColor: "#e2e8f0",
          labelFontSize: 12,
          labelFontWeight: 600,
        },
        columns: Math.min(3, Math.ceil(Math.sqrt(seriesCount || 4))),
      },
      spec: {
        mark: { type: "bar", cornerRadiusTopLeft: 3, cornerRadiusTopRight: 3, color: PRIMARY_COLOR },
        encoding: {
          x: {
            field: safeXField,
            type: getVegaType(xType),
            axis: { title: null, labelAngle, labelColor: "#94a3b8", labelFontSize: 10 },
          },
          y: {
            field: safeYField,
            type: "quantitative",
            axis: { title: null, format: "~s", labelColor: "#94a3b8", gridColor: "#334155", gridOpacity: 0.5 },
          },
          tooltip: [
            { field: safeXField, type: getVegaType(xType), title: formatFieldName(safeXField) },
            { field: safeYField, type: "quantitative", title: formatFieldName(safeYField), format: ",.0f" },
          ],
        },
        width: 160,
        height: 120,
      },
      config: BASE_CONFIG,
      title: vizState.view.title ? { text: vizState.view.title, subtitle: vizState.view.subtitle } : undefined,
    } as unknown as TopLevelSpec;
  }

  // FACET LINE
  if (vizState.chartType === "facet_line") {
    const facetField = seriesField || safeXField;
    return {
      $schema: "https://vega.github.io/schema/vega-lite/v5.json",
      data: { values: transformedData },
      facet: {
        field: facetField,
        type: "nominal",
        header: {
          title: null,
          labelColor: "#e2e8f0",
          labelFontSize: 12,
          labelFontWeight: 600,
        },
        columns: Math.min(3, Math.ceil(Math.sqrt(seriesCount || 4))),
      },
      spec: {
        mark: { type: "line", strokeWidth: 2, point: { filled: true, size: 50 }, color: PRIMARY_COLOR, interpolate: "monotone" },
        encoding: {
          x: {
            field: safeXField,
            type: getVegaType(xType),
            axis: { title: null, labelAngle, labelColor: "#94a3b8", labelFontSize: 10 },
          },
          y: {
            field: safeYField,
            type: "quantitative",
            axis: { title: null, format: "~s", labelColor: "#94a3b8", gridColor: "#334155", gridOpacity: 0.5 },
          },
          tooltip: [
            { field: safeXField, type: getVegaType(xType), title: formatFieldName(safeXField) },
            { field: safeYField, type: "quantitative", title: formatFieldName(safeYField), format: ",.0f" },
          ],
        },
        width: 160,
        height: 120,
      },
      config: BASE_CONFIG,
      title: vizState.view.title ? { text: vizState.view.title, subtitle: vizState.view.subtitle } : undefined,
    } as unknown as TopLevelSpec;
  }

  // DEFAULT / FALLBACK (bar)
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    data: { values: transformedData },
    mark: { type: "bar", cornerRadiusTopLeft: 4, cornerRadiusTopRight: 4 },
    encoding: {
      x: { field: safeXField, type: getVegaType(xType), axis: { labelAngle, labelColor: "#94a3b8", titleColor: "#e2e8f0" } },
      y: { field: safeYField, type: "quantitative", axis: { format: "~s", labelColor: "#94a3b8", titleColor: "#e2e8f0", gridColor: "#334155" } },
      color: { value: PRIMARY_COLOR },
    },
    width: "container",
    height: 280,
    autosize: { type: "fit", contains: "padding" },
    config: BASE_CONFIG,
  } as TopLevelSpec;
}

/**
 * Compile table data — applies client-side transforms and returns
 * column metadata + row objects.
 */
export function compileTableData(
  envelope: ResultEnvelope,
  vizState: VizState
): { columns: ColumnMeta[]; rows: Record<string, any>[] } {
  return {
    columns: envelope.data.columns,
    rows: applyClientSideTransforms(
      envelope.data.rows,
      envelope.data.columns,
      vizState.transforms
    ),
  };
}
