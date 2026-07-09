// Layer badge DOM (spec §4). Builds one badge per domain (air/marine/land),
// showing: domain title, a status indicator+label driven by the seven
// `LayerStatus` values, both freshness timestamps (UTC), feature count, and
// the Toggle/Refresh/Caveats controls row. Built once per domain, updated
// imperatively via `update()` (no framework, per ADR-3).

import { formatUtc } from '../util/formatUtc';
import { formatAge } from '../util/formatAge';
import type { LayerSnapshotMeta } from '../state/types';

export type BadgeDomain = 'air' | 'marine' | 'land';

interface Badge {
  container: HTMLElement;
  update(meta: LayerSnapshotMeta): void;
}

/** Renders the fixed (non-countdown) label text for a given status per
 * spec §4's color/label table. `rate-limited`'s countdown text is rendered
 * separately by `update()`'s interval logic, not through this helper. */
function staticLabelFor(meta: LayerSnapshotMeta): string {
  switch (meta.status) {
    case 'live':
      return 'Live';
    case 'loading':
      return 'Loading…';
    case 'reconnecting':
      return 'Reconnecting…';
    case 'error':
      return 'Error';
    case 'stale':
      return `Stale · ${formatAge(meta.timestamp_source)}`;
    case 'cached-fallback':
      return `Cached · ${formatAge(meta.timestamp_fetched)}`;
    default:
      return meta.status;
  }
}

/** Builds one badge container (`[data-testid="badge-{domain}"]`) with its
 * status/freshness/count seams, and mounts it into `parent`. */
export function mountBadge(parent: HTMLElement, domain: BadgeDomain): Badge {
  const container = document.createElement('div');
  container.className = 'zij-badge';
  container.dataset.testid = `badge-${domain}`;

  const headerRow = document.createElement('div');
  headerRow.className = 'zij-badge__row zij-badge__header';

  const indicator = document.createElement('span');
  indicator.className = 'zij-badge__indicator';
  indicator.dataset.testid = 'status-indicator';
  headerRow.appendChild(indicator);

  const title = document.createElement('span');
  title.className = 'zij-badge__title';
  title.textContent = domain.toUpperCase();
  headerRow.appendChild(title);

  const labelValue = document.createElement('span');
  labelValue.className = 'zij-badge__status-label';
  labelValue.dataset.testid = 'status-label';
  headerRow.appendChild(labelValue);

  container.appendChild(headerRow);

  const fetchedRow = document.createElement('div');
  fetchedRow.className = 'zij-badge__row';
  const fetchedLabel = document.createElement('span');
  fetchedLabel.className = 'zij-badge__label';
  fetchedLabel.textContent = 'fetched ';
  const fetchedValue = document.createElement('span');
  fetchedValue.dataset.testid = 'freshness-fetched';
  fetchedRow.append(fetchedLabel, fetchedValue);
  container.appendChild(fetchedRow);

  const sourceRow = document.createElement('div');
  sourceRow.className = 'zij-badge__row';
  const sourceLabel = document.createElement('span');
  sourceLabel.className = 'zij-badge__label';
  sourceLabel.textContent = 'source ';
  const sourceValue = document.createElement('span');
  sourceValue.dataset.testid = 'freshness-source';
  sourceRow.append(sourceLabel, sourceValue);
  container.appendChild(sourceRow);

  const countRow = document.createElement('div');
  countRow.className = 'zij-badge__row';
  const countValue = document.createElement('span');
  countValue.dataset.testid = 'feature-count';
  countRow.appendChild(countValue);
  container.appendChild(countRow);

  // Present on every badge (REQUIRED TEST SEAM #5) — its `data-detail`
  // attribute mirrors `meta.detail` verbatim; only meaningful when
  // `status === 'error'`, but kept in sync unconditionally for simplicity.
  const detailEl = document.createElement('div');
  detailEl.dataset.testid = 'status-detail';
  detailEl.style.display = 'none';
  container.appendChild(detailEl);

  // Controls row — spec §4/§7 layout: `[ Toggle ] [ Refresh ↻ ] [ Caveats ⓘ ]`.
  // Toggle/Refresh are inert this slice (wiring deferred to step); Caveats
  // must always be present and enabled, in every status (REQUIRED TEST SEAM #6).
  const controlsRow = document.createElement('div');
  controlsRow.className = 'zij-badge__row zij-badge__controls';

  const toggleButton = document.createElement('button');
  toggleButton.type = 'button';
  toggleButton.dataset.testid = 'toggle-button';
  toggleButton.textContent = 'Toggle';
  controlsRow.appendChild(toggleButton);

  const refreshButton = document.createElement('button');
  refreshButton.type = 'button';
  refreshButton.dataset.testid = 'refresh-button';
  refreshButton.textContent = 'Refresh ↻';
  controlsRow.appendChild(refreshButton);

  const caveatsButton = document.createElement('button');
  caveatsButton.type = 'button';
  caveatsButton.dataset.testid = 'caveats-button';
  caveatsButton.textContent = 'Caveats ⓘ';
  // No-op this slice — the caveat panel itself is step's job (spec §5).
  caveatsButton.addEventListener('click', () => {
    console.debug(`[zij] caveats button clicked for ${domain} (panel wiring: step)`);
  });
  controlsRow.appendChild(caveatsButton);

  container.appendChild(controlsRow);

  parent.appendChild(container);

  // Rate-limited countdown state (REQUIRED TEST SEAM #4): seeded from
  // `retry_after_s` on each `rate-limited` update, ticking down every second.
  // Cleared whenever a new `update()` call supersedes it — whether the status
  // changes away from `rate-limited` or a fresh `rate-limited` meta arrives —
  // so no interval ever leaks across updates.
  let countdownIntervalId: ReturnType<typeof setInterval> | null = null;

  function clearCountdown(): void {
    if (countdownIntervalId !== null) {
      clearInterval(countdownIntervalId);
      countdownIntervalId = null;
    }
  }

  function update(meta: LayerSnapshotMeta): void {
    container.dataset.status = meta.status;
    fetchedValue.textContent = formatUtc(meta.timestamp_fetched);
    sourceValue.textContent = formatUtc(meta.timestamp_source);
    countValue.textContent = `${meta.feature_count} feature${meta.feature_count === 1 ? '' : 's'}`;
    detailEl.dataset.detail = meta.detail ?? '';

    clearCountdown();

    if (meta.status === 'rate-limited') {
      let remaining = meta.retry_after_s ?? 0;
      const render = () => {
        labelValue.textContent = `Rate-limited · retry in ${remaining}s`;
      };
      render();
      countdownIntervalId = setInterval(() => {
        remaining = Math.max(0, remaining - 1);
        render();
        if (remaining <= 0) {
          clearCountdown();
        }
      }, 1000);
    } else {
      labelValue.textContent = staticLabelFor(meta);
    }
  }

  return { container, update };
}
