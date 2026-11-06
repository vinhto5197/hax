// The browser's address as this server received it: the first x-forwarded-for
// entry, which Caddy sets. Sent to the internal auth routes as X-Visitor-IP,
// whose per-address limits would otherwise see only this server. Empty when
// absent, so the API falls back to the connection's address.
export function visitorIp(headers: Headers): string {
  return (headers.get("x-forwarded-for") ?? "").split(",")[0].trim();
}
