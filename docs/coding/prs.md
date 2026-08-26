# PRs and refactorings

* PR should ideally have diffs of around 500 lines or less. There might be exceptions when size is due to large repetitive tests, but not for the production code. Experience indicates that smaller PRs are easier to review, while it is hard to do careful and punctual reviews for very large diffs.

* It is fair for reviewers to ask for large PRs to be split. It is also fair to ask for discussion on best strategies to do this with colleagues and architects.

* Whenever reasonable, avoid spurious differences between the code in master and the new code.

* If a change affects the REST API implemented in ./daemon, the REST API documentation needs to be updated in the same PR. If the ./docs/api folder has changes, the OpenAPI workflow will trigger automatically.

* Large mechanical refactoring and changes should be done as separate PRs. Try to separate behaviour changes and refactoring into different PRs and not mix the two.

* Refactoring should not touch preexisting tests. If changing a test is unavoidable, changes must be minimal. To ensure a refactor can be anchored, it's a good idea to check the coverage before starting, both in terms of lines of codes and in the features and behaviors that may be affected. Checking the coverage afterwards can also reveal whether there is old code that now can be dropped.

* Large moving of code around and changes to code placement might also be better done separately.

* PR summaries and the first line of commit messages are expected to be of this form:
  * *`affected full packages:  short summary in lowercase`*
    * When too many packages are involved, many can be used instead, or sometimes package names can be abbreviated by using single letters for the top-level package, when non ambiguous combined with the subpackage.
    * Examples:
      * `overlord/devicestate: add test to check connect hooks don't break anything`
      * `gadget,image: remove LayoutConstraints struct`
      * `o/snapstate: add helpers to get user and gating holds`
      * `many: correct struct fields and output key`
  * When no golang code is involved, the context prefix before the colon can refer to directories or top-level files instead.
    * `build-aux,.github/workflows: limit make processes with nproc`

* Merging
  * Only use `Squash and Merge` or `Rebase and Merge`, never `Create a merge commit`
  * `Squash and Merge`: Preferred method because it simplifies cherry-picking of PR content
    * Also for single commits
    * This merge will use the title as commit message so double check that it is accurate and concise
  * `Rebase and Merge`: Required when it is important to be able to distinguish different parts of a solution in the future
    * Keep commits to a minimum
    * Squash uninteresting commits such as review improvements after review approval
