# Tests

Tests should help with these aspects:

* Illustrate (and help clarify while writing the code) the intent and behaviour of code.
* Anchor the correctness of the code, to the extent possible, from this POV while we try to keep a high coverage without overdoing. One should keep in mind that line coverage might itself not be enough. Lines of code can be covered without being tested as only part of a predicate might be triggered, or some code could be removed and no test breaks unless tests were targeting it. So when writing tests it is always important to take on an expectations and behaviours mindset.
* Help later to have some confidence when refactoring.

We do not mandate TDD, but it's always a good idea when possible to start at least from happy path tests for new code/behaviour.

Bug fixes should be covered by new tests, for which is important to verify that they do not pass and fail as expected prior to the fix.

Coverage of error handling is important as well:

* Complex error handling should be tested
* Undo/restore behaviour on error, if any, should be tested
* Error generation that produces errors that are expected/inspected by callers should be tested
* Simple unexpected/give up error paths may not necessarily need to be tested
* The return paths in code like:

  ```
      if […;] err != nil {
         return err
      }
  ```

  might not need to be tested if it's too cumbersome to trigger them, but the other considerations need to be taken into account. Reviewers should keep under consideration that golang error handling conventions are followed.

We use [gocheck](https://labix.org/gocheck) and our own testutil package for snapd tests, to complement what is provided by go and golang standard library.

We definitely prefer to write tests in dedicated `<package-under-test>_test` packages, this means that tests should mainly explore the exported interface of the tested packages. There might be helpers and unexported details that sometimes warrant testing, in which case we use re-assignment or type aliasing in conventional `export_test.go` or `export_foo_test.go` files in the package under test, to get access to what we need to test. This is usually needed if there is algorithmic complexity or error handling behaviour that is hard to explore through the exported API, or is important to illustrate the chosen behaviour of the helper in itself.

There are varying opinions on this, but mocking is definitely a double-edged sword. Our pattern for mocking is `Mock*` functions defined in `export_test.go` returning a parameter-less restore function. These usually change some package global variable through which original values or functions are indirectly accessed and therefore can be replaced.

```
var timeNow = time.Now // close to usages in package code

func MockTimeNow(f func() time.Time) (restore func()) { // in export_test.go
     restore = testutil.Backup(&timeNow)
     timeNow = f
     return restore
}
```

If something cannot avoid being mocked across package boundaries, we sometimes have `Mock*` functions or constructors exported in the API of packages.

Because of this complexity with mocking, and because mock-heavy tests might risk needing large rewrites when refactoring (which goes against their confidence enhancement use), we are not very strict about unit tests testing exactly single functions and structs. We should do that whenever possible without mocking, but otherwise it is not atypical for snapd tests to concentrate on mocking points of interaction with the actual external system and state, as it might require less overall mocking support and it might be easier to reason on expectations for effects. For example, we have support to mock our systemd interactions and observe the involved `systemctl` invocations (`systemd.MockSystemctl`).

So, many of our unit tests might end up testing more than one package, and test instead across two levels (rarely more) of packages in our architecture; a package of lower-level primitives, for example, and a more high-level behaviour one using the former.

Full direct mocking might still make perfect sense when the API of the consumed packages is very complex but its details should be fully or largely transparent to the consumer. This is mostly the case, for example, when testing API functionality in the `daemon` package vs the API offered by the [overlord state managers](https://github.com/snapcore/snapd/blob/master/overlord/README.md).

The cost of our approach is sometimes a complex fixture setup. To help mitigate this, and in other cases when it makes sense for a package to offer test-dedicated helpers related to it, we can introduce matching `<main-package>test` packages one level deeper than `<main-package>` (e.g. `asserts/assertstest` or `overlord/devicestate/devicestatetest`).

Related to tests in and for overlord state manager packages `overlord/<concern>state`, we have a few rules:

* Ideally they should limit themselves to test the manager defined by the package
* If that's not possible they should limit themselves to as few managers as possible
* If what needs to be tested is the full interaction across many or all managers then we have or can write tests for this in `overlord/managers_test.go`. Fixture setup in these cases is very costly but they are still easier to iterate on and can be useful to probe behaviour in more internal details than functional/integration tests.

We do not have strong policies against repetition in test code, as usual the important consideration is readability. This area is mostly left to the personal judgement of developers. If any general advice can be given is that:

* Investing in clear helpers to setup complex fixtures is often valuable, while compressing actual ad hoc testing and checking code less so, as it might result in if-trees that might be hard to follow.
* Wherever applicable, tabular tests (where cases are expressed as a slice of anonymous structs) should be used. For example, they are often appropriate when testing error cases of functions.
