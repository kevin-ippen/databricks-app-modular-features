/**
 * VoiceOverlay Component
 *
 * Full-screen overlay modal for live voice conversation mode.
 * Shows state indicators, pulsing mic animation, transcript,
 * and agent response text. Uses CSS variable system for theming.
 *
 * Includes animated feedback for processing states to reassure users
 * that the system is working during TTS/ASR latency gaps.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import type { VoiceState } from "./useVoiceConversation";

// ---------------------------------------------------------------------------
// State display config
// ---------------------------------------------------------------------------

const STATE_CONFIG: Record<
  VoiceState,
  {
    label: string;
    sublabel: string;
    color: string;
    icon: "mic" | "wave" | "dots" | "speaker";
  }
> = {
  idle: {
    label: "Ready",
    sublabel: "Starting...",
    color: "var(--color-text-muted)",
    icon: "mic",
  },
  listening: {
    label: "Listening",
    sublabel: "Speak now...",
    color: "var(--color-accent)",
    icon: "mic",
  },
  transcribing: {
    label: "Processing",
    sublabel: "Transcribing your speech...",
    color: "var(--color-warning, #f59e0b)",
    icon: "dots",
  },
  streaming: {
    label: "Thinking",
    sublabel: "Preparing response...",
    color: "var(--color-info, #3b82f6)",
    icon: "dots",
  },
  speaking: {
    label: "Speaking",
    sublabel: "Playing response...",
    color: "var(--color-success, #22c55e)",
    icon: "speaker",
  },
};

// ---------------------------------------------------------------------------
// Animated dots component for processing states
// ---------------------------------------------------------------------------

function AnimatedDots({ color }: { color: string }) {
  const [frame, setFrame] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setFrame((f) => (f + 1) % 4), 400);
    return () => clearInterval(id);
  }, []);

  return (
    <span
      style={{
        color,
        fontWeight: 600,
        fontSize: "24px",
        letterSpacing: "4px",
      }}
    >
      {".".repeat(frame || 1)}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface VoiceOverlayProps {
  state: VoiceState;
  transcript: string;
  agentText: string;
  volumeLevel: number;
  onStop: () => void;
  onInterrupt: () => void;
}

export function VoiceOverlay({
  state,
  transcript,
  agentText,
  volumeLevel,
  onStop,
  onInterrupt,
}: VoiceOverlayProps) {
  const config = STATE_CONFIG[state];
  const agentTextRef = useRef<HTMLDivElement>(null);

  // Escape key to close
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") onStop();
    },
    [onStop]
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  // Auto-scroll agent text to bottom as it streams in
  useEffect(() => {
    if (agentTextRef.current) {
      agentTextRef.current.scrollTop = agentTextRef.current.scrollHeight;
    }
  }, [agentText]);

  // Mic pulse scale: base 1.0, scales up with volume (max ~1.5)
  const pulseScale =
    state === "listening" ? 1 + Math.min(volumeLevel / 100, 0.5) : 1;

  const isProcessing = state === "transcribing" || state === "streaming";

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(0, 0, 0, 0.75)",
        backdropFilter: "blur(8px)",
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onStop();
      }}
    >
      {/* Keyframe animations */}
      <style>{`
        @keyframes voice-spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
        @keyframes voice-pulse {
          0%, 100% { opacity: 0.15; transform: scale(1); }
          50% { opacity: 0.3; transform: scale(1.08); }
        }
      `}</style>

      <div
        style={{
          width: "min(480px, 90vw)",
          background: "var(--color-bg-elevated, #1e293b)",
          borderRadius: "24px",
          padding: "48px 32px 32px",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: "24px",
          border:
            "1px solid var(--color-border-subtle, rgba(255,255,255,0.1))",
          boxShadow: "0 25px 50px rgba(0, 0, 0, 0.5)",
        }}
      >
        {/* State indicator */}
        <div style={{ textAlign: "center" }}>
          <div
            style={{
              fontSize: "14px",
              fontWeight: 600,
              letterSpacing: "0.05em",
              textTransform: "uppercase",
              color: config.color,
              marginBottom: "4px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "6px",
            }}
          >
            <span
              style={{
                width: "8px",
                height: "8px",
                borderRadius: "50%",
                background: config.color,
                display: "inline-block",
                animation: isProcessing
                  ? "voice-pulse 1.5s ease-in-out infinite"
                  : "none",
              }}
            />
            {config.label}
          </div>
          <div
            style={{
              fontSize: "13px",
              color: "var(--color-text-secondary, #94a3b8)",
            }}
          >
            {config.sublabel}
          </div>
        </div>

        {/* Pulsing mic / processing indicator */}
        <div
          style={{
            position: "relative",
            width: "120px",
            height: "120px",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          {/* Spinning ring for processing states */}
          {isProcessing && (
            <div
              style={{
                position: "absolute",
                inset: "-4px",
                borderRadius: "50%",
                border: `3px solid transparent`,
                borderTopColor: config.color,
                borderRightColor: config.color,
                animation: "voice-spin 1.2s linear infinite",
              }}
            />
          )}

          {/* Outer pulse ring */}
          <div
            style={{
              position: "absolute",
              inset: 0,
              borderRadius: "50%",
              border: `2px solid ${config.color}`,
              opacity: state === "listening" ? 0.4 : 0.15,
              transform: `scale(${pulseScale * 1.15})`,
              transition: "transform 0.15s ease-out, opacity 0.3s",
            }}
          />
          {/* Inner circle */}
          <div
            style={{
              width: "80px",
              height: "80px",
              borderRadius: "50%",
              background: config.color,
              opacity: 0.15,
              transform: `scale(${pulseScale})`,
              transition: "transform 0.15s ease-out",
              animation:
                state === "speaking"
                  ? "voice-pulse 1s ease-in-out infinite"
                  : "none",
            }}
          />
          {/* Center icon */}
          {config.icon === "dots" ? (
            <div style={{ position: "absolute" }}>
              <AnimatedDots color={config.color} />
            </div>
          ) : config.icon === "speaker" ? (
            <svg
              width="32"
              height="32"
              viewBox="0 0 24 24"
              fill="none"
              stroke={config.color}
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{ position: "absolute" }}
            >
              <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
              <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
              <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
            </svg>
          ) : (
            <svg
              width="32"
              height="32"
              viewBox="0 0 24 24"
              fill="none"
              stroke={config.color}
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{ position: "absolute" }}
            >
              <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
              <line x1="12" x2="12" y1="19" y2="22" />
            </svg>
          )}
        </div>

        {/* User transcript */}
        {transcript && (
          <div
            style={{
              width: "100%",
              padding: "12px 16px",
              borderRadius: "12px",
              background:
                "var(--color-surface-soft, rgba(255,255,255,0.05))",
              border:
                "1px solid var(--color-border-strong, rgba(255,255,255,0.1))",
            }}
          >
            <div
              style={{
                fontSize: "10px",
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                color: "var(--color-text-muted, #64748b)",
                marginBottom: "6px",
              }}
            >
              You said
            </div>
            <div
              style={{
                fontSize: "14px",
                color: "var(--color-text-primary, #e2e8f0)",
                lineHeight: 1.5,
              }}
            >
              {transcript}
            </div>
          </div>
        )}

        {/* Agent response text */}
        {agentText && (
          <div
            ref={agentTextRef}
            style={{
              width: "100%",
              maxHeight: "200px",
              overflowY: "auto",
              padding: "12px 16px",
              borderRadius: "12px",
              background:
                "var(--color-surface-soft, rgba(255,255,255,0.05))",
              border:
                "1px solid var(--color-accent-border, rgba(99,102,241,0.3))",
            }}
          >
            <div
              style={{
                fontSize: "10px",
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                color: "var(--color-accent, #6366f1)",
                marginBottom: "6px",
              }}
            >
              Assistant
            </div>
            <div
              style={{
                fontSize: "14px",
                color: "var(--color-text-primary, #e2e8f0)",
                lineHeight: 1.5,
              }}
            >
              {agentText}
            </div>
          </div>
        )}

        {/* Processing hint */}
        {isProcessing && !agentText && transcript && (
          <div
            style={{
              fontSize: "12px",
              color: "var(--color-text-secondary, #94a3b8)",
              fontStyle: "italic",
              textAlign: "center",
            }}
          >
            Generating response -- audio will play momentarily
          </div>
        )}

        {/* Action buttons */}
        <div style={{ display: "flex", gap: "12px", marginTop: "8px" }}>
          {(state === "streaming" || state === "speaking") && (
            <button
              onClick={onInterrupt}
              style={{
                padding: "10px 24px",
                borderRadius: "999px",
                background: "var(--color-warning, #f59e0b)",
                color: "white",
                fontSize: "13px",
                fontWeight: 600,
                border: "none",
                cursor: "pointer",
              }}
            >
              Interrupt
            </button>
          )}

          <button
            onClick={onStop}
            style={{
              padding: "10px 24px",
              borderRadius: "999px",
              background: "var(--color-danger, #ef4444)",
              color: "white",
              fontSize: "13px",
              fontWeight: 600,
              border: "none",
              cursor: "pointer",
            }}
          >
            End Conversation
          </button>
        </div>

        <div
          style={{
            fontSize: "11px",
            color: "var(--color-text-muted, #64748b)",
          }}
        >
          Press Esc or click outside to close
        </div>
      </div>
    </div>
  );
}
