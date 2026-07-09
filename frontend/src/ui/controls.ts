// Connection-lost banner (spec §7/§3). One global banner, mounted once,
// updated imperatively off `store.on('connection', ...)` — no framework.

import type { Connection, Store } from '../state/store';

export interface ConnectionBanner {
  container: HTMLElement;
}

/**
 * Mounts the single global connection banner into `parent`. Hidden while
 * `connection` is `connecting`/`open`. Shows a non-blocking "Reconnecting…"
 * strip while `lost`; shows "Connection failed" plus a Retry button while
 * `failed`. Clicking Retry calls `onRetry()` (wired by the caller to
 * `SseClient#connect()`), which must issue a fresh `/api/events` request.
 */
export function mountConnectionBanner(parent: HTMLElement, store: Store, onRetry: () => void): ConnectionBanner {
  const container = document.createElement('div');
  container.className = 'zij-connection-banner';
  container.dataset.testid = 'connection-banner';
  // Inline `display` is used (rather than a CSS class + the `hidden`
  // attribute) so visibility always wins the cascade regardless of any
  // author stylesheet rule targeting `.zij-connection-banner`.
  container.style.display = 'none';

  const text = document.createElement('span');
  text.className = 'zij-connection-banner__text';
  container.appendChild(text);

  const retryButton = document.createElement('button');
  retryButton.type = 'button';
  retryButton.dataset.testid = 'connection-retry';
  retryButton.textContent = 'Retry';
  retryButton.style.display = 'none';
  retryButton.addEventListener('click', () => {
    onRetry();
  });
  container.appendChild(retryButton);

  function render(connection: Connection): void {
    if (connection === 'lost') {
      container.style.display = 'flex';
      text.textContent = 'Reconnecting…';
      retryButton.style.display = 'none';
    } else if (connection === 'failed') {
      container.style.display = 'flex';
      text.textContent = 'Connection failed —';
      retryButton.style.display = 'inline-block';
    } else {
      container.style.display = 'none';
      retryButton.style.display = 'none';
    }
  }

  store.on('connection', (payload) => render(payload as Connection));
  render(store.getState().connection);

  parent.appendChild(container);

  return { container };
}
