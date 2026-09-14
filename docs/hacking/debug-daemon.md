# Testing the snapd daemon

To test the `snapd` REST API daemon on a snappy system you need to
transfer it to the snappy system and then run:

    sudo systemctl stop snapd.service snapd.socket
    sudo SNAPD_DEBUG=1 SNAPD_DEBUG_HTTP=3 ./snapd

To debug interaction with the snap store, you can set `SNAPD_DEBUG_HTTP`.
It is a bitfield: dump requests: 1, dump responses: 2, dump bodies: 4.

Similarly, to debug the interaction between the `snap` command-line tool and the
snapd REST API, you can set `SNAP_CLIENT_DEBUG_HTTP`. It is also a bitfield,
with the same values and behaviour as `SNAPD_DEBUG_HTTP`.
> In case you get some security profiles errors, when trying to install or refresh a snap, 
maybe you need to replace system installed snap-seccomp with the one aligned to the snapd that 
you are testing. To do this, simply backup `/usr/lib/snapd/snap-seccomp` and overwrite it with 
the testing one. Don't forget to roll back to the original, after you finish testing.

## Testing the snap userd agent

To test the `snap userd --agent` command, you must first stop the current process, if it is
running, and then stop the dbus activation part. To do so, just run:

    systemctl --user disable snapd.session-agent.socket
    systemctl --user stop snapd.session-agent.socket

After that, it's now possible to launch the daemon with `snapd userd --agent` from a command
line.

To re-enable the dbus activation, kill that process and run:

    systemctl --user enable snapd.session-agent.socket
