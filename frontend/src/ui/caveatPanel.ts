// Caveat panel DOM (spec §5, FR9). ONE reused instance across all domains —
// content is swapped in place on every `open(domain)` call, never re-mounted
// (locked by the outer test's "panel count never exceeds 1" assertion). No
// framework, imperative DOM (ADR-3), mirroring `ui/regionSelector.ts`.
//
// Deliberately the one component in the app with NO persistent-dismiss
// affordance (FR9) — `close()` only toggles visibility for the current
// session; the badge's Caveats button is the only way back, every time.

import { fetchCaveats } from '../api/client';
import type { CaveatResponse, Domain } from '../state/types';

export interface CaveatPanel {
  container: HTMLElement;
  /** Fetches (or serves from cache) `domain`'s caveats and swaps them into
   * the one shared panel instance, then shows it. */
  open(domain: Domain): Promise<void>;
}

const DOMAIN_LABEL: Record<Domain, string> = {
  air: 'AIR',
  marine: 'MARINE',
  land: 'LAND',
};

// Domain accent bar reads the same §8 tokens as the badge chip / map icons —
// one source of truth, no re-declaration (spec §8).
const DOMAIN_ACCENT_VAR: Record<Domain, string> = {
  air: '--zij-brass',
  marine: '--zij-teal',
  land: '--zij-dun',
};

/** Mounts the single caveat panel into `parent` (hidden until first opened). */
export function mountCaveatPanel(parent: HTMLElement): CaveatPanel {
  const container = document.createElement('div');
  container.className = 'zij-caveat-panel';
  container.dataset.testid = 'caveat-panel';
  container.style.display = 'none';

  const header = document.createElement('div');
  header.className = 'zij-caveat-panel__header';

  const domainEl = document.createElement('span');
  domainEl.className = 'zij-caveat-panel__domain';
  domainEl.dataset.testid = 'caveat-panel-domain';
  header.appendChild(domainEl);

  const closeButton = document.createElement('button');
  closeButton.type = 'button';
  closeButton.className = 'zij-caveat-panel__close';
  closeButton.dataset.testid = 'caveat-panel-close';
  closeButton.textContent = 'Close';
  closeButton.addEventListener('click', () => {
    // Session-only hide — no persistent-dismiss state is ever written here
    // (FR9); the badge's Caveats button is the only way back.
    container.style.display = 'none';
  });
  header.appendChild(closeButton);

  container.appendChild(header);

  const bullets = document.createElement('ul');
  bullets.className = 'zij-caveat-panel__bullets';
  bullets.dataset.testid = 'caveat-bullets';
  container.appendChild(bullets);

  const footer = document.createElement('div');
  footer.className = 'zij-caveat-panel__footer';
  footer.dataset.testid = 'caveat-panel-footer';
  container.appendChild(footer);

  parent.appendChild(container);

  // Component-local cache (spec §5's `store.caveats[domain]` sketch is
  // optional — caveat text is static, only counts move, so a per-open
  // refetch here is cheap and keeps counts fresh without a store change).
  const cache: Partial<Record<Domain, CaveatResponse>> = {};

  function render(domain: Domain, data: CaveatResponse): void {
    container.style.setProperty('--zij-caveat-accent', `var(${DOMAIN_ACCENT_VAR[domain]})`);
    domainEl.textContent = DOMAIN_LABEL[domain];

    bullets.innerHTML = '';
    for (const caveat of data.caveats) {
      const li = document.createElement('li');
      li.textContent = caveat;
      bullets.appendChild(li);
    }

    const flagEntries = Object.entries(data.active_flags);
    if (flagEntries.length === 0) {
      footer.textContent = 'No active integrity flags.';
    } else {
      footer.textContent = flagEntries.map(([flag, count]) => `${flag}: ${count}`).join(' · ');
    }
  }

  /** Honest fallback (#101, FR9): when the requested domain's fetch fails
   * and it has no cached content, render an explicit unavailable state FOR
   * THAT DOMAIN. Returning without rendering left whatever domain was shown
   * before mislabeled under the requested domain's implied context — the one
   * dishonest state an honesty panel must never occupy. */
  function renderUnavailable(domain: Domain): void {
    container.style.setProperty('--zij-caveat-accent', `var(${DOMAIN_ACCENT_VAR[domain]})`);
    domainEl.textContent = DOMAIN_LABEL[domain];
    bullets.innerHTML = '';
    const li = document.createElement('li');
    li.textContent = 'Caveats are unavailable right now (the server could not be reached). This layer’s standing caveats still apply.';
    bullets.appendChild(li);
    footer.textContent = 'Active integrity flag counts unavailable.';
  }

  async function open(domain: Domain): Promise<void> {
    let data = cache[domain];
    try {
      data = await fetchCaveats(domain);
      cache[domain] = data;
    } catch (err) {
      console.warn(`[zij] fetchCaveats(${domain}) failed:`, err);
      if (!data) {
        renderUnavailable(domain);
        container.style.display = 'block';
        return;
      }
    }
    render(domain, data);
    container.style.display = 'block';
  }

  return { container, open };
}
