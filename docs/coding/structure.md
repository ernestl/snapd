# Code structure and style

## Other style points

* We rely on and apply `go fmt` consistently.
* Our PR CI static checks run [`golangci-lint`](https://github.com/golangci/golangci-lint), for details see our `.golangci-lint.yml` config.
* We tend to avoid naked returns, we run the `nakedret` test with an accepted function length of at most 5.
* `run-checks –static` runs also various linting plus some project specific checks:
  * For example, in the face of mixed usage in the end we agreed to use numbers directly instead and avoid `http.Status*` constants. This is checked by `run-checks -–static`.

## Code structuring

* Packages should have a clear responsibility, and present an exported interface with a relatively consistent level of abstraction. As an exception, there might be a few higher-level convenience functions or lower level ones. Generally if a responsibility is split across multiple packages, with the aim to produce focused and readable code, it should be split by having packages with growing application-specific levels of abstraction, instead of splitting the same level of abstraction across multiple packages. As current examples of this in the code base, consider (in higher-level to lower-level abstraction level):
  * overlord/snapstate -> overlord/snapstate/backend -> boot -> bootloader
  * overlord/snapstate -> overlord/snapstate/backend -> wrappers -> systemd
  * overlord/servicestate -> wrappers -> systemd

* Symmetry should always be applied to structure code when it is useful. Code is easier to reason about and to review if do and undo code paths, save and restore paths, etc. are written in obvious structurally symmetric ways when possible. Managers' tasks being defined with do and undo handlers tries to guide and facilitate this for example.

* When trying to keep functions and methods readable by introducing helpers, trying to aim for a mostly consistent level of abstraction inside each function could be useful.

* *Do not repeat yourself* is a balancing act. Complex behaviour should ideally be encoded only once in the code base when possible. When extracting and deciding how to extract some behaviour it is important to consider the readability of both the now encapsulated code and its consumers. For example, if it's hard to give the extracted code a good name and signature it might show that a different approach should be looked at. For simpler helpers, it might be worth seeing a couple of usages before creating them as local helpers, and a bit more before creating an exported helper that can be imported from all the used places. When creating helpers and avoiding repetition the aim should also be first to improve maintainability and readability. If the consumer code is less readable then maybe the extraction in this case might not be a good idea in the end.

* See [Tests](tests.md) for consideration about repetition and reuse specifically in test code.

* Given that golang does not support mutual/circular imports we have a few patterns and rules:
  * Across overlord state managers' packages:
    * `snapstate` can and is imported by other managers but cannot import them directly
    * `assertstate` and `hookstate` should also be mostly consumed and not consume other managers
  * When unavoidable, we break circular import issues by using exported function hook variables from the normally imported package. These are assigned to in the package that normally imports and uses the first one, either directly or indirectly.
  * These variables need to be assigned in `init` code or `Manager` constructor functions.
    * Examples are:
      * `snapstate.ValidateRefreshes` assigned from a `assertstate.delayedCrossMgrInit` called by `assertsstate.Manager`
      * The hooks in `snapstate` assigned from a `hookstate init`
      * `boot.HasFDESetupHook` assigned from `devicestate.Manager`
  * When applicable, we might also use hook registration mechanisms. Examples:
    * `snapstate.AddCheckSnapCallback`
    * `snapstate.RegisterAffectedSnapsByAttr`
  * `*util` packages should not import not `*util` packages, and whenever possible just use standard library packages and as few as strictly necessary other `*util` packages

* Most packages can be imported as needed by any snapd tool and service with the exception of most code under overlord and the state managers' packages. This code is meant to implement only the snapd daemon itself and not be imported by any other tool, as it will also grow the size of the latter significantly. (As an exception, a subset of `overlord/configstate/configcore` is consumed and built into tools outside of the snapd daemon. This subset is kept under control via the `nomanagers` build tag).

## System properties

* snapd should complete initiated operations even in the case of snapd restarts or system reboots. In the case of failure, it should try to bring back the system to a known good state.
* snapd should avoid or minimise cases and time windows where the external state of the system can cause unexpected errors for users and the rest of the system.
