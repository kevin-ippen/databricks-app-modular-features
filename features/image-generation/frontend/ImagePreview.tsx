/**
 * Image preview component for generated or analyzed images.
 * Displays base64 or URL images with download capability.
 */
import React, { useState } from "react";

interface ImagePreviewProps {
  /** Base64 data URI or URL of the image. */
  src: string | null;
  /** Alt text for accessibility. */
  alt?: string;
  /** Optional caption or analysis text to display below the image. */
  caption?: string;
  /** Whether the image is still loading/generating. */
  loading?: boolean;
  /** Max width in pixels. Default: 512. */
  maxWidth?: number;
  /** Callback when download button is clicked. */
  onDownload?: () => void;
}

export function ImagePreview({
  src,
  alt = "Generated image",
  caption,
  loading = false,
  maxWidth = 512,
  onDownload,
}: ImagePreviewProps) {
  const [expanded, setExpanded] = useState(false);

  if (loading) {
    return (
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "center",
        width: maxWidth, height: maxWidth * 0.75,
        border: "1px dashed var(--color-border, #e2e8f0)",
        borderRadius: 8, backgroundColor: "var(--color-bg-subtle, #f8fafc)",
      }}>
        <span style={{ color: "var(--color-text-muted, #94a3b8)" }}>Generating...</span>
      </div>
    );
  }

  if (!src) return null;

  const handleDownload = () => {
    if (onDownload) {
      onDownload();
      return;
    }
    const link = document.createElement("a");
    link.href = src;
    link.download = `generated-${Date.now()}.png`;
    link.click();
  };

  return (
    <div style={{ maxWidth }}>
      <img
        src={src}
        alt={alt}
        onClick={() => setExpanded(!expanded)}
        style={{
          width: "100%", borderRadius: 8,
          cursor: "pointer",
          maxHeight: expanded ? "none" : maxWidth * 0.75,
          objectFit: expanded ? "contain" : "cover",
          transition: "max-height 0.2s ease",
        }}
      />
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        marginTop: 8, gap: 8,
      }}>
        {caption && (
          <p style={{
            margin: 0, fontSize: 13, flex: 1,
            color: "var(--color-text-muted, #64748b)",
            lineHeight: 1.4,
          }}>{caption}</p>
        )}
        <button
          onClick={handleDownload}
          title="Download image"
          style={{
            background: "none", border: "1px solid var(--color-border, #e2e8f0)",
            borderRadius: 6, padding: "4px 10px", cursor: "pointer",
            fontSize: 12, color: "var(--color-text-muted, #64748b)",
            flexShrink: 0,
          }}
        >
          Download
        </button>
      </div>
    </div>
  );
}
