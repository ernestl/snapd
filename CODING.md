# Coding checklist

How to participate in the project (CLA, reviews, pull requests):
[CONTRIBUTING.md](CONTRIBUTING.md).

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

## Further readings

* [Notes on state and changes](https://github.com/snapcore/snapd/blob/master/overlord/README.md)
