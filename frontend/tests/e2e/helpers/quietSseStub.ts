/**
 * Shared e2e helper — a quiet, permanently-open `/api/events` stub for specs
 * that don't exercise SSE at all (`map-init.spec.ts`, `layers-refresh.spec.ts`).
 * See `sse-client.spec.ts`'s file-header STUB MECHANISM comment for the full
 * rationale; the short version:
 *
 * `page.route().fulfill()` always delivers a complete, atomic HTTP body, so a
 * fulfilled `/api/events` response — even a "200, empty body" one — hits an
 * unexpected close the instant it's delivered. Per the WHATWG EventSource
 * spec that's a non-fatal close, so the browser's native reconnect logic
 * retries forever at its default interval: an infinite background
 * open-then-immediately-drop loop for the entire remaining test (and, on
 * this environment, into Playwright's own browser-process teardown well
 * past the test's own pass/fail — observed as `worker process did not exit
 * within 300000ms after stop, force-killed it`).
 *
 * The fix is the same one `sse-client.spec.ts` already needs for its own
 * "connected" window: run a REAL streaming HTTP server (Node `http`, no IPC,
 * same process) that answers with valid SSE headers and never ends the
 * response, and redirect the browser's same-origin request to it via
 * `route.continue({ url })` (unlike `fulfill()`, `continue()` performs a
 * genuine network request, so the server can hold the socket open for real).
 * The EventSource opens once, stays `open`, and never needs to retry — the
 * quietest possible stand-in for a spec that asserts nothing about SSE.
 */
import { createServer, type Server } from 'node:http';
import type { Socket } from 'node:net';
import type { AddressInfo } from 'node:net';
import type { Page } from '@playwright/test';

export interface QuietSseStub {
  /** Registers the `/api/events` redirect on `page`. Call BEFORE `page.goto()`. */
  attachTo(page: Page): Promise<void>;
  /** Force-closes the fixture server (destroys any held-open sockets first —
   * `server.close()` alone waits indefinitely for already-open connections). */
  close(): Promise<void>;
}

export async function startQuietSseStub(): Promise<QuietSseStub> {
  const sockets = new Set<Socket>();

  const server: Server = createServer((_req, res) => {
    res.setHeader('Access-Control-Allow-Origin', '*'); // cross-origin redirect target
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
    });
    // A bare SSE comment line — a no-op "heartbeat" that keeps the stream a
    // well-formed text/event-stream without dispatching any named event.
    res.write(':\n\n');
    const flushable = res as typeof res & { flushHeaders?: () => void };
    flushable.flushHeaders?.();
    // Deliberately no res.end() — held open for the whole test.
  });

  server.on('connection', (socket) => {
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
  });

  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address() as AddressInfo;
  const url = `http://127.0.0.1:${port}/api/events`;

  return {
    attachTo: async (page: Page) => {
      await page.route('**/api/events', async (route) => {
        await route.continue({ url });
      });
    },
    close: async () => {
      for (const socket of sockets) {
        socket.destroy();
      }
      await new Promise<void>((resolve) => server.close(() => resolve()));
    },
  };
}
