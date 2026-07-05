---
name: red-green-refactor
description: Use to implement one slice test-first with disciplined double-loop TDD — an outer failing end-to-end or integration test wrapping inner unit-test red, green, refactor cycles, worked outside-in until the acceptance test is green. Phase 2 and the heart of the TDD harness. Trigger on 'red green refactor', 'TDD this', 'write a failing test then make it pass', 'implement slice NN', or working through a plan in plans/. Enforces the discipline literally — never write production code without a failing test, watch every test fail first, minimum code to green, refactor only on green.
---

# Red-Green-Refactor — Double-Loop TDD (Phase 2)

Develop **one slice** by driving it outside-in: a failing acceptance (e2e/integration) test sets the goal, and inner unit-test red→green→refactor cycles build the code that makes it pass. Both test layers grow together. This is the core discipline of the whole harness.

**Read `references/red-green-refactor-philosophy.md` now** if you have not this session — it is the authoritative rulebook, and everything below is a summary of it. For detecting and running the project's test tooling (unit runner + Playwright e2e) across stacks, read `references/test-strategy.md`.

> ## Zij adaptation (roles, gates, stack) — overrides the generic body below
> This skill runs inside the Zij enterprise (see `CLAUDE.md`). Three overrides:
>
> 1. **DEC-1 role split — the outer acceptance test is NOT yours to write.** In Zij, the **test-author** authors the slice's outer acceptance test and commits it **red**; it is the **locked behavioral contract**. When you (the **implementer**) run this skill you **enter at step 6 and drive the inner unit red→green→refactor cycles only.** You may **not** create, edit, delete, weaken, or re-baseline the outer acceptance test, and you may not touch `design/**` specs — the path-guard hooks block writes under `**/tests/` and `design/` for the implementer anyway, so an attempt is denied, not just discouraged. If the locked outer test looks wrong, **stop and raise a `spec-drift` issue** (never edit it to force green). Steps 1–5 below describe test-author work done in a **prior** step; read them as context, do not perform them. The outer test must already exist and be red before you start.
> 2. **Gates (Phase 3) are live.** `uv run pytest` runs before every `git commit` (tests-green hook) — a red suite blocks your own commit, by design. `git merge` / `gh pr merge` / plugin-merge are blocked for subagents. Commit small and green; never try to merge — `safe-pr` only *prepares* the PR.
> 3. **Stack + non-web default.** The suite is **`uv run pytest`**; lint is **`uv run ruff check`** (run it in your REFACTOR step, step 9/13). Zij is a **FastAPI + pipeline** product, so the default outer endpoint is an **HTTP route or a CLI/pipeline invocation with a captured transcript** — **Playwright is optional**, used only if a real MapLibre `frontend/` web slice needs it. Ignore any "the harness requires a screenshot + recording" wording below for non-web slices; the evidence is the test-run transcript plus a real-endpoint invocation transcript (see `safe-pr`).

## Input

A slice plan: `plans/<feature-slug>/<NN>-<slice-slug>.md`. If the user names a slice, open that file. If no plan exists, stop and run `tdd-plan` first (or ask the user to) — **no code before a plan**. Work on exactly one slice; never batch slices.

## Setup (once per slice)

1. **Read the plan.** Internalise the goal, the acceptance criterion (Given/When/Then), the seeded unit test list, and what's out of scope.
2. **Cut the branch.** From an up-to-date `main`, create `feat/<feature-slug>/<NN>-<slice-slug>` (see `references/test-strategy.md` if unsure). Never develop a slice on `main`.
3. **Detect test tooling.** Identify the unit runner and the e2e setup (see `references/test-strategy.md`). If Playwright (or a unit runner) is needed and absent, set it up now as part of the slice — a walking-skeleton slice exists precisely to establish this. Note the plan's **Project directory**: if the app lives in a subfolder, run install/test/build from there (the branch is still cut at the repo root). For a walking-skeleton slice, set the project directory up now and record it in the plan if the planner left it open.

## The OUTER loop (acceptance / e2e — the "are we done" signal)

4. *(test-author, prior step — context only for the implementer)* **Write ONE failing acceptance test** for the slice's acceptance criterion, exercising the system **only through its real external endpoint** (in Zij: an HTTP route via the FastAPI test client / a running server, or a CLI/pipeline invocation — a browser page via Playwright only for a real `frontend/` web slice) — never by calling internal code. Use the user's language. For a browser slice only, configure the Playwright acceptance project to **record video** (`video: 'on'`) and screenshot the decisive assertion; for the default non-web slice the evidence is a captured **transcript** of the passing run instead (`safe-pr` attaches whichever applies).
5. **Run it and watch it fail.** Confirm it fails **because the feature is absent**, with a readable diagnostic — not because of a typo, missing import, or misconfigured harness. If you can't articulate why it fails, you don't understand the requirement yet. This failing acceptance test is now your progress meter; it stays red until the slice is done.

## The INNER loop (unit — the "how / quality" signal)

Repeat per behaviour, working **inward from the boundary** named by the acceptance test. Mock collaborators that don't exist yet to design their interfaces cheaply.

6. **THINK.** Pick the single smallest next behaviour that moves the acceptance test toward green. Add it to the plan's unit test list if it's new.
7. **RED.** Write one small failing unit test (~5 lines). Run it. **Watch it fail for the right reason** and check the diagnostic is clear.
8. **GREEN.** Write the **minimum** code to pass — Fake It / hard-code a constant if you're unsure; ugliness is fine here. Run the behaviour's unit test plus the full **unit** suite (not the slow e2e suite — that runs when closing the loop and before commit) and confirm green. Implement **nothing** that no test demands.
9. **REFACTOR (only on green).** Remove duplication (especially any hard-coding from step 8), clarify names, extract collaborators — **without changing behaviour**. Re-run tests after **each** small change. If a refactor reddens the bar, **revert it — do not fix forward**. Add no new behaviour.
10. **Log it.** Append a one-line entry to the plan's "Status / progress log" (e.g. `<date> green: TokenGenerator returns url-safe token`). Tick the unit-list checkbox.
11. **Step sizing.** Obvious Implementation when confident; Fake It when unsure; Triangulate (require a second example) before generalising. On any **unexpected red**, downshift to smaller steps and run tests more often.

Repeat 6–11 until enough code exists for the acceptance test to pass.

## Close the OUTER loop

12. **Re-run the acceptance test** (the locked outer test — run it, never edit it). If still red, you're missing a piece — return to the inner loop. If green, the slice's behaviour is demonstrably complete — capture the passing run as evidence: for the default non-web slice a **transcript** of the passing acceptance run plus a real-endpoint invocation; for a web slice a **video recording and a screenshot** (re-run with `video: 'on'` if not). `safe-pr` attaches whichever applies.
13. **Outer refactor.** With the **whole suite green**, clean up across module/boundary scope (duplication between the new code and existing code, leaky abstractions, names). Re-run the full suite after each change.
14. **Full green check + commit.** Run the entire suite (**`uv run pytest`**) and confirm green; run **`uv run ruff check`** and fix lint. Commit in small, green-only commits using Conventional Commit style, e.g. `feat(<feature-slug>): <goal> [slice NN]`. The **tests-green hook re-runs the suite and blocks the commit if red** — this is the gate, not a formality. Never commit on red, and never attempt to merge (`safe-pr` prepares the PR; the founder merges). (You may leave one test red in the **uncommitted** working tree as a cross-session resume marker, but never commit or push a red bar.)
15. **Update the plan.** Mark the Definition-of-Done boxes that are now satisfied; set the slice status toward done.

## Invariants — must hold at all times

- No production code exists without a failing test (unit **or** acceptance) that you watched **fail first**. For a walking skeleton, the failing acceptance test may be the only driver.
- The bar is **green before and after every refactoring**; never refactor on red.
- **No new behaviour during a refactor** — structure only. New behaviour needs a fresh RED.
- **Done = the acceptance/e2e test is green** and the full suite passes — not unit coverage. Never trade global correctness for local coverage.
- Eliminate duplication before closing each cycle.
- When stuck or surprised by red: **shrink the step and run the tests more.**

## Both test layers, always

This harness requires **both** unit tests and end-to-end/integration tests, and double-loop TDD is how they coexist: the e2e test defines and gates the slice; the unit tests drive and verify the internals. You cannot finish the slice until the e2e test is green, and you never write internal code without a unit test — so both suites accumulate together. See `references/test-strategy.md` for how each layer is written and run, and how Playwright is configured to capture the screenshots and recordings that `safe-pr` will attach as review evidence.

## Hand-off

When the slice is green and committed, tell the user it's ready and recommend the next phases: `tdd-ci` to run these tests in GitHub Actions, then `safe-pr` to open the reviewable PR. If running under `tdd-harness`, return control to the orchestrator.
