# Developing interfaces

Interfaces define how snaps access system resources and interact with each
other. Each interface consists of plugs (consumers) and slots (providers).

Full policy evaluation: `interfaces/builtin/README.md`.

## Structure

Every interface must:

- Be registered via `registerIface()` in its `init()` function
- Implement the `Interface` interface (at minimum `Name()` and `AutoConnect()`)
- Live in `interfaces/builtin/`

```go
type myInterface struct {
    commonInterface
}

func (iface *myInterface) Name() string {
    return "my-interface"
}

func init() {
    registerIface(&myInterface{commonInterface{
        name:                 "my-interface",
        summary:              "allows access to X",
        implicitOnCore:       true,
        baseDeclarationPlugs: myBaseDeclarationPlugs,
        baseDeclarationSlots: myBaseDeclarationSlots,
    }})
}
```

## Security backends

- `AppArmorConnectedPlug/Slot`: AppArmor rules when connected
- `AppArmorPermanentPlug/Slot`: AppArmor rules always present
- `SecCompConnectedPlug/Slot`: seccomp filters when connected
- `UDevConnectedPlug/Slot`: udev rules for device access
- `KModConnectedPlug/Slot`: kernel modules to load

```go
func (iface *myInterface) AppArmorConnectedPlug(spec *apparmor.Specification,
    plug *interfaces.ConnectedPlug, slot *interfaces.ConnectedSlot) error {
    spec.AddSnippet("/dev/my-device rw,")
    return nil
}
```

Profiles are additive: each connected interface adds to AppArmor/seccomp.

## Base declaration

```go
const myBaseDeclarationPlugs = `
  my-interface:
    allow-installation: false  # Super-privileged, needs snap-declaration
    deny-auto-connection: true # Manual connection required
`
```

Policy evaluation order (first match wins):

1. `deny-*` in plug snap-declaration
2. `allow-*` in plug snap-declaration
3. `deny-*` in slot snap-declaration
4. `allow-*` in slot snap-declaration
5. `deny-*` in plug base-declaration
6. `allow-*` in plug base-declaration
7. `deny-*` in slot base-declaration
8. `allow-*` in slot base-declaration

## Sanitizers

```go
func (iface *myInterface) BeforePreparePlug(plug *snap.PlugInfo) error {
    path, ok := plug.Attrs["path"].(string)
    if !ok || path == "" {
        return fmt.Errorf("my-interface must contain path attribute")
    }
    return nil
}
```

## Tests

- Test both plug and slot sides
- Test connection scenarios
- Test AppArmor/seccomp snippet generation
- Verify base declaration policy evaluation
- Use `ifacetest.BackendSuite` for backend tests

## Key files

- `interfaces/builtin/README.md`: complete policy evaluation guide
- `interfaces/core.go`: core types and sanitizer interfaces
- `interfaces/builtin/common.go`: `commonInterface`
- `interfaces/repo.go`: connection repository
