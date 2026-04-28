/**
 * Chat Feature — Shared Types
 *
 * Block-based chat message types for two-panel UI.
 * Self-contained: no external imports required.
 */

// ============================================================================
// Block Types
// ============================================================================

export interface TextBlock {
  id: string;
  type: "text";
  markdown: string;
}

export interface ChartBlock {
  id: string;
  type: "chart";
  title?: string;
  subtitle?: string;
  specType: "vegaLite" | "recharts" | "echarts";
  spec: any | null;
  dataRef?: {
    type: "genie" | "sql" | "custom";
    genie?: {
      spaceId: string;
      conversationId: string;
      messageId: string;
      attachmentId: string;
    };
    sql?: {
      query: string;
      catalog?: string;
      schema?: string;
    };
  };
  meta?: {
    primaryMeasure?: string;
    primaryDim?: string;
    timeframe?: string;
  };
}

export interface TableBlock {
  id: string;
  type: "table";
  columns: string[];
  rows: any[][];
  meta?: {
    title?: string;
    subtitle?: string;
    query?: string;
  };
  envelopeId?: string;
}

export interface ImageBlock {
  id: string;
  type: "image";
  url: string;
  alt?: string;
  width?: number;
  height?: number;
}

export type FileType =
  | "pdf"
  | "word"
  | "excel"
  | "powerpoint"
  | "text"
  | "code"
  | "data"
  | "json"
  | "image"
  | "web"
  | "file";

export interface CitationBlock {
  id: string;
  type: "citation";
  title: string;
  label: string;
  url: string;
  path: string;
  fileType: FileType;
  page?: number;
  snippet?: string;
  chunk?: string;
  score?: number;
  index?: number;
  refNumber?: number;
}

export type ChatBlock =
  | TextBlock
  | ChartBlock
  | TableBlock
  | ImageBlock
  | CitationBlock;

// ============================================================================
// Tool Call Types
// ============================================================================

export interface ToolCall {
  name: string;
  status: "running" | "complete" | "error";
  args?: Record<string, any>;
  output?: any;
}

// ============================================================================
// Thinking Step Types (for agent transparency)
// ============================================================================

export type ThinkingStepType =
  | "routing"
  | "agent_start"
  | "tool_call"
  | "tool_result"
  | "retry"
  | "agent_end";

export interface ThinkingStep {
  id: string;
  type: ThinkingStepType;
  agent: string;
  message: string;
  timestamp: number;
  isRetry?: boolean;
  metadata?: {
    confidence?: number;
    failedAgents?: string[];
    toolName?: string;
    error?: string;
  };
}

// ============================================================================
// Result Envelope (for visualization system)
// ============================================================================

export interface ResultEnvelope {
  result_id: string;
  columns?: Array<{ name: string; type: string }>;
  rows?: any[][];
  query?: string;
  [key: string]: any;
}

// ============================================================================
// Message Types
// ============================================================================

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  blocks: ChatBlock[];
  citations?: CitationBlock[];
  toolCalls?: ToolCall[];
  thinkingSteps?: ThinkingStep[];
  timestamp: number;
  envelopes?: Record<string, ResultEnvelope>;
  metadata?: {
    agentUsed?: string;
    routingConfidence?: number;
    routingReason?: string;
    executionTimeMs?: number;
    retryCount?: number;
    failedAgents?: string[];
  };
}

// ============================================================================
// Active Block Reference
// ============================================================================

export interface ActiveBlockRef {
  messageId: string;
  blockId: string;
}

// ============================================================================
// Image Attachment
// ============================================================================

export interface ImageAttachment {
  file: File;
  preview: string;
  base64?: string;
}
