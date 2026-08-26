# Agent instructions and skills

This directory holds on-demand workflows for coding agents. Shared always-on
rules live in the repository root, not here.

## Layout

| Path | Role |
|---|---|
| [`AGENTS.md`](../AGENTS.md) | Always-on agent guide: architecture map, locking, commands, conventions, boundaries |
| [`CODING.md`](../CODING.md), [`HACKING.md`](../HACKING.md), [`CONTRIBUTING.md`](../CONTRIBUTING.md) | Human indexes with short landings |
| [`docs/coding/`](../docs/coding/) | Coding/review topics (errors, tests, PRs, …) |
| [`docs/contributing/`](../docs/contributing/) | Contributor guidelines and PR workflow |
| [`docs/hacking/`](../docs/hacking/) | Developer setup and build topics |
| [`interfaces/AGENTS.md`](../interfaces/AGENTS.md) | Interface how-to, loaded when working under `interfaces/` |
| [`interfaces/CLAUDE.md`](../interfaces/CLAUDE.md) | `@AGENTS.md` so Claude Code loads the nested file |
| [`.github/copilot-instructions.md`](../.github/copilot-instructions.md) | Copilot adapter: `@../AGENTS.md` |
| [`CLAUDE.md`](../CLAUDE.md), [`GEMINI.md`](../GEMINI.md) | Thin adapters: `@AGENTS.md` plus tool-only notes |
| `.agents/skills/*/SKILL.md` | Multi-step workflows (spread, snap builds, packaging, AppArmor bump) |

There are no Cursor-only `.mdc` rules. Cursor reads `AGENTS.md` natively.

## Which tools we target

| Tool | What it reads |
|---|---|
| Cursor | `AGENTS.md` (and nested `AGENTS.md` when the session is in that tree) |
| GitHub Copilot | `AGENTS.md` for the coding agent; chat still uses `.github/copilot-instructions.md` |
| Claude Code | Root `CLAUDE.md`; nested `interfaces/CLAUDE.md` because Claude does not auto-load nested `AGENTS.md` |
| Gemini CLI | `GEMINI.md` |

Adapters must not duplicate project rules. Put shared guidance in `AGENTS.md`
or a topic file.

## Skills

- [`run-spread-test`](skills/run-spread-test/SKILL.md) — run spread integration tests
- [`build-snapd-snap`](skills/build-snapd-snap/SKILL.md) — build the snapd snap for testing
- [`build-native-package`](skills/build-native-package/SKILL.md) — distro packages with kulturysta
- [`bump-snapd-apparmor`](skills/bump-snapd-apparmor/SKILL.md) — bundled AppArmor in the snapd snap

Installing a custom snapd snap on the **host** is documented in
[`docs/hacking/build-snapcraft.md`](../docs/hacking/build-snapcraft.md), not in
the spread skill.

## Maintaining this

- Change a convention in the topic file (`docs/coding/`, `docs/contributing/`,
  or `docs/hacking/`) in the same PR as the code that depends on it. Update the
  one-line reminder in `AGENTS.md` only if the always-on rule changed.
- Do not grow root `AGENTS.md` with long samples or essays.
- Nested `AGENTS.md` is for package-specific checklists. For Claude Code, add a
  sibling `CLAUDE.md` containing `@AGENTS.md`.
- Skills are for fragile or slow procedures. Do not add a skill whose only job
  is “read CODING.md”.
