import { defineConfig } from 'vitest/config';

// Unit tests (Vitest) run in jsdom. The test-author adds units under tests/unit/**
// from the plan's inner unit list; this config is ready for them.
export default defineConfig({
  test: {
    environment: 'jsdom',
    include: ['tests/unit/**/*.{test,spec}.ts'],
  },
});
