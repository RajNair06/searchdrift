# SearchDrift — Claude Context

All shared project context lives in AGENTS.md, imported here so the two never drift apart:

@AGENTS.md

## Start of every session

1. Read `PROGRESS.md` → "Current position" and "Next actions".
2. Read `docs/project.md` (what we're building) and the current week in `docs/plan.md`.
3. Work only on the current week's scope.
4. Pick the next unchecked chunk of the week's build checklist and run it
   through the learn + build loop in AGENTS.md ("How we work"): teach the
   fundamentals it touches, build it, explain *why* and *how* the code works,
   prove it with tests, give self-test questions, then stop at a checkpoint.

## Claude-specific notes

- **Update progress at every checkpoint** (each finished chunk, each confirmed
  decision, and before ending a session), exactly as listed in AGENTS.md →
  "Keeping progress up to date": `PROGRESS.md` sections, `AGENTS.md` current
  status, entity doc status lines. Tell the user in one line what was updated.
- Don't commit without being asked; end commit messages with the attribution line from the harness.
