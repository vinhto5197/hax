import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface MarkdownProps {
  content: string;
}

// Tailwind Typography's default `prose` is print-document sized — too big for
// chat bubbles. `prose-sm` matches the bubble's text-sm; the override classes
// strip the default vertical margins so consecutive paragraphs don't blow the
// bubble open, and tighten heading sizes.
const PROSE_CLASSES = [
  "prose prose-sm dark:prose-invert max-w-none",
  "prose-p:my-2 prose-p:first:mt-0 prose-p:last:mb-0",
  "prose-headings:my-2 prose-headings:font-semibold",
  "prose-h1:text-base prose-h2:text-base prose-h3:text-sm",
  "prose-pre:my-2 prose-pre:bg-black/10 dark:prose-pre:bg-white/10",
  "prose-code:before:content-none prose-code:after:content-none",
  "prose-ul:my-2 prose-ol:my-2 prose-li:my-0",
].join(" ");

export function Markdown({ content }: MarkdownProps) {
  return (
    <div className={PROSE_CLASSES}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}
