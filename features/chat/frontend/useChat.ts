/**
 * useChat Hook
 *
 * Encapsulates all chat state management and streaming logic.
 * Provides a clean interface for sending messages and managing chat state.
 * Supports multimodal messages with image attachments.
 *
 * Generic: no hardcoded endpoints. Pass `streamEndpoint` via options.
 */

import { useState, useCallback, useRef } from "react";
import type {
  ChatMessage,
  ToolCall,
  ActiveBlockRef,
  ThinkingStep,
  ChatBlock,
  CitationBlock,
  ImageAttachment,
} from "./types";

// ---------------------------------------------------------------------------
// Inline parseMessageBlocks — simplified block parser (no citation extraction)
// Override with your own parser via UseChatOptions.parseBlocks if needed.
// ---------------------------------------------------------------------------

interface ParsedContent {
  blocks: ChatBlock[];
  citations: CitationBlock[];
}

function defaultParseMessageBlocks(
  content: string,
  messageId: string
): ParsedContent {
  const blocks: ChatBlock[] = [];
  if (!content.trim()) return { blocks, citations: [] };

  const lines = content.split("\n");
  let currentTextLines: string[] = [];
  let tableLines: string[] = [];
  let inTable = false;
  let blockCounter = 0;

  const flushText = () => {
    if (currentTextLines.length > 0) {
      const textContent = currentTextLines.join("\n").trim();
      if (textContent) {
        blocks.push({
          id: `${messageId}-text-${blockCounter++}`,
          type: "text",
          markdown: textContent,
        });
      }
      currentTextLines = [];
    }
  };

  const flushTable = () => {
    if (tableLines.length >= 2) {
      const headerLine = tableLines[0].trim();
      const headers = headerLine
        .split("|")
        .slice(1, -1)
        .map((h, i) => h.trim() || `Column ${i + 1}`);

      if (headers.length > 0) {
        const dataRows: string[][] = [];
        for (let i = 2; i < tableLines.length; i++) {
          const line = tableLines[i].trim();
          if (!line) continue;
          const cells = line
            .split("|")
            .slice(1, -1)
            .map((c) => c.trim());
          if (cells.length === headers.length) {
            dataRows.push(cells);
          }
        }

        if (dataRows.length > 0) {
          blocks.push({
            id: `${messageId}-table-${blockCounter++}`,
            type: "table",
            columns: headers,
            rows: dataRows,
            meta: { title: "Data Table", subtitle: `${dataRows.length} rows` },
          });
        } else {
          currentTextLines.push(...tableLines);
        }
      } else {
        currentTextLines.push(...tableLines);
      }
      tableLines = [];
    }
    inTable = false;
  };

  for (const line of lines) {
    const trimmedLine = line.trim();
    if (trimmedLine.startsWith("|") && trimmedLine.endsWith("|")) {
      if (!inTable) {
        flushText();
        inTable = true;
      }
      tableLines.push(line);
    } else {
      if (inTable) flushTable();
      currentTextLines.push(line);
    }
  }

  if (inTable) flushTable();
  flushText();

  if (blocks.length === 0 && content.trim()) {
    blocks.push({
      id: `${messageId}-text-0`,
      type: "text",
      markdown: content,
    });
  }

  return { blocks, citations: [] };
}

// ---------------------------------------------------------------------------
// Hook types
// ---------------------------------------------------------------------------

export interface UseChatOptions {
  /** SSE streaming endpoint. No default — must be provided. */
  streamEndpoint: string;
  /** Custom block parser. Defaults to simple markdown table extraction. */
  parseBlocks?: (content: string, messageId: string) => ParsedContent;
  onError?: (error: Error) => void;
  onStreamStart?: () => void;
  onStreamEnd?: () => void;
  /** Called on each text.delta SSE event with the delta and full accumulated text. */
  onTextDelta?: (delta: string, accumulated: string) => void;
  /** Called when the SSE stream completes with the full response text. */
  onStreamComplete?: (fullText: string) => void;
}

export interface UseChatReturn {
  messages: ChatMessage[];
  isStreaming: boolean;
  activeBlock: ActiveBlockRef | null;
  toolCalls: ToolCall[];
  followupSuggestions: string[];
  setActiveBlock: (ref: ActiveBlockRef | null) => void;
  sendMessage: (content: string, images?: ImageAttachment[]) => Promise<void>;
  clearMessages: () => void;
  cancelStream: () => void;
}

// ---------------------------------------------------------------------------
// Hook implementation
// ---------------------------------------------------------------------------

export function useChat(options: UseChatOptions): UseChatReturn {
  const {
    streamEndpoint,
    parseBlocks = defaultParseMessageBlocks,
    onError,
    onStreamStart,
    onStreamEnd,
    onTextDelta,
    onStreamComplete,
  } = options;

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [activeBlock, setActiveBlock] = useState<ActiveBlockRef | null>(null);
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([]);
  const [followupSuggestions, setFollowupSuggestions] = useState<string[]>([]);

  const sessionIdRef = useRef<string>(
    `session-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
  );
  const abortControllerRef = useRef<AbortController | null>(null);
  const streamingMessageIdRef = useRef<string | null>(null);

  const cancelStream = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsStreaming(false);
    streamingMessageIdRef.current = null;
  }, []);

  const clearMessages = useCallback(() => {
    cancelStream();
    setMessages([]);
    setActiveBlock(null);
    setToolCalls([]);
    setFollowupSuggestions([]);
  }, [cancelStream]);

  const sendMessage = useCallback(
    async (content: string, images?: ImageAttachment[]) => {
      if ((!content.trim() && (!images || images.length === 0)) || isStreaming)
        return;

      // Build message content
      let messageContent:
        | string
        | Array<{
            type: string;
            text?: string;
            image?: string;
            mime?: string;
          }>;

      if (images && images.length > 0) {
        messageContent = [
          { type: "text", text: content.trim() || "What's in this image?" },
          ...images.map((img) => ({
            type: "image",
            image: img.base64 || "",
            mime: img.file.type,
          })),
        ];
      } else {
        messageContent = content.trim();
      }

      const generateId = () => crypto.randomUUID();

      // Create user message for display
      const userMessage: ChatMessage = {
        id: generateId(),
        role: "user",
        content: content.trim() || (images ? "[Image attached]" : ""),
        blocks: [
          {
            id: `${generateId()}-text-0`,
            type: "text",
            markdown:
              content.trim() || (images ? "*Image attached*" : ""),
          },
        ],
        citations: [],
        toolCalls: [],
        timestamp: Date.now(),
      };

      // Create placeholder assistant message
      const assistantMessageId = generateId();
      const assistantMessage: ChatMessage = {
        id: assistantMessageId,
        role: "assistant",
        content: "",
        blocks: [],
        citations: [],
        toolCalls: [],
        timestamp: Date.now(),
      };

      setMessages((prev) => [...prev, userMessage, assistantMessage]);
      setIsStreaming(true);
      setToolCalls([]);
      setFollowupSuggestions([]);
      streamingMessageIdRef.current = assistantMessageId;
      onStreamStart?.();

      abortControllerRef.current = new AbortController();
      const signal = abortControllerRef.current.signal;

      try {
        const apiMessages = [
          ...messages.map((m) => ({
            role: m.role,
            content: m.content,
          })),
          {
            role: userMessage.role,
            content: messageContent,
          },
        ];

        const response = await fetch(streamEndpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            messages: apiMessages,
            session_id: sessionIdRef.current,
          }),
          signal,
        });

        if (!response.ok) {
          throw new Error(`Stream failed: ${response.statusText}`);
        }

        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error("No response body");
        }

        const decoder = new TextDecoder();
        let buffer = "";
        let accumulatedContent = "";
        const activeToolCalls: ToolCall[] = [];
        const thinkingSteps: ThinkingStep[] = [];

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          while (buffer.includes("\n")) {
            const lineEnd = buffer.indexOf("\n");
            const line = buffer.slice(0, lineEnd).trim();
            buffer = buffer.slice(lineEnd + 1);

            if (!line || !line.startsWith("data: ")) continue;
            const data = line.slice(6);
            if (data === "[DONE]") continue;

            try {
              const event = JSON.parse(data);

              if (event.type === "text.delta") {
                accumulatedContent += event.delta || "";
                onTextDelta?.(event.delta || "", accumulatedContent);

                const { blocks, citations } = parseBlocks(
                  accumulatedContent,
                  assistantMessageId
                );

                setMessages((prev) =>
                  prev.map((m) => {
                    if (m.id !== assistantMessageId) return m;
                    const envelopeIds = Object.keys(m.envelopes || {});
                    let tableIdx = 0;
                    const linkedBlocks = blocks.map((block) => {
                      if (block.type !== "table") return block;
                      const id = envelopeIds[tableIdx++];
                      return id ? { ...block, envelopeId: id } : block;
                    });
                    return {
                      ...m,
                      content: accumulatedContent,
                      blocks: linkedBlocks,
                      citations,
                    };
                  })
                );
              } else if (event.type === "tool.call") {
                const newToolCall: ToolCall = {
                  name: event.name,
                  status: "running",
                  args: event.args,
                };
                activeToolCalls.push(newToolCall);
                setToolCalls([...activeToolCalls]);

                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMessageId
                      ? { ...m, toolCalls: [...activeToolCalls] }
                      : m
                  )
                );
              } else if (event.type === "tool.output") {
                const toolIdx = activeToolCalls.findIndex(
                  (t) => t.name === event.name && t.status === "running"
                );
                if (toolIdx >= 0) {
                  activeToolCalls[toolIdx] = {
                    ...activeToolCalls[toolIdx],
                    status: "complete",
                    output: event.output,
                  };
                  setToolCalls([...activeToolCalls]);

                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantMessageId
                        ? { ...m, toolCalls: [...activeToolCalls] }
                        : m
                    )
                  );
                }
              } else if (
                event.type === "thinking.step" ||
                event.type === "thinking.retry"
              ) {
                const newStep: ThinkingStep = {
                  id: crypto.randomUUID(),
                  type: event.step_type || "routing",
                  agent: event.agent || "unknown",
                  message: event.message || "",
                  timestamp: Date.now(),
                  isRetry: event.type === "thinking.retry",
                  metadata: event.metadata || {},
                };
                thinkingSteps.push(newStep);

                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMessageId
                      ? { ...m, thinkingSteps: [...thinkingSteps] }
                      : m
                  )
                );
              } else if (event.type === "metadata") {
                console.log("[useChat] Agent metadata:", event.data);

                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMessageId
                      ? {
                          ...m,
                          metadata: {
                            agentUsed: event.data?.agent_used,
                            routingConfidence:
                              event.data?.routing_confidence,
                            routingReason: event.data?.routing_reason,
                            executionTimeMs:
                              event.data?.execution_time_ms,
                            retryCount: event.data?.retry_count,
                            failedAgents: event.data?.failed_agents,
                          },
                        }
                      : m
                  )
                );
              } else if (event.type === "followups") {
                const suggestions = event.suggestions || [];
                if (
                  Array.isArray(suggestions) &&
                  suggestions.length > 0
                ) {
                  setFollowupSuggestions(suggestions);
                  console.log(
                    "[useChat] Follow-up suggestions:",
                    suggestions
                  );
                }
              } else if (event.type === "result.envelope") {
                const envelope = event.envelope;
                if (envelope && envelope.result_id) {
                  console.log(
                    "[useChat] Received ResultEnvelope:",
                    envelope.result_id
                  );

                  setMessages((prev) =>
                    prev.map((m) => {
                      if (m.id !== assistantMessageId) return m;
                      const newEnvelopes = {
                        ...(m.envelopes || {}),
                        [envelope.result_id]: envelope,
                      };
                      const envelopeIds = Object.keys(newEnvelopes);
                      let tableIdx = 0;
                      const linkedBlocks = m.blocks.map((block) => {
                        if (block.type !== "table") return block;
                        const id = envelopeIds[tableIdx++];
                        return id
                          ? { ...block, envelopeId: id }
                          : block;
                      });
                      return {
                        ...m,
                        envelopes: newEnvelopes,
                        blocks: linkedBlocks,
                      };
                    })
                  );

                  setActiveBlock((prev) => {
                    if (prev) return prev;
                    return {
                      messageId: assistantMessageId,
                      blockId: `${assistantMessageId}-table-0`,
                    };
                  });
                }
              } else if (event.type === "error") {
                console.error("[useChat] Stream error:", event.message);
                onError?.(new Error(event.message));
              }
            } catch (e) {
              console.warn("[useChat] Failed to parse event:", data);
            }
          }
        }

        // Final update
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMessageId
              ? {
                  ...m,
                  toolCalls: activeToolCalls,
                  thinkingSteps: thinkingSteps,
                }
              : m
          )
        );

        onStreamComplete?.(accumulatedContent);
      } catch (error: any) {
        if (error.name === "AbortError") {
          console.log("[useChat] Stream aborted");
        } else {
          console.error("[useChat] Stream error:", error);
          onError?.(error);

          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMessageId
                ? {
                    ...m,
                    content:
                      m.content ||
                      "Sorry, something went wrong. Please try again.",
                    blocks: m.blocks.length
                      ? m.blocks
                      : [
                          {
                            id: `${assistantMessageId}-error`,
                            type: "text" as const,
                            markdown:
                              "Sorry, something went wrong. Please try again.",
                          },
                        ],
                  }
                : m
            )
          );
        }
      } finally {
        setIsStreaming(false);
        streamingMessageIdRef.current = null;
        abortControllerRef.current = null;
        onStreamEnd?.();
      }
    },
    [
      messages,
      isStreaming,
      streamEndpoint,
      parseBlocks,
      onError,
      onStreamStart,
      onStreamEnd,
      onTextDelta,
      onStreamComplete,
    ]
  );

  return {
    messages,
    isStreaming,
    activeBlock,
    toolCalls,
    followupSuggestions,
    setActiveBlock,
    sendMessage,
    clearMessages,
    cancelStream,
  };
}
