// Layer badge DOM (spec §4). v0 (this slice): freshness timestamps (UTC) +
// feature count only — status color/label, toggle/refresh-per-layer/caveats
// controls are later slices. Built once per domain, updated imperatively via
// `update()` (no framework, per ADR-3).

import { formatUtc } from '../util/formatUtc';
import type { LayerSnapshotMeta } from '../state/types';

export type BadgeDomain = 'air' | 'land';

interface Badge {
  container: HTMLElement;
  update(meta: LayerSnapshotMeta): void;
}

/** Builds one badge container (`[data-testid="badge-{domain}"]`) with its
 * freshness/count seams, and mounts it into `parent`. */
export function mountBadge(parent: HTMLElement, domain: BadgeDomain): Badge {
  const container = document.createElement('div');
  container.className = 'zij-badge';
  container.dataset.testid = `badge-${domain}`;

  const title = document.createElement('div');
  title.className = 'zij-badge__title';
  title.textContent = domain.toUpperCase();
  container.appendChild(title);

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

  parent.appendChild(container);

  function update(meta: LayerSnapshotMeta): void {
    fetchedValue.textContent = formatUtc(meta.timestamp_fetched);
    sourceValue.textContent = formatUtc(meta.timestamp_source);
    countValue.textContent = `${meta.feature_count} feature${meta.feature_count === 1 ? '' : 's'}`;
  }

  return { container, update };
}
