---
description: Resume the agentic-engineering-org build from where it left off — reads docs/agentic-build.md, finds the next unfinished phase, and continues under the same rules and checkpoints.
---
You are **resuming** a supervised, phase-by-phase build of the
`agentic-engineering-org` workflow in this repo (Zij). This is a continuation, not a
fresh start. **Do NOT restart from Phase 0** and do NOT re-scaffold anything that
already exists.

Follow these steps in order:

1. **Read the source of truth.** Read `docs/agentic-build.md` in full: the
   **Progress Tracker** (each phase's status) and the **Decision Log** (DEC-1..N —
   the binding decisions and Zij-specific adaptations already made). These override
   any default assumption from the skill's generic skeletons.

2. **Load the playbook.** Invoke the `agentic-engineering-org` skill (Skill tool) for
   the phase-by-phase plan, then read the matching file under that skill's
   `references/` for the phase you are about to resume (e.g. `hooks.md` for Phase 3,
   `harness-and-sprint.md` for Phases 4–5).

3. **Sync git state.** `git fetch`; note the current branch; check which
   `setup/*` branches are merged into `origin/main`. The tracker plus git together
   tell you exactly where things stand.

4. **Pick the resume point.** Find the first phase whose status is not `DONE`
   (a phase marked "DONE — awaiting Checkpoint N" means the work is done but the
   founder's approval is pending: confirm with the founder before proceeding past it).
   Resume there. Honor every ⛔ CHECKPOINT — stop and wait for the founder's explicit
   "approved" before starting the next phase; never infer approval.

5. **Obey the binding operating model** (see `docs/agentic-build.md` and CLAUDE.md):
   - Do all work on a `setup/<phase-slug>` branch.
   - Privileged actions (merge to `main`, branch protection, deleting branches/data,
     pushing to `main`) are **approval-gated**: ask the founder, and on "approved"
     **this orchestrator (main session) executes them** — never a build subagent.
   - The deterministic gates hold: build subagents and the GitHub plugin's merge tool
     can never merge; the tests-green hook blocks commits on a red suite.
   - Dispatch build work (spec / test / implementation / review) to the tool-locked
     role subagents in `.claude/agents/`.
   - Hooks and scripts on this Windows host are **PowerShell**, invoked explicitly as
     `pwsh -NoProfile -File <script>.ps1` (not the `shell` hook field — see DEC-24).

6. **Keep the tracker live.** Update `docs/agentic-build.md` (Progress Tracker rows +
   new DEC rows) as you complete work, exactly as prior phases did.

Begin by stating: which phase you are resuming, its status, and the plan for it.
Then proceed.
