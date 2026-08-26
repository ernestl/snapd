# Coding/Review checklist

## Why reviews?

* Reviews can give input on whether the proposed code is seemingly correct and reasonable in the context of project practices, and whether it seems sufficiently tested.

* Code can have a long lifetime; the effort to maintain and adapt it in the future can be much larger than the original effort to produce the first version of it. Reviews from other team members should therefore focus on:
  * Is the new code readable and understandable, alongside other attributes that can help future maintainability?
  * Could the code be simplified?

## Naming conventions

Follow [Go naming conventions](https://go.dev/doc/effective_go#names): balance concision and clarity, stay consistent with nearby code, and prefer specific names for unexported package-level symbols. Comments should explain why or the abstract effect, not restate the code. Function parameters follow a conventional order (`context`, ambient objects such as `state.State`, then the main entities).

Full guidance: [docs/coding/naming.md](docs/coding/naming.md).

## Error and error messages

Error messages start with lowercase and have no trailing period. Prefer *"cannot …"* over *"failed to …"*. Use `"internal error: …"` only for unexpected internal inconsistencies. Introduce `*Error` structs only when callers need to inspect them.

Full guidance: [docs/coding/errors.md](docs/coding/errors.md).

## Code structure and style

Apply `go fmt`, avoid naked returns, and split packages by increasing application-specific abstraction (`snapstate` → `backend` → `boot`). `snapstate` cannot import other managers; `*util` packages cannot import non-util packages; most of `overlord` is daemon-only (`nomanagers` excepts a subset of `configcore`).

Full guidance: [docs/coding/structure.md](docs/coding/structure.md).

## Tests

We use gocheck (not stdlib `testing`, except benchmarks), prefer `_test` packages, and export internals via `export_test.go` `Mock*` helpers that return a restore func. Mock at system boundaries. Full guidance, including fixtures and manager-test scope: [docs/coding/tests.md](docs/coding/tests.md).

## Functional/integration tests

Externally visible behaviour should have [spread](https://github.com/canonical/spread-plus) tests. `task.yaml` section order is enforced by CI (`summary` and `details` required, `execute` last).

Full guidance: [docs/coding/spread-tests.md](docs/coding/spread-tests.md).

## PRs and refactorings

Keep diffs around 500 lines or less, separate refactoring from behaviour changes, and do not mix test changes into refactors unless unavoidable. PR titles look like `package: short summary in lowercase`. Prefer squash-and-merge.

Full guidance: [docs/coding/prs.md](docs/coding/prs.md).

## Further readings

* [Notes on state and changes](https://github.com/snapcore/snapd/blob/master/overlord/README.md)
