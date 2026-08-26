# Setting up

## Supported Ubuntu distributions

Ubuntu 18.04 LTS or later is recommended for `snapd` development.
Usually, the latest LTS would be the best choice.

> If you want to build or test on older versions of Ubuntu, additional steps
may be required when installing dependencies.

## Supported Go version

Go 1.18 (or later) is required to build `snapd`.

> If you need to build older versions of snapd, please have a look at the file
[debian/control](../../debian/control) to find out what dependencies were needed at the time
(including which version of the Go compiler).

## Getting the snapd sources

The easiest way to get the source for `snapd` is to clone the GitHub repository
in a directory where you have read-write permissions, such as your home
directory.

    cd ~/
    git clone https://github.com/snapcore/snapd.git
    cd snapd

This will allow you to build and test `snapd`. If you wish to contribute to
the `snapd` project, please see [Contributing to snapd](../../CONTRIBUTING.md).

> For more details about source-code structure of `snapd` please read about
[Managing module source](https://go.dev/doc/modules/managing-source) in Go.

## Installing the build dependencies

Build dependencies can automatically be resolved using `build-dep` on Ubuntu:

<!-- test:ubuntu-deps -->

    cd ~/snapd
    ln -sfn packaging/ubuntu-16.04 debian
    sudo apt build-dep -y .

> [!NOTE]
> The `debian` symbolic link is intentionally not part of the tree, and is explicitly listed in the .gitignore file.

Package build dependencies for other distributions can be found under the
[./packaging/](../../packaging/) directory. Eg. for Fedora use:

<!-- test:fedora-deps -->

    cd packaging/fedora
    sudo dnf install -y rpmdevtools
    sudo dnf install -y $(rpmspec -q --buildrequires snapd.spec)
    sudo dnf install -y glibc-static.i686 glibc-devel.i686

Source dependencies are automatically retrieved at build time.
Sometimes, it might be useful to pull them without building:

```
cd ~/snapd
go get ./... && ./get-deps.sh
```
