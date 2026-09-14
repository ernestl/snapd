# Quick intro to hacking on snap-confine

Hey, welcome to the nice, low-level world of snap-confine

## Building the code locally

To get started from a pristine tree you want to do this:

<!-- test:build-c -->
```bash
cd ~/snapd
# overriding the version to 1337, or leave empty to let the script figure
# the version out automatically (on Ubuntu/Debian)
./mkversion.sh 1337
cd cmd/
./autogen.sh
make
```

This will drop makefiles and let you build stuff. You may find the `make hack`
target, available in [./cmd/](../../cmd/) handy `(cd cmd; make hack)`. It installs the locally built
version on your system and reloads the [AppArmor](https://apparmor.net/) profile.

>The `autogen.sh` script automatically detects your distribution (from `/etc/os-release`)
and applies the appropriate configure options. On Ubuntu it uses `--enable-nvidia-multiarch`
with the host architecture triplet, while on Fedora it uses `--enable-nvidia-biarch` with
SELinux support. The script also handles running `autoreconf -i -f` and calling `mkversion.sh`
if needed.
>
>If you need manual control over configure options, you can run `autoreconf -i -f` followed
by `./configure` with your desired flags. See `./configure --help` for available options.

## Testing your changes locally 

After building the code locally as explained in the previous section, you can run the 
test suite available for snap-confine (among other low-level tools) by running the 
`make check` target available in [./cmd](../../cmd/).

## Submitting patches

Please run `(cd cmd; make fmt)` before sending your patches for the "C" part of
the source code.
