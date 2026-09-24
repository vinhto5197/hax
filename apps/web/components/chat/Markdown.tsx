import ReactMarkdown, {
  defaultUrlTransform,
  type UrlTransform,
} from "react-markdown";
import remarkGfm from "remark-gfm";

interface MarkdownProps {
  content: string;
}

// Invariant: a rendered reply may never cause an automatic (zero-click) request
// to another origin. Cross-module contract: this renders model output, and
// retrieved document text reaches the model verbatim as tool results
// (packages/core/agent/tools.py), so an uploaded file can author what appears
// here — an image URL is fetched on render, which makes it an exfiltration
// channel for whatever the model holds in context. Image sources are therefore
// restricted to our own origin; the CSP in next.config.ts is the second wall.
// Links keep react-markdown's default treatment: following one is a user act.
const urlTransform: UrlTransform = (url, key, node) => {
  const safe = defaultUrlTransform(url);
  if (node.tagName !== "img" || key !== "src") return safe;
  // "//host/x" is another origin despite the leading slash, and anything still
  // carrying a scheme is remote (defaultUrlTransform has already emptied the
  // dangerous ones), so only genuinely relative sources survive. Dropping the
  // attribute — rather than emptying it — is what keeps the browser from
  // re-requesting the current page for an empty src.
  const isRelative =
    safe !== "" &&
    !safe.startsWith("//") &&
    (safe.startsWith("/") || !/^[a-z][a-z\d+\-.]*:/i.test(safe));
  return isRelative ? safe : undefined;
};

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
      <ReactMarkdown remarkPlugins={[remarkGfm]} urlTransform={urlTransform}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
