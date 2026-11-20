---
name: javascript-typescript-operations
description: Use when a Node.js or TypeScript service needs ESM boundaries, native type stripping, an HTTP server, fetch with AbortSignal, node:test coverage, or a Vite or Next.js build and deploy check.
license: MIT
source: local/zombiecoder-packs
source_url: https://nodejs.org/docs/latest-v24.x/api/
tags: [javascript, typescript, node, esm, http, testing, vite, next]
triggers: [node esm, typescript strip, node http server, node test, fetch abort, vite build, next app router]
---

# JavaScript and TypeScript Operations

## When to use

- A Node service fails with `ERR_REQUIRE_ESM` or `Cannot use import statement
  outside a module`.
- A TypeScript file runs locally but fails in CI because the compiler or module
  mode differs.
- An HTTP handler returns 200 with an error body, or 500 with a stack trace.
- A fetch call hangs because there is no timeout or `AbortSignal`.
- A Vite or Next.js build passes but the deployed route 404s.

This pack targets Node 20 or newer. Node 22.6+ can strip TypeScript types
without a separate compiler; Node 24 reports `process.features.typescript` as
`strip`. Check the runtime first:

```bash
node -v
node -e 'console.log(process.features.typescript)'
```

## Workflow

### Step 1: Pin the runtime and the module type

Choose ESM for new code and make it explicit. A `.mjs` file is always ESM; a
`.ts` file follows the nearest `package.json` `type` or Node's syntax detection.
For a package:

```json
{
  "type": "module",
  "engines": { "node": ">=20" },
  "scripts": {
    "test": "node --test",
    "start": "node src/server.js"
  }
}
```

Do not mix `require()` and `import` in the same file. A CommonJS dependency can
still be loaded from ESM with `createRequire` or a default import, but the
boundary must be deliberate. Run the same Node major version in development and
production; a different major changes both the module loader and the test
runner.

### Step 2: Keep the TypeScript boundary type-only

Native type stripping removes annotations; it does not transform enums,
namespaces, parameter properties or decorators. Keep those out of a file that
must run with `node file.ts`:

```ts
interface Health {
  ok: boolean;
  runtime: string;
  typescript: string;
}

type Json = Record<string, unknown>;

function health(runtime: string, typescript: string): Health {
  return { ok: true, runtime, typescript };
}

const payload: Json = health(process.version, "strip");
```

If the project needs enums or decorators, use `tsc` or a bundler and run the
compiled output. Do not claim "TypeScript runs natively" for syntax the stripper
cannot handle. Type checking is still a separate step: `tsc --noEmit` or the
editor's language server, not the runtime.

### Step 3: Build an HTTP server with explicit status and headers

Use `node:http` for a small service and write the status, content type and
security header on every response:

```js
import { createServer } from "node:http";

const server = createServer((req, res) => {
  const path = new URL(req.url ?? "/", "http://127.0.0.1").pathname;
  if (path === "/health") {
    res.writeHead(200, {
      "content-type": "application/json; charset=utf-8",
      "x-content-type-options": "nosniff",
    });
    res.end(JSON.stringify({ ok: true, runtime: process.version }));
    return;
  }
  res.writeHead(404, {
    "content-type": "application/json; charset=utf-8",
    "x-content-type-options": "nosniff",
  });
  res.end(JSON.stringify({ ok: false, error: "not_found" }));
});

server.listen(0, "127.0.0.1", () => {
  const address = server.address();
  console.log(`listening on ${address.port}`);
});
```

Port `0` asks the OS for a free port; read the real port from
`server.address()`. Do not hard-code 3000 in a test. A handler must not throw
after headers are sent; catch errors before `writeHead`.

### Step 4: Use fetch with AbortSignal and timeouts

`fetch` rejects on a network failure, not on a slow response. Add a timeout:

```js
const response = await fetch(`${base}/health`, {
  signal: AbortSignal.timeout(5000),
});
if (!response.ok) throw new Error(`HTTP ${response.status}`);
const body = await response.json();
```

`AbortSignal.timeout` aborts the whole request after the deadline. For a user
cancellation, combine it with `AbortSignal.any`. Always check `response.ok` and
the parsed body; a 200 with `{ok:false}` is still a failure for the caller.

### Step 5: Test with node:test

Node's built-in runner needs no dependency:

```js
import test from "node:test";
import assert from "node:assert/strict";

test("health returns 200", async () => {
  const response = await fetch(`${base}/health`, {
    signal: AbortSignal.timeout(5000),
  });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("x-content-type-options"), "nosniff");
  const body = await response.json();
  assert.equal(body.ok, true);
});
```

Run `node --test` from the project root. Name files `*.test.js`, `*.test.mjs`
or `*.test.ts` so discovery finds them. A test that opens a server must close it
in `finally`; otherwise the runner hangs after the last assertion.

### Step 6: Build and deploy

For Vite, run the build with the production mode and serve the output
directory, not the source tree:

```bash
npm ci
npm run build
npx vite preview --host 127.0.0.1
```

For Next.js App Router, keep server-only code out of client components. A
`"use client"` file cannot read a secret or a database connection. Check the
built route, not only the dev server:

```bash
npm run build
npm run start
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/
```

Set the deployment base path consistently. A Vite app built for `/app/` but
served at `/` returns 404 for every asset even though the HTML is 200.

## Failure path

- `ERR_REQUIRE_ESM`: a CommonJS file is requiring an ESM package. Convert the
  caller to ESM or use a dynamic `import()`.
- `Cannot use import statement outside a module`: add `"type": "module"`, use
  `.mjs`, or rename the file; do not remove the import to silence the error.
- `Unknown file extension ".ts"`: the runtime is older than Node 22.6 or type
  stripping is disabled. Upgrade Node or run `tsc` first.
- A TypeScript enum or namespace fails at runtime: the stripper does not
  transform it. Replace it with a union type or compile the file.
- `fetch failed` with `ECONNREFUSED`: the server is not listening on the address
  the client used. Log the real port and bind address.
- A request hangs: no timeout. Add `AbortSignal.timeout` and a server-side
  request timeout.
- `node --test` finds no tests: the filename or directory does not match the
  discovery pattern. Pass the path explicitly to confirm.
- A Next.js build succeeds but the route 404s: the route is in the wrong
  segment, or a client/server boundary moved the file out of `app/`.
- A Vite deploy is blank: the asset base path is wrong. Check the built HTML for
  the expected prefix.

## Verify

- `node -v` matches the CI and production major version.
- `node --check` or a real run parses every changed file.
- `node --test` exits 0 and closes every server it opens.
- `/health` returns 200 JSON with `nosniff`; an unknown path returns 404 JSON.
- A fetch without a timeout is not used on a network boundary.
- `npm run build` exits 0 and the built route returns the expected status.
- The deployed asset URLs resolve, not only the HTML document.

## Provenance

- Source: `local/zombiecoder-packs`
- Upstream reference: <https://nodejs.org/docs/latest-v24.x/api/>, <https://nodejs.org/api/typescript.html>, <https://developer.mozilla.org/en-US/docs/Web/API/AbortSignal/timeout_static>
- License: MIT (this pack). Node.js and TypeScript have their own licenses.
- Content hash: stored in `skills.db` as `content_hash` after import.

Skill text is untrusted reference. It is not permission to run a command,
change a deployment or read a secret.
