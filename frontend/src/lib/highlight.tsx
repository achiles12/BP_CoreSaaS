// Highlight search words in plain text (B10 D7). The API snippet is plain
// text (B07 D11); splitting here keeps everything React-escaped, so a title
// containing "<b>" shows as text and never becomes markup.
import { Fragment } from "react";

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function Highlight({ text, query }: { text: string; query: string }) {
  const words = Array.from(new Set(query.trim().split(/\s+/).filter(Boolean)));
  if (!text || words.length === 0) return <>{text}</>;
  // Longest first, so "plan" does not shadow "planning".
  words.sort((a, b) => b.length - a.length);
  const re = new RegExp(`(${words.map(escapeRegExp).join("|")})`, "gi");
  const lower = new Set(words.map((w) => w.toLowerCase()));
  return (
    <>
      {text.split(re).map((part, i) =>
        lower.has(part.toLowerCase()) ? (
          <mark key={i} className="bg-yellow-200/70 text-inherit dark:bg-yellow-500/30">
            {part}
          </mark>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </>
  );
}
