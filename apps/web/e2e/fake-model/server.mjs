// A scripted stand-in for Anthropic's Messages API, reached by the API through
// ANTHROPIC_BASE_URL. It speaks only the streaming wire format the SDK's
// messages.stream() helper consumes, and never returns tool_use, so the agent
// loop ends after one iteration. Anything it cannot serve is answered with an
// error and a log line, so a new call path fails loudly instead of hanging.
// Never script a search_documents tool_use: Voyage has no base-URL override,
// so the query would leave the machine for the real api.voyageai.com.
//
// Test contract (the journeys assert on these strings):
// - default reply: "Hello from the fake model." in three deltas;
// - a prompt starting with "slow:" streams ten "Slowly streaming reply, part
//   N. " deltas, 300 ms apart;
// - a prompt starting with "long:" streams twenty "Long reply, part N. "
//   deltas, 500 ms apart (about ten seconds), long enough to reload, switch
//   away or go offline while the reply is certainly still running;
// - a prompt starting with "fail:" streams "Failing reply, part N. " for N =
//   1..3, 500 ms apart, then destroys the connection without message_stop,
//   which the SDK raises on (the API's model-failure path).
// The prompt is the last paragraph of the last user turn: the API merges
// consecutive user turns with a blank line, so a resend after a failure
// arrives appended to the failed question.
import http from "node:http";

const PORT = Number(process.env.FAKE_MODEL_PORT ?? 8787);
const SLOW_DELAY_MS = 300;
const FAIL_DELAY_MS = 500;
const LONG_DELAY_MS = 500;

let messageCount = 0;

function log(line) {
  console.log(`fake-model: ${line}`);
}

function lastUserText(messages) {
  const last = [...(messages ?? [])].reverse().find((m) => m.role === "user");
  if (!last) return "";
  const text =
    typeof last.content === "string"
      ? last.content
      : (last.content ?? [])
          .filter((block) => block.type === "text")
          .map((block) => block.text)
          .join("");
  return text.split("\n\n").at(-1);
}

function replyPieces(prompt) {
  if (prompt.startsWith("slow:")) {
    return {
      pieces: Array.from(
        { length: 10 },
        (_, i) => `Slowly streaming reply, part ${i + 1}. `,
      ),
      delayMs: SLOW_DELAY_MS,
    };
  }
  if (prompt.startsWith("long:")) {
    return {
      pieces: Array.from(
        { length: 20 },
        (_, i) => `Long reply, part ${i + 1}. `,
      ),
      delayMs: LONG_DELAY_MS,
    };
  }
  if (prompt.startsWith("fail:")) {
    return {
      pieces: Array.from(
        { length: 3 },
        (_, i) => `Failing reply, part ${i + 1}. `,
      ),
      delayMs: FAIL_DELAY_MS,
      fail: true,
    };
  }
  return { pieces: ["Hello ", "from the ", "fake model."], delayMs: 0 };
}

function sendJson(res, status, body) {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function streamReply(req, res, body) {
  const { pieces, delayMs, fail } = replyPieces(lastUserText(body.messages));
  let closed = false;
  res.on("close", () => {
    closed = true;
  });
  const send = (type, data) => {
    if (closed) return;
    res.write(`event: ${type}\ndata: ${JSON.stringify({ type, ...data })}\n\n`);
  };

  messageCount += 1;
  res.writeHead(200, {
    "content-type": "text/event-stream",
    "cache-control": "no-cache",
  });
  send("message_start", {
    message: {
      id: `msg_fake_${messageCount}`,
      type: "message",
      role: "assistant",
      model: body.model,
      content: [],
      stop_reason: null,
      stop_sequence: null,
      usage: {
        input_tokens: 10,
        output_tokens: 0,
        cache_creation_input_tokens: 0,
        cache_read_input_tokens: 0,
      },
    },
  });
  send("content_block_start", {
    index: 0,
    content_block: { type: "text", text: "" },
  });
  for (const [i, piece] of pieces.entries()) {
    if (closed) {
      log("client disconnected mid-stream");
      return;
    }
    if (i > 0 && delayMs > 0) await sleep(delayMs);
    send("content_block_delta", {
      index: 0,
      delta: { type: "text_delta", text: piece },
    });
  }
  if (fail) {
    // The wait lets the last delta flush before the cut discards the buffer.
    await sleep(delayMs);
    log("cutting the stream before message_stop");
    res.destroy();
    return;
  }
  send("content_block_stop", { index: 0 });
  send("message_delta", {
    delta: { stop_reason: "end_turn", stop_sequence: null },
    usage: { output_tokens: pieces.length },
  });
  send("message_stop", {});
  res.end();
}

const server = http.createServer((req, res) => {
  if (req.method === "GET" && req.url === "/") {
    res.writeHead(200, { "content-type": "text/plain" });
    res.end("ok");
    return;
  }
  const path = (req.url ?? "").split("?")[0];
  if (req.method !== "POST" || path !== "/v1/messages") {
    log(`404 ${req.method} ${req.url}`);
    sendJson(res, 404, {
      type: "error",
      error: { type: "not_found_error", message: "fake model: no such route" },
    });
    return;
  }

  let raw = "";
  req.setEncoding("utf8");
  req.on("data", (chunk) => {
    raw += chunk;
  });
  req.on("end", () => {
    let body;
    try {
      body = JSON.parse(raw);
    } catch {
      log("400 body is not JSON");
      sendJson(res, 400, {
        type: "error",
        error: {
          type: "invalid_request_error",
          message: "fake model: body is not JSON",
        },
      });
      return;
    }
    if (body.stream !== true) {
      log("400 non-streaming request");
      sendJson(res, 400, {
        type: "error",
        error: {
          type: "invalid_request_error",
          message: "fake model: only streaming is supported",
        },
      });
      return;
    }
    streamReply(req, res, body).catch((err) => {
      log(`stream failed: ${err}`);
      res.destroy();
    });
  });
});

server.listen(PORT, () => log(`listening on ${PORT}`));
