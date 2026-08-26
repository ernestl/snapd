# Testing

We value good tests, so when you fix a bug or add a new feature we highly
encourage you to add tests.

Install the following package(s) to satisfy test dependencies.

```
sudo apt-get install python3-yamlordereddictloader dbus-x11
```

## Running unit-tests

To run the various tests that we have to ensure a high quality source just run:

    ./run-checks

This will check if the source format is consistent, that it builds, all tests
work as expected and that "go vet" has nothing to complain about.

The source format follows the `gofmt -s` formating. Please run this on your 
source files if `run-checks` complains about the format.

You can run an individual test for a sub-package by changing into that 
directory and:

```
go test -check.f $testname
```

If a test hangs, you can enable verbose mode:

```
go test -v -check.vv
```

Or, try just `-check.v` for a less verbose output.

> Some unit tests are known to fail on locales other than `C.UTF-8`. 
If you have unit tests failing, try setting `LANG=C.UTF-8` when running 
`go test`. See [issue #1960131](https://bugs.launchpad.net/snapd/+bug/1960131) for more details.

There is more to read about the testing framework on the [website](https://labix.org/gocheck)
