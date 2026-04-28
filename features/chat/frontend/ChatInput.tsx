/**
 * ChatInput Component
 *
 * Multi-modal chat input with:
 * - Text input with auto-resize
 * - Image attachment support
 * - Inline voice recording with transcription
 * - Send / Cancel streaming controls
 *
 * Generic: transcription endpoint is configurable via props.
 */

import {
  useState,
  KeyboardEvent,
  useRef,
  useEffect,
  useCallback,
  ChangeEvent,
} from "react";
import type { ImageAttachment } from "./types";

// ---------------------------------------------------------------------------
// Inline audioBufferToWav (zero-dependency WAV encoder)
// ---------------------------------------------------------------------------

function audioBufferToWav(
  buffer: AudioBuffer,
  targetSampleRate = 16000
): Blob {
  let samples: Float32Array;
  if (buffer.numberOfChannels === 1) {
    samples = buffer.getChannelData(0);
  } else {
    const left = buffer.getChannelData(0);
    const right = buffer.getChannelData(1);
    samples = new Float32Array(left.length);
    for (let i = 0; i < left.length; i++) {
      samples[i] = (left[i] + right[i]) / 2;
    }
  }

  if (buffer.sampleRate !== targetSampleRate) {
    const ratio = buffer.sampleRate / targetSampleRate;
    const newLength = Math.round(samples.length / ratio);
    const resampled = new Float32Array(newLength);
    for (let i = 0; i < newLength; i++) {
      resampled[i] = samples[Math.round(i * ratio)];
    }
    samples = resampled;
  }

  const int16 = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }

  const wavBuffer = new ArrayBuffer(44 + int16.length * 2);
  const view = new DataView(wavBuffer);
  const writeString = (offset: number, str: string) => {
    for (let i = 0; i < str.length; i++)
      view.setUint8(offset + i, str.charCodeAt(i));
  };

  writeString(0, "RIFF");
  view.setUint32(4, 36 + int16.length * 2, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, targetSampleRate, true);
  view.setUint32(28, targetSampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, int16.length * 2, true);

  const output = new Uint8Array(wavBuffer);
  output.set(new Uint8Array(int16.buffer), 44);

  return new Blob([wavBuffer], { type: "audio/wav" });
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ChatInputProps {
  onSubmit: (message: string, images?: ImageAttachment[]) => void;
  onCancel?: () => void;
  disabled?: boolean;
  isStreaming?: boolean;
  placeholder?: string;
  /** Endpoint for ASR transcription. If omitted, mic button is hidden. */
  transcribeEndpoint?: string;
  /** Maximum number of image attachments. Default: 4. */
  maxImages?: number;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ChatInput({
  onSubmit,
  onCancel,
  disabled = false,
  isStreaming = false,
  placeholder = "Ask a question...",
  transcribeEndpoint,
  maxImages = 4,
}: ChatInputProps) {
  const [value, setValue] = useState("");
  const [images, setImages] = useState<ImageAttachment[]>([]);
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  // Auto-resize textarea
  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
    }
  }, [value]);

  const handleSubmit = () => {
    if (
      (value.trim() || images.length > 0) &&
      !disabled &&
      !isStreaming
    ) {
      onSubmit(
        value.trim(),
        images.length > 0 ? images : undefined
      );
      setValue("");
      setImages([]);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleImageSelect = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;

    const newImages: ImageAttachment[] = [];

    for (const file of Array.from(files)) {
      if (!file.type.startsWith("image/")) continue;
      if (file.size > 10 * 1024 * 1024) {
        alert(`Image ${file.name} is too large. Maximum size is 10MB.`);
        continue;
      }

      const preview = URL.createObjectURL(file);
      const base64 = await new Promise<string>((resolve) => {
        const reader = new FileReader();
        reader.onloadend = () => {
          const result = reader.result as string;
          resolve(result.split(",")[1]);
        };
        reader.readAsDataURL(file);
      });

      newImages.push({ file, preview, base64 });
    }

    setImages((prev) => [...prev, ...newImages].slice(0, maxImages));
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const removeImage = (index: number) => {
    setImages((prev) => {
      const updated = [...prev];
      URL.revokeObjectURL(updated[index].preview);
      updated.splice(index, 1);
      return updated;
    });
  };

  // --- Audio recording ---
  const startRecording = useCallback(async () => {
    if (!transcribeEndpoint) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: true,
      });
      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: "audio/webm",
      });
      mediaRecorderRef.current = mediaRecorder;
      chunksRef.current = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      mediaRecorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());

        const webmBlob = new Blob(chunksRef.current, {
          type: "audio/webm",
        });
        if (webmBlob.size === 0) return;

        setIsTranscribing(true);
        try {
          const audioCtx = new AudioContext();
          const arrayBuffer = await webmBlob.arrayBuffer();
          const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
          const wavBlob = audioBufferToWav(audioBuffer, 16000);
          audioCtx.close();

          const formData = new FormData();
          formData.append("file", wavBlob, "recording.wav");

          const resp = await fetch(transcribeEndpoint, {
            method: "POST",
            body: formData,
          });

          if (!resp.ok)
            throw new Error(
              `Transcription failed: ${resp.statusText}`
            );

          const data = await resp.json();
          if (data.text) {
            setValue((prev) =>
              prev ? prev + " " + data.text : data.text
            );
            textareaRef.current?.focus();
          }
        } catch (err) {
          console.error("[ChatInput] Transcription error:", err);
        } finally {
          setIsTranscribing(false);
        }
      };

      mediaRecorder.start();
      setIsRecording(true);
    } catch (err) {
      console.error("[ChatInput] Microphone access denied:", err);
    }
  }, [transcribeEndpoint]);

  const stopRecording = useCallback(() => {
    if (
      mediaRecorderRef.current &&
      mediaRecorderRef.current.state !== "inactive"
    ) {
      mediaRecorderRef.current.stop();
    }
    setIsRecording(false);
  }, []);

  const toggleRecording = useCallback(() => {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  }, [isRecording, startRecording, stopRecording]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      images.forEach((img) => URL.revokeObjectURL(img.preview));
      if (
        mediaRecorderRef.current &&
        mediaRecorderRef.current.state !== "inactive"
      ) {
        mediaRecorderRef.current.stop();
      }
    };
  }, []);

  return (
    <div
      className="border-t p-4"
      style={{
        borderColor: "var(--color-border-subtle)",
        background: "var(--color-bg-elevated)",
      }}
    >
      {/* Image previews */}
      {images.length > 0 && (
        <div className="flex gap-2 mb-3 flex-wrap">
          {images.map((img, idx) => (
            <div
              key={idx}
              className="relative w-16 h-16 rounded-lg overflow-hidden"
              style={{
                border: "1px solid var(--color-border-strong)",
              }}
            >
              <img
                src={img.preview}
                alt={`Attachment ${idx + 1}`}
                className="w-full h-full object-cover"
              />
              <button
                onClick={() => removeImage(idx)}
                className="absolute top-0 right-0 p-0.5 rounded-bl-lg"
                style={{
                  background: "rgba(0,0,0,0.6)",
                  color: "white",
                }}
              >
                {"\u2715"}
              </button>
            </div>
          ))}
        </div>
      )}

      <div
        className="flex items-end gap-2 rounded-lg p-2"
        style={{
          background: "var(--color-surface-soft)",
          border: "1px solid var(--color-border-strong)",
        }}
      >
        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          multiple
          onChange={handleImageSelect}
          className="hidden"
        />

        {/* Image upload button */}
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled || isStreaming || images.length >= maxImages}
          className="p-2 rounded-lg transition-colors disabled:opacity-50"
          style={{ color: "var(--color-text-secondary)" }}
          title="Attach image"
        >
          {"\u{1F4CE}"}
        </button>

        {/* Microphone button (only if transcribeEndpoint is set) */}
        {transcribeEndpoint && (
          <button
            onClick={toggleRecording}
            disabled={disabled || isStreaming || isTranscribing}
            className="p-2 rounded-lg transition-colors disabled:opacity-50"
            style={{
              color: isRecording
                ? "var(--color-danger)"
                : "var(--color-text-secondary)",
              background: isRecording
                ? "rgba(239,68,68,0.1)"
                : "transparent",
            }}
            title={
              isRecording
                ? "Stop recording"
                : isTranscribing
                ? "Transcribing..."
                : "Voice input"
            }
          >
            {isTranscribing
              ? "..."
              : isRecording
              ? "\u{1F534}"
              : "\u{1F3A4}"}
          </button>
        )}

        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            isRecording
              ? "Listening..."
              : isTranscribing
              ? "Transcribing..."
              : placeholder
          }
          disabled={disabled}
          rows={1}
          className="flex-1 bg-transparent border-none outline-none resize-none text-sm"
          style={{
            color: "var(--color-text-primary)",
            minHeight: "24px",
            maxHeight: "200px",
          }}
        />

        {isStreaming ? (
          <button
            onClick={onCancel}
            className="p-2 rounded-lg transition-colors"
            style={{
              background: "var(--color-danger)",
              color: "white",
            }}
            title="Stop generating"
          >
            {"\u25A0"}
          </button>
        ) : (
          <button
            onClick={handleSubmit}
            disabled={
              (!value.trim() && images.length === 0) || disabled
            }
            className="p-2 rounded-lg transition-colors disabled:opacity-50"
            style={{
              background:
                value.trim() || images.length > 0
                  ? "var(--color-accent)"
                  : "var(--color-border-strong)",
              color: "white",
            }}
            title="Send message"
          >
            {"\u27A4"}
          </button>
        )}
      </div>

      <div
        className="flex justify-between items-center mt-2 text-xs"
        style={{ color: "var(--color-text-muted)" }}
      >
        <span>
          {isRecording
            ? "Recording... click mic to stop"
            : isTranscribing
            ? "Transcribing audio..."
            : "Press Enter to send, Shift+Enter for new line"}
        </span>
        {isStreaming && <span>Generating response...</span>}
      </div>
    </div>
  );
}
