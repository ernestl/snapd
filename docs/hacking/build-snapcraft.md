# Building the snap with snapcraft

The easiest (though not the most efficient) way to test changes to snapd is to
build the snapd snap using _snapcraft_ and then install that snapd snap. The
[snapcraft.yaml](../../build-aux/snap/snapcraft.yaml) for the snapd snap is located at
[./build-aux/](../../build-aux/), and
can be built using snapcraft.

Snapcraft 8.x or later is expected.

Install snapcraft:

```
sudo snap install snapcraft --classic
```

Install and init lxd:

```
sudo snap install lxd
sudo lxd init --minimal
```

Then run snapcraft:

```
snapcraft
```

Now the snapd snap that was just built can be installed with:

```
sudo snap install --dangerous snapd_*.snap
```

To go back to using snapd from the store instead of the custom version we 
installed (since it will not get updates as it was installed dangerously), you
can either use `snap revert snapd`, or you can refresh directly with 
`snap refresh snapd --stable --amend`.

## Building for other architectures with snapcraft

It is also sometimes useful to use snapcraft to build the snapd snap for
other architectures using the `remote-build` feature.

You can use remote-build with snapcraft on the snapd tree for any desired
architectures:

```
snapcraft remote-build --build-for=armhf,s390x,arm64
```

## Splicing the snapd snap into the core snap

Sometimes while developing you may need to build a version of the _core_ snap
with a custom snapd version. 
The `snapcraft.yaml` for the [core snap](https://github.com/snapcore/core/) 
currently is complex in that it assumes it is built inside Launchpad with the 
[ppa:snappy-dev/image](https://launchpad.net/~snappy-dev/+archive/ubuntu/image/) 
enabled, so it is difficult to inject a custom version of
snapd into this by rebuilding the core snap directly, so an easier way is to 
actually first build the snapd snap and inject the binaries from the snapd snap
into the core snap. This currently works since both the snapd snap and the core 
snap have the same `build-base` of Ubuntu 16.04. However, at some point in time
this trick will stop working when the snapd snap starts using a `build-base` other
than Ubuntu 16.04, but until then, you can use the following trick to more 
easily get a custom version of snapd inside a core snap.

First follow the steps above to build a full snapd snap. Then, extract the core
snap you wish to splice the custom snapd snap into:

```
sudo unsquashfs -d custom-core core_<rev>.snap
```

`sudo` is important as the core snap has special permissions on various 
directories and files that must be preserved as it is a boot base snap.

Now, extract the snapd snap, again with sudo because there are `suid` binaries
which must retain their permission bits:

```
sudo unsquashfs -d custom-snapd snapd-custom.snap
```

Now, copy the meta directory from the core snap outside to keep it and prevent
it from being lost when we replace the files from the snapd snap:

```
sudo cp ./custom-core/meta meta-core-backup
```

Then copy all the files from the snapd snap into the core snap, and delete the
meta directory so we don't use any of the meta files from the snapd snap:

```
sudo cp -r ./custom-snapd/* ./custom-core/
sudo rm -r ./custom-core/meta/
sudo cp ./meta-core-backup ./custom-core/
```

Now we can repack the core snap:

```
sudo snap pack custom-core
```

Sometimes it is helpful to modify the snap version in 
`./custom-core/meta/snap.yaml` before repacking with `snap pack` so it is easy
to identify which snap file is which.
