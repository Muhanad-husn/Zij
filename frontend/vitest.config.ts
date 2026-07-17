import { defineConfig } from 'vitest/config';

// Unit tests (Vitest) run in jsdom. Unit tests live under tests/unit/**.
export default defineConfig({
  test: {
    environment: 'jsdom',
    include: ['tests/unit/**/*.{test,spec}.ts'],
  },
});
