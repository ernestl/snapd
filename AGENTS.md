# snapd Development Guide for AI Agents

## Project Overview

**snapd** is the background daemon that manages snap packages across Linux
distributions. It is written in Go: daemon (`snapd`), CLI (`snap`), and
sandbox helpers (`snap-confine`, `snap-exec`).

The `snapd` binary also implements the client. The client is invoked when
`argv[0]` equals `snap`.

```
snap run <snap.app>  →  exec(snap-confine)  →  exec(snap-exec)  →  actual app
                        [sandbox setup]        [final prep]
```

See `ARCHITECTURE.md` for diagrams. Setup: `docs/hacking/setup.md`. Style
index: `CODING.md` (topics under `docs/coding/`).

## Overlord

`overlord.Overlord` coordinates state managers (`Ensure()`, optional `StartUp()`/`Stop()`).
Operations persist in `overlord/state.State` (`state.json`) as `state.Change` →
`state.Task` graphs with do/undo handlers. See `overlord/README.md`.

**Key managers:** `snapstate` (lifecycle), `ifacestate` (connections/profiles),
`assertstate` (assertions), `devicestate` (identity/Core/remodel), `hookstate` (hooks).

**Import rules:**

- `snapstate` is imported BY other managers but CANNOT import them
- Break circular imports with function hook variables (see `snapstate.ValidateRefreshes`)
- Assign hook variables in `init()` or `Manager()` constructors
- `*util` packages cannot import non-util packages
- `overlord/*state` is daemon-only, not imported by CLI tools (exception: subset of
  `overlord/configstate/configcore` via `nomanagers`)

Package layout and more import rules: `docs/coding/structure.md`.

### Task handlers

- Start with `st.Lock(); defer st.Unlock()`
- Unlock only for slow I/O or network; re-lock afterwards
- Non-idempotent work: `t.SetStatus(state.DoneStatus)` before unlock
- Undo must be symmetric and idempotent
- Task parameters: `t.Get("snap-setup", &snapsup)` as `SnapSetup`
- Device context: `DeviceCtx(task)`, not `DeviceCtxFromState()`

## Skills

Workflows in `.agents/skills/`:

- `run-spread-test` — run spread integration tests
- `build-snapd-snap` — build the snapd snap for testing
- `build-native-package` — build distro packages with kulturysta
- `bump-snapd-apparmor` — update bundled AppArmor in the snapd snap

When editing `interfaces/`, follow `interfaces/AGENTS.md`.

## Commands

Usually only `snap` and `snapd` are needed locally. Prefer a focused test over
the full suite. Native `go build`: `docs/hacking/build-native.md`. Unit tests,
hangs (`-check.vv`), and `LANG=C.UTF-8`: `docs/hacking/unit-tests.md`.

```bash
go build -o /tmp/build/snapd ./cmd/snapd
./run-checks
go test -v ./overlord/snapstate -check.v -check.f TestName
LANG=C.UTF-8 go test ./overlord/snapstate
make -C cmd check
```

Spread **runs**: use the `run-spread-test` skill. Spread **setup** (image-garden,
garden backend): `docs/hacking/spread.md`. Test snapd snap artifact:
`build-snapd-snap` skill. Installing a custom snapd snap on the host:
`docs/hacking/build-snapcraft.md` (not the spread skill). C/`snap-confine`:
`docs/hacking/snap-confine.md`.

## Conventions

Keep these always-on. Long form: `docs/coding/errors.md`, `docs/coding/tests.md`,
`docs/coding/spread-tests.md`, `docs/coding/prs.md`, `docs/coding/naming.md`.

- `gofmt -s` (enforced by `./run-checks`)
- Errors: lowercase, no period, `"cannot X"` not `"failed to X"`; prefix unexpected
  bugs with `"internal error:"`
- Keep error chains concise — avoid `"cannot: cannot: cannot"`
- Introduce `*Error` structs only when callers need to inspect them
- Tests: gocheck (`gopkg.in/check.v1`), not stdlib `testing` except benchmarks;
  `_test` package
- Export internals via `export_test.go`; mocks are `Mock*` returning a restore
  func (`testutil.Backup`)
- Test do and undo symmetrically; handlers must be idempotent; test error-path cleanup
- Mock at system boundaries (systemd, store), not internal packages
- Spread `task.yaml` section order (CI): `summary`, `details`, then optional
  `backends`/`systems`/`manual`/`priority`/`warn-timeout`/`kill-timeout`, then
  `environment`/`prepare`/`restore`/`debug`, then `execute`

## Boundaries

- Always add or update tests for behavior changes; run `./run-checks` before claiming done
- Never force-push after review, skip hooks, or commit secrets
- Never add `Co-authored-by`, `Signed-off-by` for the agent, or any trailer that
  credits an AI/agent/tool
- Do not attribute commits to Cursor, Copilot, Claude, ChatGPT, or any other assistant
- If a hook appends such a trailer, strip it before finishing
- Ask before mixing refactor with behavior changes, or diffs likely over ~500 lines

## PR and commits

Title: `affected/packages: short summary in lowercase`

```
overlord/snapstate: add helper to get gating holds
gadget,image: remove LayoutConstraints struct
o/snapstate: add user and gating holds helpers
many: correct struct fields and output keys
spread: remove old release of distribution
```

- Prefer "Squash and Merge"; rebase only when history is valuable; never a merge commit
- Separate refactoring from behavior changes; refactoring must not touch tests unless unavoidable
- Details: `docs/coding/prs.md`

## Debugging

```bash
sudo systemctl stop snapd.service snapd.socket
sudo SNAPD_DEBUG=1 SNAPD_DEBUG_HTTP=3 ./snapd
# SNAPD_DEBUG_HTTP: 1=requests, 2=responses, 4=bodies (bitfield)
SNAP_CLIENT_DEBUG_HTTP=7 snap install ...
```

More: `docs/hacking/debug-daemon.md`. Nested VMs: `docs/hacking/nested-tests.md`.

## Key files

- `ARCHITECTURE.md`, `overlord/README.md`, `spread.yaml`
- `CODING.md` and `HACKING.md` are human indexes; open the topic file for the task
- `docs/coding/` (naming, errors, structure, tests, spread `task.yaml`, PRs)
- `docs/hacking/` (setup, snapcraft, native build, unit tests, spread setup)
- `interfaces/AGENTS.md` and `interfaces/builtin/README.md` when changing interfaces
- Manager cache: `state.State.Cache()` with private keys

## Common patterns

1. State transitions persist: `state.Change` and `state.Task` survive restarts
2. Task handlers are retriable: design for idempotency
3. Device context is contextual: `DeviceCtx(task)`, not `DeviceCtxFromState()`
4. Conflicts serialize snap ops: `snapstate/conflict.go`
5. Disk state via `snapstate/backend`, never manipulate directly
6. Interface security profiles are additive
