// A scripted stand-in for Anthropic's Messages API (reached by the API and the
// worker through ANTHROPIC_BASE_URL) and Voyage's embeddings API (through
// VOYAGE_BASE_URL). Messages speak the streaming wire format the SDK's
// messages.stream() helper consumes; the one non-streaming call served is the
// title request. Anything it cannot serve is answered with an error and a log
// line, so a new call path fails loudly instead of hanging.
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
//   which the SDK raises on (the API's model-failure path);
// - a prompt starting with "search:" answers with one search_documents
//   tool_use whose query is the rest of the prompt, trimmed (stop_reason
//   "tool_use"); the follow-up call, whose last user turn carries the
//   tool_result, waits 1.5 s and streams "Here is what your documents say.";
// - a prompt starting with "table:" streams a Markdown table of Item and
//   Count (Apples 10, Pears 9, Plums —, Figs 100);
// - a prompt starting with "code:" streams a fenced python greet() function,
//   then a Markdown image of https://example.com/chart.png;
// - a title request (non-streaming, carrying output_config) whose user
//   message starts with "title:" waits 2 s and answers the JSON title
//   "Fake model title"; every other title request is refused at once, so
//   every other conversation stays "Untitled". Any other non-streaming
//   request is a 400;
// - POST /v1/embeddings answers one 1024-dimension vector per input, the
//   same unit vector [1, 0, 0, ...] for every text, so every chunk is at
//   distance 0 from every query; when any input contains "slow-embed" the
//   answer waits 8 s, under the Voyage client's 15 s per-attempt timeout.
// The prompt is the last paragraph of the last user turn: the API merges
// consecutive user turns with a blank line, so a resend after a failure
// arrives appended to the failed question.
import http from "node:http";

const PORT = Number(process.env.FAKE_MODEL_PORT ?? 8787);
const SLOW_DELAY_MS = 300;
const FAIL_DELAY_MS = 500;
const LONG_DELAY_MS = 500;
const SEARCH_FOLLOW_UP_DELAY_MS = 1500;
const TITLE_DELAY_MS = 2000;
const SLOW_EMBED_DELAY_MS = 8000;
// Matches EMBEDDING_DIM (packages/db/models/chunk.py); the API checks it.
const EMBEDDING_DIM = 1024;

const TABLE_REPLY = [
  "| Item | Count |",
  "|---|---|",
  "| Apples | 10 |",
  "| Pears | 9 |",
  "| Plums | — |",
  "| Figs | 100 |",
].join("\n");
const CODE_REPLY = [
  "```python",
  "def greet(name):",
  '    return f"Hello, {name}"',
  "```",
  "",
  "![chart](https://example.com/chart.png)",
].join("\n");
const TITLE_REPLY = JSON.stringify({ title: "Fake model title" });

let messageCount = 0;
let toolUseCount = 0;

function log(line) {
  console.log(`fake-model: ${line}`);
}

function lastUserTurn(messages) {
  return [...(messages ?? [])].reverse().find((m) => m.role === "user");
}

function turnText(turn) {
  if (!turn) return "";
  return typeof turn.content === "string"
    ? turn.content
    : (turn.content ?? [])
        .filter((block) => block.type === "text")
        .map((block) => block.text)
        .join("");
}

function lastUserText(messages) {
  return turnText(lastUserTurn(messages)).split("\n\n").at(-1);
}

function carriesToolResult(turn) {
  return (
    Array.isArray(turn?.content) &&
    turn.content.some((block) => block.type === "tool_result")
  );
}

// One reply: text pieces streamed delayMs apart after leadMs, or a single
// tool_use block.
function scriptReply(messages) {
  if (carriesToolResult(lastUserTurn(messages))) {
    return {
      pieces: ["Here is what your documents say."],
      leadMs: SEARCH_FOLLOW_UP_DELAY_MS,
    };
  }
  const prompt = lastUserText(messages);
  if (prompt.startsWith("search:")) {
    return {
      toolUse: {
        name: "search_documents",
        input: { query: prompt.slice("search:".length).trim() },
      },
    };
  }
  if (prompt.startsWith("table:")) {
    return { pieces: TABLE_REPLY.split(/(?<=\n)/) };
  }
  if (prompt.startsWith("code:")) {
    return { pieces: CODE_REPLY.split(/(?<=\n)/) };
  }
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
  return { pieces: ["Hello ", "from the ", "fake model."] };
}

function sendJson(res, status, body) {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
}

function sendError(res, status, type, message) {
  sendJson(res, status, { type: "error", error: { type, message } });
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function streamReply(req, res, body) {
  const {
    pieces = [],
    toolUse,
    delayMs = 0,
    leadMs = 0,
    fail,
  } = scriptReply(body.messages);
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

  if (toolUse) {
    toolUseCount += 1;
    send("content_block_start", {
      index: 0,
      content_block: {
        type: "tool_use",
        id: `toolu_fake_${toolUseCount}`,
        name: toolUse.name,
        input: {},
      },
    });
    send("content_block_delta", {
      index: 0,
      delta: {
        type: "input_json_delta",
        partial_json: JSON.stringify(toolUse.input),
      },
    });
    send("content_block_stop", { index: 0 });
    send("message_delta", {
      delta: { stop_reason: "tool_use", stop_sequence: null },
      usage: { output_tokens: 1 },
    });
    send("message_stop", {});
    res.end();
    return;
  }

  send("content_block_start", {
    index: 0,
    content_block: { type: "text", text: "" },
  });
  if (leadMs > 0) await sleep(leadMs);
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

async function answerTitle(res, body) {
  messageCount += 1;
  const granted = turnText(lastUserTurn(body.messages)).startsWith("title:");
  if (granted) await sleep(TITLE_DELAY_MS);
  sendJson(res, 200, {
    id: `msg_fake_${messageCount}`,
    type: "message",
    role: "assistant",
    model: body.model,
    content: granted ? [{ type: "text", text: TITLE_REPLY }] : [],
    stop_reason: granted ? "end_turn" : "refusal",
    stop_sequence: null,
    usage: { input_tokens: 10, output_tokens: granted ? 8 : 0 },
  });
}

async function answerEmbeddings(res, body) {
  const inputs = Array.isArray(body.input) ? body.input : [body.input ?? ""];
  if (inputs.some((text) => String(text).includes("slow-embed"))) {
    await sleep(SLOW_EMBED_DELAY_MS);
  }
  const vector = Array.from({ length: EMBEDDING_DIM }, (_, i) =>
    i === 0 ? 1 : 0,
  );
  // A JSON array, not base64: the SDK decodes the embedding only when it is a
  // string, and passes a list through.
  sendJson(res, 200, {
    object: "list",
    data: inputs.map((_, index) => ({
      object: "embedding",
      embedding: vector,
      index,
    })),
    model: body.model,
    usage: { total_tokens: inputs.length },
  });
}

function handleMessages(req, res, body) {
  if (body.stream === true) {
    return streamReply(req, res, body);
  }
  if (body.output_config !== undefined) {
    return answerTitle(res, body);
  }
  log("400 non-streaming request");
  sendError(
    res,
    400,
    "invalid_request_error",
    "fake model: only streaming is supported",
  );
  return Promise.resolve();
}

const ROUTES = {
  "/v1/messages": handleMessages,
  "/v1/embeddings": (req, res, body) => answerEmbeddings(res, body),
};

const server = http.createServer((req, res) => {
  if (req.method === "GET" && req.url === "/") {
    res.writeHead(200, { "content-type": "text/plain" });
    res.end("ok");
    return;
  }
  const path = (req.url ?? "").split("?")[0];
  const route = req.method === "POST" ? ROUTES[path] : undefined;
  if (!route) {
    log(`404 ${req.method} ${req.url}`);
    sendError(res, 404, "not_found_error", "fake model: no such route");
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
      sendError(
        res,
        400,
        "invalid_request_error",
        "fake model: body is not JSON",
      );
      return;
    }
    route(req, res, body).catch((err) => {
      log(`${path} failed: ${err}`);
      res.destroy();
    });
  });
});

server.listen(PORT, () => log(`listening on ${PORT}`));
