import type { Page } from "@playwright/test";

// Chromium's offline emulation does not cut a response already streaming, so
// a journey cuts the page's /api/chat stream itself: installStreamCut wraps
// window.fetch, and cutStream fails the relayed body and aborts the real
// request, so the browser closes the connection and the server sees the
// client leave. Every other request goes to the real fetch untouched.
const REGISTRY = "__haxOpenChatStreams";

// Resolves once the real body's read has rejected with the abort, the
// browser's sign that the real connection is closed; rejects otherwise.
type Cut = () => Promise<void>;

// Call before the page's first navigation: the init script must replace
// fetch before the app first calls it.
export async function installStreamCut(page: Page): Promise<void> {
  await page.addInitScript((key: string) => {
    // One entry per wrapped stream between its response and its EOF or
    // error, so a finished earlier turn is never cut.
    const open = new Set<Cut>();
    (window as unknown as Record<string, Set<Cut>>)[key] = open;
    const realFetch = window.fetch.bind(window);

    window.fetch = async (input, init) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url;
      const method = (
        init?.method ?? (input instanceof Request ? input.method : "GET")
      ).toUpperCase();
      if (
        method !== "POST" ||
        !new URL(url, location.href).pathname.endsWith("/api/chat")
      ) {
        return realFetch(input, init);
      }

      const abort = new AbortController();
      const callerSignal =
        init?.signal ?? (input instanceof Request ? input.signal : null);
      if (callerSignal) {
        if (callerSignal.aborted) abort.abort(callerSignal.reason);
        else
          callerSignal.addEventListener(
            "abort",
            () => abort.abort(callerSignal.reason),
            { once: true },
          );
      }

      const response = await realFetch(input, {
        ...init,
        signal: abort.signal,
      });
      if (!response.body) return response;

      const reader = response.body.getReader();
      let errored = false;
      let relayController!: ReadableStreamDefaultController<Uint8Array>;
      const cut: Cut = async () => {
        errored = true;
        open.delete(cut);
        // Erroring the relay must come before the abort: the abort rejects
        // the pending read, and the pump would error the relay with an
        // AbortError instead of a dropped connection's TypeError.
        relayController.error(new TypeError("network error"));
        abort.abort();
        let outcome: string;
        try {
          const chunk = await Promise.race([
            reader.read(),
            new Promise<never>((_, reject) =>
              setTimeout(() => reject(new Error("no answer in 2 s")), 2000),
            ),
          ]);
          outcome = chunk.done ? "ended" : "still delivering";
        } catch (error) {
          if (error instanceof DOMException && error.name === "AbortError") {
            return;
          }
          outcome = `failed with ${String(error)}`;
        }
        throw new Error(
          `cutStream: the real /api/chat body ${outcome} after the abort`,
        );
      };
      const relay = new ReadableStream<Uint8Array>({
        start(controller) {
          relayController = controller;
          open.add(cut);
        },
        async pull(controller) {
          try {
            const chunk = await reader.read();
            if (errored) return;
            if (chunk.done) {
              open.delete(cut);
              controller.close();
            } else {
              controller.enqueue(chunk.value);
            }
          } catch (error) {
            if (errored) return;
            open.delete(cut);
            controller.error(error);
          }
        },
        // The client's silence limit cancels its reader; that must close the
        // real connection too.
        cancel(reason) {
          open.delete(cut);
          return reader.cancel(reason);
        },
      });

      return new Response(relay, {
        status: response.status,
        statusText: response.statusText,
        headers: response.headers,
      });
    };
  }, REGISTRY);
}

// Throws when no wrapped stream is open, or when a real body is not closed by
// its abort: a journey that cuts nothing, or cuts only the relay, fails.
export async function cutStream(page: Page): Promise<void> {
  await page.evaluate(async (key: string) => {
    const open = (window as unknown as Record<string, Set<Cut> | undefined>)[
      key
    ];
    if (!open || open.size === 0) {
      throw new Error("cutStream: no open /api/chat stream to cut");
    }
    await Promise.all([...open].map((cut) => cut()));
  }, REGISTRY);
}
