# Contributing to snapd

We are an open source project and welcome community contributions, suggestions,
fixes and constructive feedback.

If you'd like to contribute, you will first need to sign the Canonical
contributor agreement. This is the easiest way for you to give us permission to
use your contributions. In effect, you’re giving us a licence, but you still
own the copyright — so you retain the right to modify your code and use it in
other projects.

The agreement can be found, and signed, here:
https://ubuntu.com/legal/contributors

If you have any questions, please reach out to us on our forum:
https://forum.snapcraft.io/c/snapd/5

## Getting started

Clone the tree and install build dependencies:
[docs/hacking/setup.md](docs/hacking/setup.md). The human index for building,
testing, and debugging is [HACKING.md](HACKING.md). How to write Go is
[CODING.md](CODING.md).

## Why reviews?

Reviews can give input on whether the proposed code is seemingly correct and
reasonable in the context of project practices, and whether it seems
sufficiently tested.

Code can have a long lifetime; the effort to maintain and adapt it in the
future can be much larger than the original effort to produce the first version
of it. Reviews from other team members should therefore focus on:

* Is the new code readable and understandable, alongside other attributes that
  can help future maintainability?
* Could the code be simplified?

## Contributor guidelines

Prefer small PRs, do not mix trivial with controversial changes, write tests,
and do not force-push after a PR has been reviewed (force-push is OK when ready
to merge). Commit emails must be ASCII.

Full guidance: [docs/contributing/guidelines.md](docs/contributing/guidelines.md).

### External and AI-assisted contributions

External or fully AI-submitted PRs need a sponsor from the team
assigned to them (as GH assignee). The sponsor is responsible,
with help from others on the team if needed, for evaluating the
contributions for viability and priority and then for helping carry
the PR(s) to landing.

Preferably AI-assisted contributions should disclose this and, when
reasonable and relevant, provide prompt(s) and tooling information in
their descriptions.

While we will not prejudge AI-assisted contributions either way on
correctness, it is important that they are targeted and relatively
small, or split across many PRs. It is also important to pay extra
attention to readability and code placement (the latter may not
always be evident in diffs as presented on GH).

We might simply reject scattershot or overly large PRs.

Coding agents should follow [`AGENTS.md`](AGENTS.md). Thin adapters exist for
Copilot, Claude Code, and Gemini CLI; do not duplicate those rules elsewhere.
Humans still follow this file, [`CODING.md`](CODING.md), [`HACKING.md`](HACKING.md),
and the topic files under [`docs/contributing/`](docs/contributing/),
[`docs/coding/`](docs/coding/), and [`docs/hacking/`](docs/hacking/).

## Pull requests and tests

CI runs static checks, unit tests, and spread integration tests on every PR.
Tests are not required to open a PR, but we rarely merge without them (we may
write them on your behalf). Reviewers will say if tests are still needed.

How to run tests: [docs/hacking/unit-tests.md](docs/hacking/unit-tests.md).

## Pull request guidelines

Open a PR from a [fork][fork]. Keep history linear. After the first review, add
commits instead of rewriting; two approvals are required to merge.

How to open and update a PR:
[docs/contributing/pull-requests.md](docs/contributing/pull-requests.md).

How to slice the diff, title it, and merge:
[docs/contributing/prs.md](docs/contributing/prs.md).

### Labels

We add [GitHub labels][github-labels] to a PR for both organisational purposes
and to alter specific CI behaviour. Only project maintainers can add labels.

The following labels are commonly used:

- `Simple 🙂`: informs potential reviewers the PR can be reviewed quickly.
- `Test robustness`: either fixes tests, adds tests, or otherwise improves our
  test suite.
- `Documentation`: is used to denote a PR that requires typically small
  documentation changes, either internally (to this repository) or externally.
- `Needs documentation`: not to be confused with the above. This label needs to
  be added when a PR introduces new features which need to be documented for
  our users, or if the PR changes the behaviour of already documented
  features (though this should almost never happen).
  * Our user-facing documentation can be found here: https://snapcraft.io/docs
  * The PR description must explain any required documentation changes.
  * For internal documentation in this repository, it's expected that
    documentation changes are delivered in the same branch.
    Please don't abuse this tag.
- `Needs Samuele review`: Samuele (@pedronis) is our architect, and this label
  will summon his attention. Do not use it unless you want @pedronis to review
  your branch. If making big or deep changes, then ping Samuele in advance. The
  tag will then be added if necessary. When requesting a quick high-level green
  light about a chosen approach use a [draft PR][github-draft] to avoid the risk
  of other reviewers wasting time on something that has not been agreed upon.
- `Needs security review`: similar to above, but with a security focus. If your
  changes touch code in snap-confine or code related to AppArmor, Seccomp,
  Cgroup management, then someone from the security team will be alerted and
  will review your code.
- `Run nested`: instructs our CI system to run our container-based
  [nested tests][nested-tests]. These tests are usually skipped to save time,
  but they're useful to test a PR  against certain operating system traits that
  might otherwise be missed.
- `Skip spread`: instructs our CI system to not run any spread tests. Only unit
  tests will be executed. Use this when a PR only changes code in the unit tests.
  Do not use this flag if any production code changes.
- `Run only one system`: instructs our CI system to only run one system or a
  subset of systems. To run a subset of systems, add the case-insensitive tag
  `#runonlyonesystem` followed by a regex somewhere in your PR description on its
  own line. The regex should select the systems you wish to run as known to
  our CI. For a list of systems, check
  `.github/workflows/data-*fundamental-systems.json`

  Examples:
  - Run all opensuse and fedora systems: `#runonlyonesystem (opensuse|fedora)`
  - Run all non-core ubuntu systems: `#runonlyonesystem ^ubuntu(?!-core).*`
  - Run only jammy: `#runonlyonesystem ubuntu-22.04-64`

[1]: http://www.ubuntu.com/legal/contributors
[fork]: https://docs.github.com/en/get-started/quickstart/fork-a-repo#forking-a-repository
[github-draft]: https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/about-pull-requests#draft-pull-requests
[github-labels]: https://docs.github.com/en/issues/using-labels-and-milestones-to-track-work/managing-labels
[nested-tests]: https://github.com/snapcore/snapd/tree/master/tests/nested
