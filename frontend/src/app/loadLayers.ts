// Failure-isolation orchestration seam (spec FR10; reviewer stage-2 finding
// #1, issue #20). Previously `main.ts` used `Promise.all([...])` to fetch the
// air + land snapshots, so one domain's rejected fetch made `Promise.all`
// reject and blocked BOTH layers from rendering. `loadLayers` runs each
// task's `load()` concurrently via `Promise.allSettled`, renders only the
// fulfilled ones, and never throws — one domain failing must never block
// another from rendering.

/** One domain's fetch+render pair (dependency-injected so this seam stays
 * hermetic and framework-free — no map, no network, in its unit tests). */
export interface LayerLoadTask {
  label: string;
  load: () => Promise<unknown>;
  render: (snapshot: unknown) => void;
}

/** Runs every task's `load()` concurrently, calls `render` for each fulfilled
 * task, `console.warn(label, err)` + skips `render` for each rejected task,
 * and never throws. Returns a record of which labels succeeded. */
export async function loadLayers(tasks: LayerLoadTask[]): Promise<Record<string, boolean>> {
  const settled = await Promise.allSettled(tasks.map((task) => task.load()));

  const result: Record<string, boolean> = {};
  settled.forEach((outcome, index) => {
    const task = tasks[index];
    if (outcome.status === 'fulfilled') {
      task.render(outcome.value);
      result[task.label] = true;
    } else {
      console.warn(task.label, outcome.reason);
      result[task.label] = false;
    }
  });

  return result;
}
