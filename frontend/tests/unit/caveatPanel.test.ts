/**
 * Inner unit tests — plan/frontend/05-caveat-panel.md "Inner loop" unit list,
 * against `src/ui/caveatPanel.ts` (`mountCaveatPanel`) as actually built.
 * `src/api/client.ts` is `vi.mock`'d wholesale (no real network); pure DOM via
 * jsdom, mirroring `tests/unit/regionSelector.test.ts`'s pattern.
 *
 * Plan unit list covered here:
 *   - Panel content is fetched and swapped per domain (bullets verbatim, not
 *     paraphrased) — including a cross-domain-leak check.
 *   - `active_flags` counts render in the footer from the endpoint response.
 *   - No persistent-dismiss affordance exists in the panel DOM (asserted
 *     absent — no checkbox, no "don't show again"/"dismiss forever" text or
 *     testid).
 *   - The SAME single container is reused across two `open()` calls (count
 *     stays 1, content swapped not re-mounted — spec §5).
 *   - Close hides the panel; a subsequent `open()` (mirroring "reopen from the
 *     badge") shows it again.
 *   - Fetch-failure fallback: caches last-known content per domain, per the
 *     implementation's own `catch` branch in `caveatPanel.ts`.
 *   - #101: a failed fetch for a domain with NO cache renders an explicit
 *     unavailable state labeled for the REQUESTED domain (never leaves
 *     another domain's content mislabeled on screen, and never leaves the
 *     Caveats click looking like a dead button).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { mountCaveatPanel } from '../../src/ui/caveatPanel';
import * as client from '../../src/api/client';
import type { CaveatResponse } from '../../src/state/types';

vi.mock('../../src/api/client', () => ({
  fetchCaveats: vi.fn(),
}));

function mockedClient() {
  return client as unknown as {
    fetchCaveats: ReturnType<typeof vi.fn>;
  };
}

const AIR: CaveatResponse = {
  domain: 'air',
  caveats: [
    'AIR-ONLY-CAVEAT: OpenSky coverage over this region depends on volunteer ADS-B receiver density.',
    'AIR-ONLY-CAVEAT: military and state aircraft routinely disable transponders and will not appear.',
  ],
  active_flags: { air_unique_flag_x: 7 },
};

const MARINE: CaveatResponse = {
  domain: 'marine',
  caveats: [
    'Terrestrial AIS coverage in the Persian Gulf is receiver-dependent and uneven.',
    'Dark-fleet vessels routinely disable AIS and will not appear.',
  ],
  active_flags: { spoof_suspect_on_land: 3, implausible_kinematics: 1 },
};

const LAND: CaveatResponse = {
  domain: 'land',
  caveats: ['LAND-ONLY-CAVEAT: OSM road/rail/POI tagging completeness varies by area and editor activity.'],
  active_flags: {},
};

function testid(container: HTMLElement, id: string): HTMLElement {
  const el = container.querySelector(`[data-testid="${id}"]`);
  if (!el) {
    throw new Error(`missing [data-testid="${id}"]`);
  }
  return el as HTMLElement;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('mountCaveatPanel — mounts hidden, single reused instance', () => {
  it('mounts exactly one [data-testid="caveat-panel"] into parent, hidden until opened', () => {
    const parent = document.createElement('div');
    mountCaveatPanel(parent);

    const panels = parent.querySelectorAll('[data-testid="caveat-panel"]');
    expect(panels).toHaveLength(1);
    expect((panels[0] as HTMLElement).style.display).toBe('none');
  });

  it('a second open() call reuses the SAME container (count stays 1), swapping content rather than remounting', async () => {
    mockedClient().fetchCaveats.mockResolvedValueOnce(AIR).mockResolvedValueOnce(MARINE);
    const parent = document.createElement('div');
    const panel = mountCaveatPanel(parent);

    await panel.open('air');
    expect(parent.querySelectorAll('[data-testid="caveat-panel"]')).toHaveLength(1);

    await panel.open('marine');
    expect(parent.querySelectorAll('[data-testid="caveat-panel"]')).toHaveLength(1);
  });
});

describe('mountCaveatPanel — verbatim bullets + domain swap (no cross-domain leak)', () => {
  it('renders AIR\'s bullets verbatim and shows the panel', async () => {
    mockedClient().fetchCaveats.mockResolvedValueOnce(AIR);
    const parent = document.createElement('div');
    const panel = mountCaveatPanel(parent);

    await panel.open('air');

    const container = testid(parent, 'caveat-panel');
    expect(container.style.display).not.toBe('none');
    const bullets = testid(parent, 'caveat-bullets');
    for (const bullet of AIR.caveats) {
      expect(bullets.textContent).toContain(bullet);
    }
    const domainEl = testid(parent, 'caveat-panel-domain');
    expect(domainEl.textContent?.toLowerCase()).toContain('air');
  });

  it('swapping from air to marine replaces the bullets — no leftover AIR bullet text', async () => {
    mockedClient().fetchCaveats.mockResolvedValueOnce(AIR).mockResolvedValueOnce(MARINE);
    const parent = document.createElement('div');
    const panel = mountCaveatPanel(parent);

    await panel.open('air');
    await panel.open('marine');

    const bullets = testid(parent, 'caveat-bullets');
    for (const bullet of MARINE.caveats) {
      expect(bullets.textContent).toContain(bullet);
    }
    for (const bullet of AIR.caveats) {
      expect(bullets.textContent).not.toContain(bullet);
    }
    const domainEl = testid(parent, 'caveat-panel-domain');
    expect(domainEl.textContent?.toLowerCase()).toContain('marine');
    expect(domainEl.textContent?.toLowerCase()).not.toContain('air');
  });

  it('swapping to LAND (empty active_flags) clears any prior footer counts', async () => {
    mockedClient().fetchCaveats.mockResolvedValueOnce(MARINE).mockResolvedValueOnce(LAND);
    const parent = document.createElement('div');
    const panel = mountCaveatPanel(parent);

    await panel.open('marine');
    await panel.open('land');

    const footer = testid(parent, 'caveat-panel-footer');
    expect(footer.textContent).not.toContain('spoof_suspect_on_land');
    expect(footer.textContent).not.toContain('implausible_kinematics');
    const bullets = testid(parent, 'caveat-bullets');
    expect(bullets.textContent).toContain(LAND.caveats[0]);
  });
});

describe('mountCaveatPanel — active_flags name + numeric count in the footer', () => {
  it('renders each active_flags key together with its numeric count', async () => {
    mockedClient().fetchCaveats.mockResolvedValueOnce(MARINE);
    const parent = document.createElement('div');
    const panel = mountCaveatPanel(parent);

    await panel.open('marine');

    const footer = testid(parent, 'caveat-panel-footer');
    for (const [flag, count] of Object.entries(MARINE.active_flags)) {
      expect(footer.textContent).toContain(flag);
      expect(footer.textContent).toContain(String(count));
    }
  });

  it('an empty active_flags object renders no flag names (e.g. LAND) rather than throwing', async () => {
    mockedClient().fetchCaveats.mockResolvedValueOnce(LAND);
    const parent = document.createElement('div');
    const panel = mountCaveatPanel(parent);

    await expect(panel.open('land')).resolves.toBeUndefined();
    const footer = testid(parent, 'caveat-panel-footer');
    expect(footer.textContent).not.toBe('');
  });
});

describe('mountCaveatPanel — no persistent-dismiss affordance anywhere in the panel', () => {
  it('has no checkbox, no "don\'t show again"/"dismiss forever" text, no dont-show/dismiss-forever testid', async () => {
    mockedClient().fetchCaveats.mockResolvedValueOnce(AIR);
    const parent = document.createElement('div');
    const panel = mountCaveatPanel(parent);
    await panel.open('air');

    const container = testid(parent, 'caveat-panel');
    expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(0);
    expect(container.textContent).not.toMatch(/don'?t show again/i);
    expect(container.textContent).not.toMatch(/dismiss forever/i);
    expect(container.querySelectorAll('[data-testid*="dont-show" i]')).toHaveLength(0);
    expect(container.querySelectorAll('[data-testid*="dismiss-forever" i]')).toHaveLength(0);
  });
});

describe('mountCaveatPanel — close is session-only; badge reopens the same instance', () => {
  it('clicking [data-testid="caveat-panel-close"] hides the panel', async () => {
    mockedClient().fetchCaveats.mockResolvedValueOnce(AIR);
    const parent = document.createElement('div');
    const panel = mountCaveatPanel(parent);
    await panel.open('air');

    const container = testid(parent, 'caveat-panel');
    expect(container.style.display).not.toBe('none');

    testid(parent, 'caveat-panel-close').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(container.style.display).toBe('none');
  });

  it('a later open() call (mirroring badge reopen) shows the same instance again', async () => {
    mockedClient().fetchCaveats.mockResolvedValueOnce(AIR).mockResolvedValueOnce(AIR);
    const parent = document.createElement('div');
    const panel = mountCaveatPanel(parent);
    await panel.open('air');

    const container = testid(parent, 'caveat-panel');
    testid(parent, 'caveat-panel-close').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(container.style.display).toBe('none');

    await panel.open('air');
    expect(parent.querySelectorAll('[data-testid="caveat-panel"]')).toHaveLength(1);
    expect(container.style.display).not.toBe('none');
  });
});

describe('mountCaveatPanel — fetch-failure fallback caches last-known content per domain', () => {
  it('a failed fetch on the FIRST open (no prior cache) shows an honest unavailable state for the requested domain (#101)', async () => {
    mockedClient().fetchCaveats.mockRejectedValueOnce(new Error('network down'));
    const parent = document.createElement('div');
    const panel = mountCaveatPanel(parent);

    await expect(panel.open('air')).resolves.toBeUndefined();
    const container = testid(parent, 'caveat-panel');
    expect(container.style.display).not.toBe('none');
    expect(testid(parent, 'caveat-panel-domain').textContent?.toLowerCase()).toContain('air');
    expect(testid(parent, 'caveat-bullets').textContent).toMatch(/unavailable/i);
  });

  it('a failed fetch AFTER a prior successful open falls back to the cached content for that domain', async () => {
    mockedClient().fetchCaveats.mockResolvedValueOnce(AIR).mockRejectedValueOnce(new Error('network down'));
    const parent = document.createElement('div');
    const panel = mountCaveatPanel(parent);

    await panel.open('air');
    const container = testid(parent, 'caveat-panel');
    expect(container.style.display).not.toBe('none');

    // Second open for the SAME domain hits the network again; this time it
    // fails — the panel must keep showing air's last-known (cached) content
    // rather than going blank or throwing.
    await expect(panel.open('air')).resolves.toBeUndefined();
    expect(container.style.display).not.toBe('none');
    const bullets = testid(parent, 'caveat-bullets');
    for (const bullet of AIR.caveats) {
      expect(bullets.textContent).toContain(bullet);
    }
  });

  it("#101 regression: domain-SWITCH failure with no cache for the new domain must NOT leave the previous domain's content mislabeled on screen", async () => {
    mockedClient().fetchCaveats.mockResolvedValueOnce(AIR).mockRejectedValueOnce(new Error('network down'));
    const parent = document.createElement('div');
    const panel = mountCaveatPanel(parent);

    await panel.open('air'); // panel open, showing AIR
    // User clicks MARINE's Caveats button; marine has never loaded and the
    // fetch fails — the pre-#101 bug left AIR's bullets visible here.
    await expect(panel.open('marine')).resolves.toBeUndefined();

    const container = testid(parent, 'caveat-panel');
    expect(container.style.display).not.toBe('none');
    expect(testid(parent, 'caveat-panel-domain').textContent?.toLowerCase()).toContain('marine');
    const bullets = testid(parent, 'caveat-bullets');
    for (const bullet of AIR.caveats) {
      expect(bullets.textContent).not.toContain(bullet);
    }
    expect(bullets.textContent).toMatch(/unavailable/i);
    expect(testid(parent, 'caveat-panel-footer').textContent).toMatch(/unavailable/i);
  });

  it('#101: a later successful open for that domain recovers from the unavailable state to real content', async () => {
    mockedClient().fetchCaveats
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce(MARINE);
    const parent = document.createElement('div');
    const panel = mountCaveatPanel(parent);

    await panel.open('marine'); // unavailable state
    await panel.open('marine'); // network recovered

    const bullets = testid(parent, 'caveat-bullets');
    for (const bullet of MARINE.caveats) {
      expect(bullets.textContent).toContain(bullet);
    }
    expect(bullets.textContent).not.toMatch(/unavailable/i);
  });
});
