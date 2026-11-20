// Real JavaScript/TypeScript workflow: native type stripping, an HTTP server,
// fetch with AbortSignal, explicit status codes and a 404 path.
//
// Run from the repository root:
//
//     node examples/packs/js_ts_example.ts
//
// examples/packs/package.json sets "type": "module", so this .ts file is ESM
// and Node strips the type annotations without a compiler. It prints
// JS_TS_PACK_OK only when every check passes.

import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

interface Health {
  ok: boolean;
  runtime: string;
  typescript: string;
}

type Json = Record<string, unknown>;

function health(runtime: string, typescript: string): Health {
  return { ok: true, runtime, typescript };
}

function send(res: ServerResponse, status: number, payload: Json): void {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
    "x-content-type-options": "nosniff",
  });
  res.end(body);
}

const server = createServer((req: IncomingMessage, res: ServerResponse) => {
  const path = new URL(req.url ?? "/", "http://127.0.0.1").pathname;
  if (path === "/health") {
    const runtime = process.version;
    const typescript = String(process.features.typescript);
    send(res, 200, health(runtime, typescript));
    return;
  }
  send(res, 404, { ok: false, error: "not_found" });
});

await new Promise<void>((resolve, reject) => {
  server.once("error", reject);
  server.listen(0, "127.0.0.1", resolve);
});

const address = server.address();
if (address === null || typeof address === "string") {
  server.close();
  throw new Error(`unexpected server address: ${String(address)}`);
}
const base = `http://127.0.0.1:${address.port}`;

try {
  const healthResponse = await fetch(`${base}/health`, {
    signal: AbortSignal.timeout(5000),
  });
  if (healthResponse.status !== 200) {
    throw new Error(`health returned HTTP ${healthResponse.status}`);
  }
  if (healthResponse.headers.get("x-content-type-options") !== "nosniff") {
    throw new Error("health response is missing x-content-type-options: nosniff");
  }
  const payload = (await healthResponse.json()) as Health;
  if (payload.ok !== true || payload.typescript !== "strip") {
    throw new Error(`unexpected health payload: ${JSON.stringify(payload)}`);
  }

  const missingResponse = await fetch(`${base}/missing`, {
    signal: AbortSignal.timeout(5000),
  });
  if (missingResponse.status !== 404) {
    throw new Error(`missing path returned HTTP ${missingResponse.status}`);
  }
  const errorPayload = (await missingResponse.json()) as Json;
  if (errorPayload.error !== "not_found") {
    throw new Error(`unexpected 404 payload: ${JSON.stringify(errorPayload)}`);
  }

  console.log(
    `node=${payload.runtime} typescript=${payload.typescript} health=200 missing=404 nosniff=ok`,
  );
  console.log("JS_TS_PACK_OK");
} finally {
  await new Promise<void>((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
}
