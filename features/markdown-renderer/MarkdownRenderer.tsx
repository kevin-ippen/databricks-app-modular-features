/**
 * Markdown renderer component with CSS-variable theming for light/dark mode.
 *
 * Peer dependencies:
 *   - react (>=17)
 *   - react-markdown (>=9)
 *   - remark-gfm (>=4)
 *   - rehype-raw (>=7)
 *
 * CSS variables consumed (define in your app's root theme):
 *   --color-text-primary     Main text color
 *   --color-accent           Link / inline-code highlight
 *   --color-accent-soft      Inline-code background
 *   --radius-sm              Border radius for code blocks / tables
 *
 * Usage:
 *   import { MarkdownRenderer } from "features/markdown-renderer/MarkdownRenderer";
 *   <MarkdownRenderer>{"# Hello\nSome **markdown** here."}</MarkdownRenderer>
 */

import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";

interface MarkdownRendererProps {
  /** Raw markdown string to render. */
  children: string;
  /** Optional CSS class applied to the wrapper div. */
  className?: string;
}

export function MarkdownRenderer({
  children,
  className,
}: MarkdownRendererProps) {
  return (
    <div
      className={className}
      style={{
        color: "var(--color-text-primary, #1e293b)",
        lineHeight: 1.65,
        fontSize: "0.9rem",
      }}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw]}
        components={{
          /* ------ Headings ------ */
          h1: ({ node, ...props }) => (
            <h1
              style={{
                color: "var(--color-text-primary, #1e293b)",
                marginBottom: "0.5em",
              }}
              {...props}
            />
          ),
          h2: ({ node, ...props }) => (
            <h2
              style={{
                color: "var(--color-text-primary, #1e293b)",
                marginBottom: "0.5em",
              }}
              {...props}
            />
          ),
          h3: ({ node, ...props }) => (
            <h3
              style={{
                color: "var(--color-text-primary, #1e293b)",
                marginBottom: "0.5em",
              }}
              {...props}
            />
          ),

          /* ------ Code (inline + block) ------ */
          code: ({ node, className: codeClass, children: codeChildren, ...props }) => {
            const match = /language-(\w+)/.exec(codeClass || "");
            const isInline = !match;

            if (isInline) {
              return (
                <code
                  style={{
                    background: "var(--color-accent-soft, rgba(59,130,246,0.1))",
                    color: "var(--color-accent, #3b82f6)",
                    padding: "0.1em 0.3em",
                    borderRadius: "3px",
                    fontSize: "0.9em",
                  }}
                  {...props}
                >
                  {codeChildren}
                </code>
              );
            }

            return (
              <pre
                style={{
                  background: "rgba(15, 23, 42, 0.8)",
                  border: "1px solid rgba(30, 41, 59, 0.8)",
                  borderRadius: "var(--radius-sm, 6px)",
                  padding: "1em",
                  overflow: "auto",
                }}
              >
                <code className={codeClass} {...props}>
                  {codeChildren}
                </code>
              </pre>
            );
          },

          /* ------ Links ------ */
          a: ({ node, ...props }) => (
            <a
              style={{
                color: "var(--color-accent, #3b82f6)",
                textDecoration: "underline",
              }}
              target="_blank"
              rel="noopener noreferrer"
              {...props}
            />
          ),

          /* ------ Lists ------ */
          ul: ({ node, ...props }) => (
            <ul
              style={{ color: "var(--color-text-primary, #1e293b)" }}
              {...props}
            />
          ),
          ol: ({ node, ...props }) => (
            <ol
              style={{ color: "var(--color-text-primary, #1e293b)" }}
              {...props}
            />
          ),

          /* ------ Paragraph ------ */
          p: ({ node, ...props }) => (
            <p
              style={{
                color: "var(--color-text-primary, #1e293b)",
                marginBottom: "0.75em",
              }}
              {...props}
            />
          ),

          /* ------ Table ------ */
          table: ({ node, ...props }) => (
            <div style={{ overflowX: "auto", marginBottom: "1em" }}>
              <table
                style={{
                  width: "100%",
                  borderCollapse: "collapse",
                  fontSize: "0.85em",
                  border: "1px solid rgba(71, 85, 105, 0.5)",
                  borderRadius: "var(--radius-sm, 6px)",
                }}
                {...props}
              />
            </div>
          ),
          thead: ({ node, ...props }) => (
            <thead
              style={{
                background: "rgba(30, 41, 59, 0.8)",
                borderBottom: "2px solid rgba(71, 85, 105, 0.6)",
              }}
              {...props}
            />
          ),
          th: ({ node, ...props }) => (
            <th
              style={{
                padding: "0.5em 0.75em",
                textAlign: "left",
                color: "var(--color-text-primary, #1e293b)",
                fontWeight: 600,
                whiteSpace: "nowrap",
              }}
              {...props}
            />
          ),
          td: ({ node, ...props }) => (
            <td
              style={{
                padding: "0.5em 0.75em",
                borderBottom: "1px solid rgba(71, 85, 105, 0.3)",
                color: "var(--color-text-primary, #1e293b)",
              }}
              {...props}
            />
          ),
          tr: ({ node, ...props }) => (
            <tr
              style={{
                borderBottom: "1px solid rgba(71, 85, 105, 0.3)",
              }}
              {...props}
            />
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}

export default MarkdownRenderer;
