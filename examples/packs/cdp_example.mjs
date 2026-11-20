#!/usr/bin/env node
// Real Chrome DevTools Protocol pack example.
//
// Run: node examples/packs/cdp_example.mjs
//
// The script discovers a Chromium binary (CDP_BROWSER_PATH, PATH, or the
// Playwright cache), launches it with a throwaway profile and port 0, reads
// the real endpoint from DevToolsActivePort, and speaks raw CDP over the
// browser WebSocket. It creates a target, evaluates the title and a DOM
// element, captures a PNG screenshot, then closes the browser and removes the
// profile. It prints CDP_PACK_OK only when every check passes.

import { spawn } from "node:child_process";
import {
  accessSync,
  constants,
  existsSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
} from "node:fs";
import { homedir, tmpdir } from "node:os";
import path from "node:path";

const TIMEOUT_MS = 15_000;
const failures = [];

function check(condition, message) {
  if (!condition) failures.push(message);
}

function executable(file) {
  try {
    accessSync(file, constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

function playwrightCandidates() {
  const root = path.join(homedir(), ".cache", "ms-playwright");
  if (!existsSync(root)) return [];
  const found = [];
  for (const entry of readdirSync(root)) {
    if (entry.startsWith("chromium_headless_shell-")) {
      found.push(
        path.join(root, entry, "chrome-headless-shell-linux64", "chrome-headless-shell"),
      );
    }
    if (entry.startsWith("chromium-")) {
      found.push(path.join(root, entry, "chrome-linux", "chrome"));
    }
  }
  return found.sort().reverse();
}

function findBrowser() {
  const explicit = process.env.CDP_BROWSER_PATH;
  if (explicit && executable(explicit)) return explicit;
  for (const name of ["chromium", "google-chrome", "google-chrome-stable", "chrome"]) {
    for (const dir of (process.env.PATH || "").split(path.delimiter)) {
      const candidate = path.join(dir, name);
      if (executable(candidate)) return candidate;
    }
  }
  return playwrightCandidates().find(executable) ?? null;
}

function waitForFile(file, deadline) {
  return new Promise((resolve, reject) => {
    const tick = () => {
      if (existsSync(file)) return resolve();
      if (Date.now() > deadline) return reject(new Error(`timeout waiting for ${file}`));
      return setTimeout(tick, 50);
    };
    tick();
  });
}

async function main() {
  const browser = findBrowser();
  if (!browser) {
    console.error("CDP_UNAVAILABLE: no Chromium binary found");
    process.exitCode = 2;
    return;
  }

  const profile = mkdtempSync(path.join(tmpdir(), "zc-cdp-"));
  let child = null;
  let socket = null;

  try {
    const args = [
      "--remote-debugging-port=0",
      `--user-data-dir=${profile}`,
      "--no-sandbox",
      "--disable-gpu",
      "--disable-dev-shm-usage",
      "--no-first-run",
      "--no-default-browser-check",
    ];
    if (!browser.includes("headless-shell")) args.push("--headless=new");
    args.push("about:blank");

    child = spawn(browser, args, { stdio: ["ignore", "ignore", "pipe"] });
    let stderr = "";
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });

    const portFile = path.join(profile, "DevToolsActivePort");
    await waitForFile(portFile, Date.now() + TIMEOUT_MS);
    const lines = readFileSync(portFile, "utf8").trim().split("\n");
    const port = (lines[0] || "").trim();
    const wsPath = (lines[1] || "").trim();
    check(/^\d+$/.test(port), `invalid DevToolsActivePort port: ${port}`);
    check(wsPath.startsWith("/"), `invalid DevToolsActivePort path: ${wsPath}`);
    if (failures.length) throw new Error(failures.join("; "));

    socket = new WebSocket(`ws://127.0.0.1:${port}${wsPath}`);
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("WebSocket open timeout")), TIMEOUT_MS);
      socket.addEventListener("open", () => {
        clearTimeout(timer);
        resolve();
      }, { once: true });
      socket.addEventListener("error", () => {
        clearTimeout(timer);
        reject(new Error("WebSocket connection failed"));
      }, { once: true });
    });

    let nextId = 1;
    const pending = new Map();
    socket.addEventListener("message", (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }
      const waiter = pending.get(message.id);
      if (!waiter) return;
      pending.delete(message.id);
      if (message.error) waiter.reject(new Error(`${waiter.method}: ${message.error.message}`));
      else waiter.resolve(message.result);
    });

    const send = (method, params = {}, sessionId) => {
      const id = nextId++;
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          pending.delete(id);
          reject(new Error(`${method} timeout`));
        }, TIMEOUT_MS);
        pending.set(id, {
          method,
          resolve: (value) => {
            clearTimeout(timer);
            resolve(value);
          },
          reject: (error) => {
            clearTimeout(timer);
            reject(error);
          },
        });
        socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
      });
    };

    const version = await send("Browser.getVersion");
    check(/Chrome/.test(version.product || ""), `unexpected product: ${version.product}`);

    const html = '<!doctype html><title>cdp-pack-ok</title><h1 id="headline">hello cdp</h1>';
    const target = await send("Target.createTarget", {
      url: "data:text/html," + encodeURIComponent(html),
    });
    const attached = await send("Target.attachToTarget", {
      targetId: target.targetId,
      flatten: true,
    });
    const sessionId = attached.sessionId;
    check(typeof sessionId === "string" && sessionId.length > 0, "attachToTarget returned no sessionId");

    await send("Runtime.enable", {}, sessionId);
    await send("Page.enable", {}, sessionId);

    const title = await send(
      "Runtime.evaluate",
      { expression: "document.title", returnByValue: true },
      sessionId,
    );
    check(title.result?.value === "cdp-pack-ok", `title was ${JSON.stringify(title.result?.value)}`);

    const headline = await send(
      "Runtime.evaluate",
      { expression: "document.querySelector('#headline')?.textContent ?? ''", returnByValue: true },
      sessionId,
    );
    check(headline.result?.value === "hello cdp", `headline was ${JSON.stringify(headline.result?.value)}`);

    const shot = await send("Page.captureScreenshot", { format: "png" }, sessionId);
    const shotBytes = shot.data ? Buffer.from(shot.data, "base64").length : 0;
    check(shotBytes > 1000, `screenshot was only ${shotBytes} bytes`);

    if (failures.length) throw new Error(failures.join("; "));

    console.log(
      `cdp: product=${version.product} title=${title.result.value} ` +
        `headline=${headline.result.value} screenshot=${shotBytes}B`,
    );
    console.log("CDP_PACK_OK");
  } catch (error) {
    console.error(`CDP_PACK_FAIL: ${error.message}`);
    process.exitCode = 1;
  } finally {
    try {
      if (socket && socket.readyState === WebSocket.OPEN) socket.close();
    } catch {
      // ignore close errors
    }
    if (child) {
      await new Promise((resolve) => {
        const timer = setTimeout(() => {
          child.kill("SIGKILL");
          resolve();
        }, 5000);
        child.once("exit", () => {
          clearTimeout(timer);
          resolve();
        });
        child.kill("SIGTERM");
        if (child.exitCode !== null) {
          clearTimeout(timer);
          resolve();
        }
      });
    }
    rmSync(profile, { recursive: true, force: true });
  }
}

await main();
