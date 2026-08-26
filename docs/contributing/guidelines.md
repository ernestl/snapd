# Contributor guidelines

Contributors can help us by observing the following guidelines:

- Commit messages should be well structured.
- Commit emails should not include non-ASCII characters.
- Several smaller PRs are better than one large PR.
- Try not to mix potentially controversial and trivial changes together.
  (Proposing trivial changes separately makes landing them easier and
  makes reviewing controversial changes simpler)
- Do not [force push][git-force] a PR after it has received reviews. It is
  acceptable to force push when a PR is ready to merge, however.
- Try to write tests to cover the contributed changes (see
  [Pull requests and tests](../../CONTRIBUTING.md#pull-requests-and-tests))

For coding conventions see [CODING.md](../../CODING.md). For how to slice,
title, and merge a PR see [prs.md](prs.md).

[git-force]: https://git-scm.com/docs/git-push#Documentation/git-push.txt---force
