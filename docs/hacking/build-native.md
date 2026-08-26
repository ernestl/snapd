# Building natively

The `snap` command line client and `snapd` are the exact same binary, with
different entrypoints that are selected by inspecting the value of `argv[0]`. To
build it:

<!-- test:build-snapd -->
```
cd ~/snapd
mkdir -p /tmp/build
go build -o /tmp/build/snapd ./cmd/snapd
```

At this point you can invoke the `snap` functionality by creating a symbolic
link named `snap`:

<!-- test:build-snap -->
```
ln -s -r /tmp/build/snapd /tmp/build/snap
```

or setting `argv[0]` explicitly when running the binary:

```
/bin/bash -c 'exec -a snap /tmp/build/snapd'
```

To build all the `snapd` Go components:

<!-- test:build-go -->
```
cd ~/snapd
mkdir -p /tmp/build
go build -o /tmp/build ./...
```
