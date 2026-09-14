# Running integration tests

## Downloading spread framework

To run the integration tests locally via QEMU, you need the latest version of
the [spread](https://github.com/canonical/spread-plus) framework. For local testing
you can install the `image-garden` snap that comes with pre-built releases of
spread-plus, qemu and all the support tools. Alternatively you may install
[image-garden](https://gitlab.com/zygoon/image-garden) from source or from a
distribution package.

To install `image-garden` as a snap run `sudo snap install image-garden`. To
use the bundled copy of spread from image-garden separately run `sudo snap
alias image-garden.spread spread`. As running spread tests in snapd requires
spread-plus, additionally set `snap set image-garden spread-variant=plus`.
Up-to-date versions of image-garden snap automatically detect the right version
of spread to use, so this may not be necessary.

## Running spread

For regular development work, the integration tests will be run with a prebuilt
test variant of the snapd snap. The build happens automatically when starting
the tests using `run-spread` helper like so:

    $ ./run-spread <spread-args>

Make sure you set up snapcraft following the [snapcraft build
section](build-snapcraft.md).

The test variant of the snapd snap may be built manually by invoking a helper
script:

    $ ./tests/build-test-snapd-snap
    
The artifact will be placed under `$PWD/built-snap`.

On occasion, when working on a test and it is known that the snapd snap need not
be rebuilt, the tests may be invoked with `NO_REBUILD=1` like so:

    $ NO_REBUILD=1 ./run-spread <spread-args>

## Running spread without a cloud account

You can run most of the tests locally, using the `garden` backend. For example,
to run integration tests for Ubuntu 18.04 LTS 64-bit, invoke spread as follows:

    $ ./run-spread -v garden:ubuntu-18.04-64

> Look at the `spread.yaml` file for a list of systems that are supported by
> the garden backend.

The `garden` backend automatically downloads and initializes each base system.
During testing additional scratch space is used to hold ephemeral chances to
the disk image. This may require significant amount of space in `/tmp` so if
your system uses `tmpfs` in `/tmp` you may want look at available free space.
This especially affects the snap version of `image-garden`, as snap
packages cannot use `/var/tmp` for scratch space.

For quick reuse you can use:

    $ ./run-spread -reuse garden:ubuntu-18.04-64

It will print how to reuse the systems. Make sure to use
`export REUSE_PROJECT=1` in your environment too.
