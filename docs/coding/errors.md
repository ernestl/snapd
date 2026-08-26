# Error and error messages

* We tend not to introduce **Error* structs until we know of caller code that will need to inspect them.

* We use `fmt.Errorf` and `errors.New` as much as possible.

* Error messages start with lowercase and not end with a period, as they often end up embedded in one another

* Error messages should be formulated as *"cannot …"* whenever possible, so avoid *"failed to …"* for example.

* OTOH as error messages often end up being embedded in one another/chained. It is also important to pay attention so that the final messages do not have too much repetition, when possible, to avoid things like *"cannot …: cannot …: cannot …"* for example. Tests for the error paths can help find those repetitions.

* Error messages should be clear, and when possible, actionable. They should also use concepts and terminology familiar to the user instead of internal-only concepts unless they are really unexpected internal errors.

* Prefixing errors with *"internal error: …"* should be used for programming errors or other unexpected internal inconsistencies but preferably not for situations where external state that is not completely under snapd control is involved.
