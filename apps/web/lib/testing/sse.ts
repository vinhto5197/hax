// Test-only. A streamed Response whose body yields exactly these reads, so a
// test decides where the network splits an event (or a UTF-8 character).
export function sseResponse(reads: Array<string | Uint8Array>): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const read of reads) {
        controller.enqueue(
          typeof read === "string" ? encoder.encode(read) : read,
        );
      }
      controller.close();
    },
  });
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

export function sseEvent(data: unknown): string {
  return `data: ${typeof data === "string" ? data : JSON.stringify(data)}\n\n`;
}
