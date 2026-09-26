# CLAUDE.md — House Rules

Random Dance combiner: downloads a list of YouTube songs (only the given time ranges) and combines them into one long video/audio with countdowns in between. Maintained across student generations, so clarity beats cleverness.

## Current phase

**SPIKE** — throwaway exploration. Work only in `scratch/` on a `spike` branch. This code will be deleted, never merged. Its only output that matters is what you record in `docs/TECH.md`.

_(Maintainer updates this section when the phase changes: spike → skeleton → slice N.)_

## Read before working

1. `docs/SPEC.md` — what and why. Owned by the maintainer.
2. `docs/TECH.md` — how. Implementation facts, quirks, findings. You maintain it.
3. `docs/HANDOFF.md` — gotchas for successors.

## Authority

- **docs/SPEC.md wins** over TECH.md and over your own judgment.
- If your work conflicts with the spec, or a finding would change a goal, a port, or operator-facing behavior: **stop and flag it**. Do not edit SPEC.md. The maintainer decides whether the spec or the code changes.
- Record new technical findings in `docs/TECH.md` as you go — including dead ends and why they failed.

## Git

- Never commit to `main`. Never merge. Work on a branch per slice.
- Small, focused commits. At the end, report: what changed, what was verified, what was **not** verified.
- Commit doc changes separately from code changes.

## Architecture (hexagonal) — the most important rules

- **Core must not import anything from adapters, the GUI, or third-party tools** (yt-dlp, FFmpeg helpers, tkinter, HTTP libraries). If core needs it, it goes through a port.
- **Ports belong to the core** and live with the core, not with the adapters.
- **Ports speak the core's language, not a tool's.** Test: could this port be implemented with a completely different tool? If it mentions anything only yt-dlp / FFmpeg / Google has, it's leaking.
- **Errors crossing a port are the project's own error types**, never a library's exceptions.
- **Never change a port signature without asking.** New ports are proposed first, approved by the maintainer, then implemented.
- GUI never calls yt-dlp or FFmpeg directly; it only talks to the core.

## Do not change without asking

- TOML config schema (`config/example.toml`) and the Google Sheet column format — the dance group depends on these.
- Pinned versions in `requirements.txt` and the supported Python range file.
- yt-dlp must stay **unpinned** (always latest). Do not pin it, and do not unpin anything else.

## Files and data

- Never write outside `workspace/` at runtime (downloads, cache, outputs, logs all go there).
- Never commit media, `workspace/`, `config.toml`, credentials, `.venv/`, or `CLAUDE.local.md`.

## FFmpeg

- Every FFmpeg call goes through the single helper module. No ad-hoc `subprocess` calls elsewhere.
- Binary path is always passed explicitly, separate from the argument list. Never rely on `ffmpeg` being on PATH.

## Done means

- The slice's acceptance condition (given with the task) is met.
- The smoke test passes (once it exists).
- Don't claim something works unless you ran it. Say so if you couldn't.