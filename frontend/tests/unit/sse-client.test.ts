/**
 * Inner unit tests — plan/frontend/01-sse-client.md "Inner loop" units #1,
 * #2, #4, #5, against `src/sse/client.ts` as actually built.
 *
 * jsdom (this repo's Vitest environment, vitest.config.ts) has no native
 * `EventSource`. A small `FakeEventSource` test double stands in for it —
 * hermetic, no real network, no real browser SSE plumbing — recording
 * listeners/readyState and letting the test drive `open`/`error`/message
 * events directly. `SseClient` itself is real and unmocked; only the global
 * `EventSource` constructor it calls is replaced.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { SseClient } from '../../src/sse/client';
import { Store } from '../../src/state/store';
import type { LayerSnapshot, LayerSnapshotMeta } from '../../src/state/types';

type Listener = (e: MessageEvent) => void;

/** Minimal EventSource stand-in: tracks readyState/listeners, and exposes
 * `dispatch`/`triggerOpen`/`triggerError` for the test to drive it directly,
 * mirroring the real WHATWG readyState values (`SseClient` reads
 * `EventSource.CLOSED` off the constructor, so the static must be present). */
class FakeEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static instances: FakeEventSource[] = [];

  readyState = FakeEventSource.CONNECTING;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, Set<Listener>>();

  constructor(public readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, cb: Listener): void {
    let set = this.listeners.get(type);
    if (!set) {
      set = new Set();
      this.listeners.set(type, set);
    }
    set.add(cb);
  }

  removeEventListener(type: string, cb: Listener): void {
    this.listeners.get(type)?.delete(cb);
  }

  dispatch(type: string, data: unknown): void {
    const event = { data: JSON.stringify(data) } as MessageEvent;
    this.listeners.get(type)?.forEach((cb) => cb(event));
  }

  triggerOpen(): void {
    this.readyState = FakeEventSource.OPEN;
    this.onopen?.();
  }

  triggerError(readyState: number): void {
    this.readyState = readyState;
    this.onerror?.();
  }

  close(): void {
    this.readyState = FakeEventSource.CLOSED;
  }
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal('EventSource', FakeEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('SseClient — plan unit #1: snapshot/layer_status/region_changed dispatch to the matching store mutator', () => {
  it('dispatches a "snapshot" event to store.applySnapshot(domain, snapshot)', () => {
    const store = new Store();
    const spy = vi.spyOn(store, 'applySnapshot');
    new SseClient(store);
    const es = FakeEventSource.instances[0];

    const snapshot: LayerSnapshot = {
      meta: {
        layer: 'air',
        region_id: 'hormuz',
        status: 'live',
        timestamp_fetched: '2026-07-09T10:05:03Z',
        timestamp_source: '2026-07-09T10:04:58Z',
        cadence_s: 600,
        stale_after_s: 1200,
        feature_count: 1,
        retry_after_s: null,
        detail: null,
      },
      features: [],
    };
    es.dispatch('snapshot', snapshot);

    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith('air', snapshot);
  });

  it('dispatches a "layer_status" event to store.applyLayerStatus(domain, meta)', () => {
    const store = new Store();
    const spy = vi.spyOn(store, 'applyLayerStatus');
    new SseClient(store);
    const es = FakeEventSource.instances[0];

    const meta: LayerSnapshotMeta = {
      layer: 'land',
      region_id: 'hormuz',
      status: 'error',
      timestamp_fetched: null,
      timestamp_source: null,
      cadence_s: 86400,
      stale_after_s: 172800,
      feature_count: 0,
      retry_after_s: 30,
      detail: 'upstream timeout',
    };
    es.dispatch('layer_status', meta);

    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith('land', meta);
  });

  it('dispatches a "region_changed" event to store.applyRegionChanged(payload)', () => {
    const store = new Store();
    const spy = vi.spyOn(store, 'applyRegionChanged');
    new SseClient(store);
    const es = FakeEventSource.instances[0];

    const payload = { region_id: 'hormuz', bbox: [54.0, 24.5, 58.5, 28.0] };
    es.dispatch('region_changed', payload);

    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith(payload);
  });
});

describe('SseClient — plan unit #2: connection state derives from EventSource open/error + readyState', () => {
  it('open -> store.connection "open"', () => {
    const store = new Store();
    new SseClient(store);
    const es = FakeEventSource.instances[0];

    es.triggerOpen();

    expect(store.getState().connection).toBe('open');
  });

  it('error while readyState is CONNECTING -> store.connection "lost" (native retry in flight)', () => {
    const store = new Store();
    new SseClient(store);
    const es = FakeEventSource.instances[0];

    es.triggerOpen();
    es.triggerError(FakeEventSource.CONNECTING);

    expect(store.getState().connection).toBe('lost');
  });

  it('error while readyState is CLOSED -> store.connection "failed" (fatal, native retry will not resume)', () => {
    const store = new Store();
    new SseClient(store);
    const es = FakeEventSource.instances[0];

    es.triggerOpen();
    es.triggerError(FakeEventSource.CLOSED);

    expect(store.getState().connection).toBe('failed');
  });
});

describe('SseClient — plan unit #4: exactly one EventSource for the app lifetime', () => {
  it('the constructor opens exactly one EventSource', () => {
    const store = new Store();
    new SseClient(store);

    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it('connect() closes the dead connection before opening a new one — never two live at once', () => {
    const store = new Store();
    const client = new SseClient(store);
    const first = FakeEventSource.instances[0];
    es_triggerFatal(first);

    client.connect();

    expect(first.readyState).toBe(FakeEventSource.CLOSED);
    expect(FakeEventSource.instances).toHaveLength(2);
    const second = FakeEventSource.instances[1];
    expect(second).not.toBe(first);
    expect(second.readyState).toBe(FakeEventSource.CONNECTING);
  });

  function es_triggerFatal(es: FakeEventSource): void {
    es.triggerError(FakeEventSource.CLOSED);
  }
});

describe('SseClient — connection transitions are observable in the order they happened (feeds plan unit #5, see tests/unit/controls.test.ts for the banner/Retry mapping itself)', () => {
  it('every connection transition is observable via store.on("connection", ...) in the same order it happened', () => {
    const store = new Store();
    const seen: string[] = [];
    store.on('connection', (c) => seen.push(c as string));
    new SseClient(store);
    const es = FakeEventSource.instances[0];

    es.triggerOpen();
    es.triggerError(FakeEventSource.CONNECTING);
    es.triggerError(FakeEventSource.CLOSED);

    expect(seen).toEqual(['open', 'lost', 'failed']);
  });
});
