/**
 * ChatMessage Component
 *
 * Renders a single chat message with support for:
 * - Markdown text blocks
 * - Tool call display with collapsible SQL
 * - TTS playback button
 * - Feedback (thumbs up/down)
 * - Thinking steps
 * - Streaming indicator
 *
 * Generic: TTS and feedback endpoints are configurable via props.
 * Markdown rendering is delegated to a `renderMarkdown` prop.
 */

import React, { memo, useState, useRef, useCallback } from "react";
import type {
  ChatMessage as ChatMessageType,
  ActiveBlockRef,
  ToolCall,
  ThinkingStep,
} from "./types";

// ---------------------------------------------------------------------------
// Inline stripMarkdown for TTS input
// ---------------------------------------------------------------------------

function stripMarkdown(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, "")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/#{1,6}\s+/g, "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/^[-*+]\s+/gm, "")
    .replace(/^\d+\.\s+/gm, "")
    .replace(/^>\s+/gm, "")
    .replace(/\|[^\n]+\|/g, "")
    .replace(/---+/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ChatMessageProps {
  message: ChatMessageType;
  activeBlock: ActiveBlockRef | null;
  onBlockClick: (ref: ActiveBlockRef) => void;
  isStreaming?: boolean;
  /** Endpoint for TTS synthesis. Default: none (TTS button hidden). */
  ttsEndpoint?: string;
  /** Endpoint for feedback submission. Default: none (feedback hidden). */
  feedbackEndpoint?: string;
  /** Custom markdown renderer. Receives markdown string, returns JSX. */
  renderMarkdown?: (markdown: string) => React.ReactNode;
  /** Custom thinking section renderer. */
  renderThinkingSection?: (
    steps: ThinkingStep[],
    isStreaming: boolean
  ) => React.ReactNode;
  onFeedback?: (messageId: string, type: "positive" | "negative") => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export const ChatMessage = memo(function ChatMessage({
  message,
  activeBlock,
  onBlockClick,
  isStreaming = false,
  ttsEndpoint,
  feedbackEndpoint,
  renderMarkdown,
  renderThinkingSection,
  onFeedback,
}: ChatMessageProps) {
  const isUser = message.role === "user";
  const isActive = (blockId: string) =>
    activeBlock?.messageId === message.id &&
    activeBlock?.blockId === blockId;

  const [feedback, setFeedback] = useState<"positive" | "negative" | null>(
    null
  );
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false);
  const [ttsState, setTtsState] = useState<"idle" | "loading" | "playing">(
    "idle"
  );
  const [audienceMode, setAudienceMode] = useState<
    "exec" | "business" | "technical"
  >("exec");
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const handleSpeak = useCallback(async () => {
    if (!ttsEndpoint) return;

    if (ttsState === "playing" && audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
      setTtsState("idle");
      return;
    }
    if (ttsState === "loading") return;

    const plainText = stripMarkdown(
      typeof message.content === "string"
        ? message.content
        : message.blocks
            .filter((b) => b.type === "text")
            .map((b) => (b as any).markdown)
            .join(" ")
    );
    if (!plainText) return;

    const textToSpeak =
      plainText.length > 1500 ? plainText.slice(0, 1500) : plainText;

    setTtsState("loading");
    try {
      const resp = await fetch(ttsEndpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: textToSpeak,
          audience_mode: audienceMode,
        }),
      });

      if (!resp.ok) throw new Error(`TTS failed: ${resp.statusText}`);

      const audioBlob = await resp.blob();
      const audioUrl = URL.createObjectURL(audioBlob);
      const audio = new Audio(audioUrl);

      audio.onended = () => {
        URL.revokeObjectURL(audioUrl);
        audioRef.current = null;
        setTtsState("idle");
      };
      audio.onerror = () => {
        URL.revokeObjectURL(audioUrl);
        audioRef.current = null;
        setTtsState("idle");
      };

      audioRef.current = audio;
      audio.playbackRate = 1.25;
      setTtsState("playing");
      audio.play();
    } catch (err) {
      console.error("[ChatMessage] TTS error:", err);
      setTtsState("idle");
    }
  }, [ttsState, message, audienceMode, ttsEndpoint]);

  const handleFeedback = async (type: "positive" | "negative") => {
    if (feedback || feedbackSubmitting || !feedbackEndpoint) return;

    setFeedbackSubmitting(true);
    try {
      const response = await fetch(feedbackEndpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message_id: message.id,
          reaction_type: type,
        }),
      });

      if (response.ok) {
        setFeedback(type);
        onFeedback?.(message.id, type);
      }
    } catch (error) {
      console.error("Failed to submit feedback:", error);
    } finally {
      setFeedbackSubmitting(false);
    }
  };

  // ── Tool calls ──────────────────────────────────────────────────────────

  const renderToolCalls = () => {
    if (!message.toolCalls || message.toolCalls.length === 0) return null;
    return (
      <div className="flex flex-col gap-1.5 mb-3">
        {message.toolCalls.map((tool, idx) => (
          <SqlQueryRow key={idx} tool={tool} />
        ))}
      </div>
    );
  };

  // ── Feedback / TTS bar ──────────────────────────────────────────────────

  const renderFeedbackButtons = () => {
    if (isUser || isStreaming || !message.content) return null;

    return (
      <div className="flex items-center gap-1 mt-3">
        {/* TTS playback button */}
        {ttsEndpoint && (
          <>
            <button
              onClick={handleSpeak}
              disabled={ttsState === "loading"}
              className="p-1.5 rounded hover:bg-opacity-20 transition-colors disabled:opacity-50"
              style={{
                color:
                  ttsState === "playing"
                    ? "var(--color-accent)"
                    : "var(--color-text-muted)",
              }}
              title={
                ttsState === "playing"
                  ? "Stop playback"
                  : ttsState === "loading"
                  ? "Generating audio..."
                  : "Listen to response"
              }
            >
              {ttsState === "loading" ? (
                <span className="h-4 w-4 animate-spin">...</span>
              ) : ttsState === "playing" ? (
                <span className="h-3.5 w-3.5">{"\u25A0"}</span>
              ) : (
                <span className="h-4 w-4">{"\u{1F50A}"}</span>
              )}
            </button>

            {/* Audience mode toggle */}
            <div
              className="inline-flex rounded-md overflow-hidden"
              style={{
                border: "1px solid var(--color-border-subtle)",
              }}
            >
              {(["exec", "business", "technical"] as const).map(
                (mode) => (
                  <button
                    key={mode}
                    onClick={() => setAudienceMode(mode)}
                    className="px-1.5 py-0.5 text-[9px] font-medium transition-colors"
                    style={{
                      background:
                        audienceMode === mode
                          ? "var(--color-accent)"
                          : "transparent",
                      color:
                        audienceMode === mode
                          ? "white"
                          : "var(--color-text-muted)",
                    }}
                    title={`${
                      mode.charAt(0).toUpperCase() + mode.slice(1)
                    } narration mode`}
                  >
                    {mode === "exec"
                      ? "Exec"
                      : mode === "business"
                      ? "Biz"
                      : "Tech"}
                  </button>
                )
              )}
            </div>

            <div
              style={{
                width: "1px",
                height: "16px",
                background: "var(--color-border-subtle)",
                margin: "0 2px",
              }}
            />
          </>
        )}

        {feedbackEndpoint && (
          <>
            {feedback ? (
              <div
                className="flex items-center gap-1 text-xs px-2 py-1 rounded"
                style={{ color: "var(--color-text-muted)" }}
              >
                {"\u2713"} Thanks for your feedback
              </div>
            ) : (
              <>
                <button
                  onClick={() => handleFeedback("positive")}
                  disabled={feedbackSubmitting}
                  className="p-1.5 rounded hover:bg-opacity-20 transition-colors disabled:opacity-50"
                  style={{ color: "var(--color-text-muted)" }}
                  title="Helpful"
                >
                  {"\u{1F44D}"}
                </button>
                <button
                  onClick={() => handleFeedback("negative")}
                  disabled={feedbackSubmitting}
                  className="p-1.5 rounded hover:bg-opacity-20 transition-colors disabled:opacity-50"
                  style={{ color: "var(--color-text-muted)" }}
                  title="Not helpful"
                >
                  {"\u{1F44E}"}
                </button>
              </>
            )}
          </>
        )}
      </div>
    );
  };

  // ── Render ──────────────────────────────────────────────────────────────

  return (
    <div
      className="flex gap-3 px-4 py-3"
      style={{
        background: isUser
          ? "transparent"
          : "var(--color-surface-soft)",
        borderBottom: "1px solid var(--color-border-subtle)",
      }}
    >
      {/* Avatar */}
      <div
        className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center"
        style={{
          background: isUser
            ? "var(--color-accent)"
            : "rgba(71, 85, 105, 0.5)",
        }}
      >
        <span className="text-white text-sm">
          {isUser ? "U" : "A"}
        </span>
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        {/* Thinking section */}
        {!isUser &&
          message.thinkingSteps &&
          message.thinkingSteps.length > 0 &&
          renderThinkingSection?.(message.thinkingSteps, isStreaming)}

        {/* Tool call badges */}
        {renderToolCalls()}

        {/* Message blocks */}
        {message.blocks.map((block) => {
          if (block.type === "text") {
            return renderMarkdown ? (
              <div key={block.id}>
                {renderMarkdown(block.markdown)}
              </div>
            ) : (
              <div
                key={block.id}
                className="prose prose-sm max-w-none"
                style={{ color: "var(--color-text-primary)" }}
              >
                {block.markdown}
              </div>
            );
          }

          if (block.type === "table") {
            return (
              <div
                key={block.id}
                className="my-2 p-2 rounded cursor-pointer transition-colors"
                style={{
                  border: isActive(block.id)
                    ? "2px solid var(--color-accent)"
                    : "1px solid var(--color-border-subtle)",
                  background:
                    "var(--color-surface-soft)",
                }}
                onClick={() =>
                  onBlockClick({
                    messageId: message.id,
                    blockId: block.id,
                  })
                }
              >
                <div
                  className="text-xs font-medium mb-1"
                  style={{
                    color: "var(--color-text-secondary)",
                  }}
                >
                  {block.meta?.title || "Data Table"}{" "}
                  ({block.rows.length} rows)
                </div>
              </div>
            );
          }

          return null;
        })}

        {/* Streaming indicator */}
        {isStreaming &&
          message.role === "assistant" &&
          message.content === "" && (
            <div
              className="flex items-center gap-2 text-sm"
              style={{ color: "var(--color-text-muted)" }}
            >
              <span className="animate-spin">{"..."}</span>
              Thinking...
            </div>
          )}

        {/* Feedback buttons */}
        {renderFeedbackButtons()}
      </div>
    </div>
  );
});

// ============================================================================
// SqlQueryRow -- collapsible SQL display
// ============================================================================

interface SqlQueryRowProps {
  tool: ToolCall;
}

function SqlQueryRow({ tool }: SqlQueryRowProps) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const title =
    (tool.args?.title as string) || tool.name.replace(/_/g, " ");
  const sql = tool.args?.sql as string | undefined;
  const isRunning = tool.status === "running";

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (sql) {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  };

  return (
    <div>
      {/* Header row */}
      <div
        className="flex items-center gap-2"
        style={{ color: "var(--color-text-muted)" }}
      >
        <span
          className="h-3 w-3 flex-shrink-0"
          style={{
            color: isRunning
              ? "var(--color-accent)"
              : "#22c55e",
          }}
        >
          {isRunning ? "..." : "\u2713"}
        </span>
        <span
          className="text-xs"
          style={{
            color: isRunning
              ? "var(--color-accent)"
              : "var(--color-text-secondary)",
          }}
        >
          {title}
        </span>
        {!isRunning && sql && (
          <button
            onClick={() => setOpen((v) => !v)}
            className="flex items-center gap-0.5 text-[10px] ml-1 transition-colors"
            style={{
              color: "var(--color-text-muted)",
              fontFamily: "var(--font-mono, monospace)",
            }}
          >
            {open ? "\u25BC" : "\u25B6"} SQL
          </button>
        )}
      </div>

      {/* Collapsible SQL block */}
      {open && sql && (
        <div
          className="relative mt-1.5 rounded-r text-[11px] leading-relaxed overflow-x-auto"
          style={{
            background: "rgba(0,0,0,0.25)",
            borderLeft: "2px solid var(--color-accent-border)",
            padding: "10px 14px",
            fontFamily: "var(--font-mono, monospace)",
            color: "var(--color-text-secondary)",
            whiteSpace: "pre",
          }}
        >
          <button
            onClick={handleCopy}
            className="absolute top-1.5 right-1.5 flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded transition-colors"
            style={{
              background: "rgba(255,255,255,0.06)",
              border: "1px solid rgba(255,255,255,0.1)",
              color: "var(--color-text-muted)",
            }}
          >
            {copied ? "\u2713" : "\u2398"}
          </button>
          {sql}
        </div>
      )}
    </div>
  );
}
