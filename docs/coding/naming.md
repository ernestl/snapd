# Naming, comments, and signatures

## Naming conventions

To a large extent we follow [golang naming conventions](https://go.dev/doc/effective_go#names):

* Names should strike a balance between concision and clarity, where for a local variable more weight might be put on concision while for an exported name clarity might have a larger weight.

* Consistency is important in a somewhat large and long lived project, it is always a good idea to check whether there are similar entities or concepts in the code from which to borrow terminology or naming patterns, especially in the neighbourhood of the new code. For example when using a verb in a method name, it is good to check whether the verb is used for similar behaviour in other names or some other verb is more common for the usage.

* Regarding concision, golang is a typed language so a slightly more concise name might still work because purpose is clarified by the parameter types of the to-be-named function or the type of the to-be-named field.

* One should remember that unexported symbols are scoped to a whole package, not their code file, so they should be named accordingly. Even for unexported helpers and symbols clarity is important - prefer something specific in their name over very generic names: `func findRev(needle snap.Revision, haystack []snap.Revision) bool` vs `find` or `findStuff`.

## Comments

Ideally all exported names should have doc comments for them following [golang conventions](https://go.dev/doc/comment).

We sometimes also use long code comments or separate markdown README files for higher-level descriptions of mechanisms or concepts.

Inline code comments should usually address non-obvious or unexpected parts of the code. Repeating what the code does is not usually very informative:

* Code comments should either address the why something is done
* Or clarify the more abstract impact of the low-level manipulation in the code

It might be appropriate and useful also to give proper doc comments even to complex unexported helpers.

## Function signatures

Example: in `overlord/snapstate`

```
Install(ctx context.Context, st *state.State, name string, opts *RevisionOptions, userID int, flags Flags) (*state.TaskSet, error)
```

* We try to follow this kind of ordering for parameters of functions and methods:
  * `context.Context` if provided
  * Long lived/ambient objects like `state.State`
  * The main entities the function or method operates on
  * Any optional and ancillary parameters in some order of relevance
* For return parameters, they should be in some order of importance with error last as per golang conventions.
* Consistency is important, so parallel/similar functions/methods should try to have the same/any shared parameters in the same order.
* For exported functions, generally try to avoid asking callers to pass values that can be computed by the called methods/functions anyway. Sometimes some optimisation pattern might make this worthwhile but consider if that is really the case. Even then things should always be organised in ways that avoid breaking/confusing responsibility boundaries.
