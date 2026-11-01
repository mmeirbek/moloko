"use client";

import { useMessagePartText } from "@assistant-ui/react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

/**
 * Model output rendered as Markdown. Raw HTML in the output is NOT rendered
 * (react-markdown escapes it by default), so a model cannot inject markup.
 */
export function MarkdownBody({ text }: { text: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer nofollow">
              {children}
            </a>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

export function MarkdownText() {
  const { text } = useMessagePartText();
  return <MarkdownBody text={text} />;
}
