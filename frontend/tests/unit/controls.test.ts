/**
 * Unit tests for `src/ui/controls.ts` (`mountConnectionBanner`): "lost" vs
 * "failed" map to the non-blocking banner vs the Retry action respectively.
 * Pure DOM, jsdom — no map, no network, no real SSE client;
 * `store.setConnection(...)` drives it directly.
 */
import { describe, expect, it, vi } from 'vitest';

import { mountConnectionBanner } from '../../src/ui/controls';
import { Store } from '../../src/state/store';

function bannerParts(container: HTMLElement) {
  return {
    banner: container.querySelector('[data-testid="connection-banner"]') as HTMLElement,
    retry: container.querySelector('[data-testid="connection-retry"]') as HTMLElement,
  };
}

describe('mountConnectionBanner — plan unit #5: "connecting"/"open" render the banner hidden', () => {
  it('hides the banner and the Retry button while connection is "connecting" (initial store state)', () => {
    const parent = document.createElement('div');
    const store = new Store();

    mountConnectionBanner(parent, store, () => undefined);

    const { banner, retry } = bannerParts(parent);
    expect(banner.style.display).toBe('none');
    expect(retry.style.display).toBe('none');
  });

  it('hides the banner once connection becomes "open"', () => {
    const parent = document.createElement('div');
    const store = new Store();
    mountConnectionBanner(parent, store, () => undefined);

    store.setConnection('open');

    const { banner, retry } = bannerParts(parent);
    expect(banner.style.display).toBe('none');
    expect(retry.style.display).toBe('none');
  });
});

describe('mountConnectionBanner — plan unit #5: "lost" shows the non-blocking Reconnecting… banner, no Retry', () => {
  it('shows the banner with "Reconnecting…" text and keeps the Retry button hidden', () => {
    const parent = document.createElement('div');
    const store = new Store();
    mountConnectionBanner(parent, store, () => undefined);

    store.setConnection('lost');

    const { banner, retry } = bannerParts(parent);
    expect(banner.style.display).not.toBe('none');
    expect(banner.textContent).toContain('Reconnecting…');
    expect(retry.style.display).toBe('none');
  });
});

describe('mountConnectionBanner — plan unit #5: "failed" shows "Connection failed" plus a wired Retry action', () => {
  it('shows the banner with "Connection failed" text and reveals the Retry button', () => {
    const parent = document.createElement('div');
    const store = new Store();
    mountConnectionBanner(parent, store, () => undefined);

    store.setConnection('failed');

    const { banner, retry } = bannerParts(parent);
    expect(banner.style.display).not.toBe('none');
    expect(banner.textContent).toContain('Connection failed');
    expect(retry.style.display).not.toBe('none');
    expect(retry.textContent).toContain('Retry');
  });

  it('clicking Retry calls the injected onRetry callback exactly once (wired to SseClient#connect() by the caller)', () => {
    const parent = document.createElement('div');
    const store = new Store();
    const onRetry = vi.fn();
    mountConnectionBanner(parent, store, onRetry);
    store.setConnection('failed');

    const { retry } = bannerParts(parent);
    retry.dispatchEvent(new MouseEvent('click', { bubbles: true }));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

describe('mountConnectionBanner — plan unit #5: transitioning from "failed" back to "lost" hides Retry again', () => {
  it('going failed -> lost re-hides the Retry button while the banner stays visible with "Reconnecting…"', () => {
    const parent = document.createElement('div');
    const store = new Store();
    mountConnectionBanner(parent, store, () => undefined);

    store.setConnection('failed');
    store.setConnection('lost');

    const { banner, retry } = bannerParts(parent);
    expect(banner.style.display).not.toBe('none');
    expect(banner.textContent).toContain('Reconnecting…');
    expect(retry.style.display).toBe('none');
  });
});
