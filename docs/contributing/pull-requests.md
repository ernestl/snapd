# Pull request guidelines

Contributions are submitted through a [pull request][pull-request] created from
a [fork][fork] of the `snapd` repository (under your GitHub account).

GitHub's documentation outlines the [process][github-pr], but for a more
concise and informative version try [this GitHub gist][pr-gist].

## Linear git history

We strive to keep a [linear git history][linear-git]. This makes it easier to
inspect the history, keep related commits next to each other, and make tools
like [git bisect][git-bisect] work intuitively.

## Pull request updates

Feel free to [rebase][github-rebase], rework commits, and [force
push][git-force] to your branch while a PR is waiting for its first review.

However, if you are still making significant changes during this waiting
phase, it's a good idea to keep the PR as a [draft][github-draft]. This stops
reviewers from looking at code you may not be confident about. Set the PR as
"Ready for review" when you do feel confident.

During the review process, reviewers will point out defects or suggest
alternative implementations.

After the first review, please treat your already pushed commits as immutable
and submit any requested changes as additional commits. This helps reviewers to
see exactly what has changed since the last review without requesting them to
review all the changes.

Two approvals are required for a PR to be merged. A PR can then be merged into the main branch.

After approval, you can rework the branch history as you see fit. Consider
squashing commits from the original PR with those made during the review
process, for example. Commit messages should follow the format described in
[prs.md](prs.md). A [force push][git-force] will be required if you
rework the history.

Start a [rebase][github-rebase] from the original parent commit of your first
commit. Ensure you do not rebase on top of the current main as this means
changes from the _main_ branch will be shown in the GitHub UI as part of your
changes, making the verification more confusing.

Merge using GitHub's [Squash and Merge][github-squash-merge] or [Rebase and
merge][github-rebase-merge], never [Create a merge
commit][github-merge-commit]. Details, including when to rebase-merge:
[prs.md](prs.md).

[pull-request]: https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request-from-a-fork
[fork]: https://docs.github.com/en/get-started/quickstart/fork-a-repo#forking-a-repository
[github-pr]: https://docs.github.com/en/github/collaborating-with-pull-requests
[pr-gist]: https://gist.github.com/Chaser324/ce0505fbed06b947d962
[linear-git]: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/defining-the-mergeability-of-pull-requests/about-protected-branches#require-linear-history
[git-bisect]: https://git-scm.com/docs/git-bisect
[github-draft]: https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/about-pull-requests#draft-pull-requests
[github-rebase]: https://docs.github.com/en/get-started/using-git/about-git-rebase
[git-force]: https://git-scm.com/docs/git-push#Documentation/git-push.txt---force
[github-rebase-merge]: https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/about-pull-request-merges#rebase-and-merge-your-commits
[github-squash-merge]: https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/about-pull-request-merges#squash-and-merge-your-commits
[github-merge-commit]: https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/about-pull-request-merges#merge-your-commits
