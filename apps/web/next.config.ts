import type { NextConfig } from "next";

// Dev only: the browser talks to FastAPI cross-origin (ADR 0005). In prod the
// reverse proxy puts it on our own origin, so 'self' already covers it and the
// token is omitted.
function apiOrigin(): string {
  const raw = process.env.NEXT_PUBLIC_API_URL;
  if (!raw) return "";
  try {
    return new URL(raw).origin;
  } catch {
    return "";
  }
}

// Second wall behind components/chat/Markdown.tsx's image restriction: model
// output is untrusted (retrieved document text reaches it verbatim), so no
// rendered reply may reach another origin without a click. img-src/connect-src
// are the load-bearing directives; the rest close the usual framing and
// form-post exits.
// - 'unsafe-inline' in script-src is required by Next's inline bootstrap and
//   hydration scripts; a per-request nonce needs middleware + dynamic
//   rendering and is not in place yet.
// - 'unsafe-eval' is only Next dev's HMR/react-refresh and never ships to prod.
// - The Auth.js Google flow needs no extra origin: signIn() POSTs same-origin
//   and then assigns window.location (a top-level navigation, which CSP does
//   not restrict), so accounts.google.com is never a fetch or a form target.
function contentSecurityPolicy(): string {
  const api = apiOrigin();
  const dev = process.env.NODE_ENV !== "production";
  return [
    "default-src 'self'",
    "img-src 'self' data:",
    `connect-src 'self'${api ? ` ${api}` : ""}`,
    `script-src 'self' 'unsafe-inline'${dev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "font-src 'self' data:",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join("; ");
}

const nextConfig: NextConfig = {
  output: "standalone",
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "Content-Security-Policy", value: contentSecurityPolicy() },
        ],
      },
    ];
  },
};

export default nextConfig;
