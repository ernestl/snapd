# Hacking on snapd

Hacking on `snapd` is fun and straightforward. The code is extensively unit
tested and we use the [spread](https://github.com/canonical/spread-plus)
integration test framework for the integration/system level tests.

For non-technical details on contributing to the project, including how to
approach a pull request, see [Contributing to snapd](./CONTRIBUTING.md).

## Setting up

Ubuntu 18.04 LTS or later (latest LTS preferred) and Go 1.18 or later are
recommended. Clone the tree, then install distro build dependencies with
`apt build-dep` on Ubuntu or the Fedora `rpmspec` equivalent.

Full steps, including the tagged snippets used by the smoke test:
[docs/hacking/setup.md](docs/hacking/setup.md).

## Building

### Building the snap with snapcraft

The usual way to test a custom snapd is to build the snapd snap with snapcraft
and install it with `snap install --dangerous`. That file also covers
`remote-build` and splicing snapd into a core snap.

Full steps: [docs/hacking/build-snapcraft.md](docs/hacking/build-snapcraft.md).

### Building natively

The `snap` client and `snapd` are the same binary, selected by `argv[0]`. Use
`go build` to produce `/tmp/build/snapd` (and optionally a `snap` symlink).

Full steps: [docs/hacking/build-native.md](docs/hacking/build-native.md).

### Building with cross-compilation (_example: ARM v7 target_)

Cross-compiling needs a matching GCC, CGO, and a cross-built libseccomp.
Full steps: [docs/hacking/cross-compile.md](docs/hacking/cross-compile.md).

## Testing

We value good tests. When you fix a bug or add a feature, add tests. Install
the extra packages listed in the unit-test topic, then use `./run-checks` and
`go test`.

### Running unit-tests

`./run-checks` covers format, build, tests, and `go vet`. Individual tests use
`go test -check.f`; hangs need `-check.vv`. Use `LANG=C.UTF-8` if tests fail
on other locales.

Full steps: [docs/hacking/unit-tests.md](docs/hacking/unit-tests.md).

### Running integration tests

Install spread (via the `image-garden` snap), then `./run-spread`. The garden
backend runs most tests locally without a cloud account.

Setup and reuse notes: [docs/hacking/spread.md](docs/hacking/spread.md).

### Testing the snapd daemon

Stop the system snapd, then run a locally built daemon with `SNAPD_DEBUG` and
`SNAPD_DEBUG_HTTP`. The same topic covers `snap userd --agent`.

Full steps: [docs/hacking/debug-daemon.md](docs/hacking/debug-daemon.md).

### Testing the snap userd agent

Stop the user session agent socket, then run `snapd userd --agent`.
Full steps: [docs/hacking/debug-daemon.md](docs/hacking/debug-daemon.md).

### Running nested tests

Nested suites boot a fresh image per test (classic, core, core20, manual).
They still run under spread; host vs nested Ubuntu mapping and `NESTED_*`
variables are in [docs/hacking/nested-tests.md](docs/hacking/nested-tests.md).

# Quick intro to hacking on snap-confine

`snap-confine` is the C sandbox helper. Build with `./mkversion.sh`,
`cmd/autogen.sh`, and `make`. Use `make hack` / `make check` / `make fmt`
from `cmd/`.

Full steps: [docs/hacking/snap-confine.md](docs/hacking/snap-confine.md).

<!-- !TODO: Few things to clean up in the future:

[] Add a section that describes functional labels in GitHub that we use to influence the verification flow of the PR
[] Remove reference to https://bugs.launchpad.net/snapd/+bug/1960131 once it gets fixed

//-->
