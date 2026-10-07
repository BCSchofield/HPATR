# HPATR — instructions for Claude

High-Performance Aerosol Testing & Research: shadowgraph imaging of effervescent silicone
atomisation (Ben's PhD). Branches: work on `Testing`; `Main` is the PR target.

## Start here

**Read `docs/STATUS.md` before any work on the droplet pipeline, the Taguchi study or the
Taguchi_Analysis_UI app.** It is the current state: what's done, what's next, open questions,
known bugs, where the data is.

**Keep it current.** Before finishing any task that changes the state of the project (a step
done, a result obtained, a bug found or fixed, a decision made, a plan changed), update
`docs/STATUS.md` in place and bump its "Last updated" line. Do this without being asked; say in
the reply that you did. Its last section says how.

`docs/archive/HANDOFF_real_data_pipeline_LEGACY.md` is frozen history (to 2026-10-07). Read the
relevant section when STATUS.md points there or when you need the evidence behind a decision.
Never edit it.

## Other docs

- `docs/TAGUCHI_ANALYSIS_UI_PLAN.md`: the app's design and per-phase build record.
- `docs/TAGUCHI_WINDOWS_RUN_SHEET.md`: running a batch on Windows.
- `docs/definitions.md`: definitions of every reported quantity.
- `docs/VALIDATION_LABELLING_PROTOCOL.md`: how the hand-labelled frames are made.
- `docs/CLAUDE_Understanding.md`: older whole-codebase notes (pre-dates the real-data pipeline).

## Commands (Mac)

```
/Users/benschofield/anaconda3/envs/phantom/bin/python3 -m pytest /Users/benschofield/Documents/GitHub/HPATR/src/ai/Taguchi_Analysis_UI/tests -q
cd /Users/benschofield/Documents/GitHub/HPATR && /Users/benschofield/anaconda3/envs/phantom/bin/python3 -m src.ai.Taguchi_Analysis_UI
```

The `phantom` env has no torch/detectron2; inference and batches run on the Windows PCs (see the
Machines table in STATUS.md).

## Working rules

- Never modify raw data on the LaCie (`/Volumes/LaCie/Experiments/<date>/<run>/` captures).
  Analysis writes to its own output folder.
- Phase-gated work: do the phase asked for, then stop and report.
- Give Ben exact paste-able commands: absolute paths, quoted if they contain spaces, the real
  interpreter path.
- Ben knows the domain; don't re-explain concepts. Flag real problems directly.
