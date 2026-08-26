# Building with cross-compilation (_example: ARM v7 target_)

Install a suitable cross-compiler for the target architecture.

```
sudo apt-get install gcc-arm-linux-gnueabihf
```

Verify the default architecture version of your GCC cross-compiler.

```
arm-linux-gnueabihf-gcc -v
:
--with-arch=armv7-a
--with-fpu=vfpv3-d16
--with-float=hard
--with-mode=thumb
```

Verify the supported Go cross-compile ARM targets [here](
https://github.com/golang/go/wiki/GoArm).

`Snapd` depends on [libseccomp](https://github.com/seccomp/libseccomp#readme) 
v2.3 or later. The following instructions can be
used to cross-compile the library:

```
cd ~/
git clone https://github.com/seccomp/libseccomp
cd libseccomp
./autogen.sh
./configure --host=arm-linux-gnueabihf --prefix=${HOME}/libseccomp/build
make && make install
```

Setup the Go environment for cross-compiling.

```sh
export CC=arm-linux-gnueabihf-gcc
export CGO_ENABLED=1
export CGO_LDFLAGS="-L${HOME}/libseccomp/build/lib"
export GOOS=linux
export GOARCH=arm
export GOARM=7
```

The Go environment variables are now explicitly set to target the ARM v7
architecture.

Run the same build commands from the [Building natively](build-native.md) section.

Verify the target architecture by looking at the application ELF header.

```
readelf -h /tmp/build/snapd
:
Class:                             ELF32
OS/ABI:                            UNIX - System V
Machine:                           ARM
```

CGO produced ELF binaries contain additional architecture attributes that
reflect the exact ARM architecture we targeted.

```
readelf -A /tmp/build/snap-seccomp
:
File Attributes
  Tag_CPU_name: "7-A"
  Tag_CPU_arch: v7
  Tag_FP_arch: VFPv3-D16
```
