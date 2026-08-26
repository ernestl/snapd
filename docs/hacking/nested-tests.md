# Running nested tests

Nested tests are used to validate features that cannot be tested with the regular tests.

The nested test suites work differently from the other test suites in snapd. In
this case each test runs in a new image which is created following the rules
defined for the test.

The nested tests are executed using the [spread framework](spread.md#downloading-spread-framework). 
See the following examples using the QEMU and Google backends.

- _QEMU_: `spread qemu-nested:ubuntu-20.04-64:tests/nested/core20/tpm`  
- _Google_: `spread google-nested:ubuntu-20.04-64:tests/nested/core20/tpm`  

The nested system in all the cases is selected based on the host system. The following lines 
show the relation between host and nested `systemd` (same applies to the classic nested tests):

- ubuntu-16.04-64 => ubuntu-core-16-64
- ubuntu-18.04-64 => ubuntu-core-18-64
- ubuntu-20.04-64 => ubuntu-core-20-64

The tools used for creating and hosting the nested VMs are:

- _ubuntu-image snap_ is used to build the images
- _QEMU_ is used for the virtualization (with [_KVM_](https://www.linux-kvm.org/page/Main_Page) acceleration)

Nested test suite is composed by the following 4 suites:

- _classic_: the nested suite contains an image of a classic system downloaded from cloud-images.ubuntu.com 
- _core_: it tests a core nested system, and the images are generated with _ubuntu-image snap_
- _core20_: this is similar to the _core_ suite, but these tests are focused on UC20
- _manual_: tests on this suite create a non generic image with specific conditions

The nested suites use some environment variables to configure the suite 
and the tests inside it. The most important ones are described below:

- `NESTED_WORK_DIR`: path to the directory where all the nested assets and images are stored
- `NESTED_TYPE`: use core for Ubuntu Core nested systems or classic instead.
- `NESTED_CORE_CHANNEL`: the images are created using _ubuntu-image snap_, use it to define the default branch
- `NESTED_CORE_REFRESH_CHANNEL`: the images can be refreshed to a specific channel; use it to specify the channel
- `NESTED_USE_CLOUD_INIT`: use cloud init to make initial system configuration instead of user assertion
- `NESTED_ENABLE_KVM`: enable KVM in the QEMU command line
- `NESTED_ENABLE_TPM`: re-boot in the nested VM in case it is supported (just supported on UC20)
- `NESTED_ENABLE_SECURE_BOOT`: enable secure boot in the nested VM in case it is supported (supported just on UC20)
- `NESTED_BUILD_SNAPD_FROM_CURRENT`: build and use either core or `snapd` from the current branch
- `NESTED_CUSTOM_IMAGE_URL`: download and use an custom image from this URL
- `NESTED_SNAPD_DEBUG_TO_SERIAL`:  add snapd debug and log to nested vm serial console
- `NESTED_EXTRA_CMDLINE`:  add any extra cmd line parameter to the nested vm
