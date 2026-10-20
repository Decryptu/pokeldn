# Android app

The Android app runs the desktop app's own interface on a phone, with an ESP32-S3, C3 or C6 radio
board on its native USB port, or a classic ESP32 on a CP210x bridge (`10c4:ea60`), on the phone's USB
port. Every page, game and tool is the code in `gui/` and `pokeldn/`; only the shell in this folder is Android's. A OnePlus CPH2621 running Android 16 completed a
smooth retail FireRed trade with a XIAO ESP32C6 through the earlier diagnostic frontend
(`MainActivity`, below). The full app on the same phone and board completes FireRed host trades at the
diagnostic frontend's speed. It had been slow (a median 36 link slots per second against 51, and as
low as 9): the session log auto-scrolls, each scroll event reached `theme.fade`'s handler, and Flet's
automatic update after the handler re-diffed the whole page (72 to 85 ms, up to 350 times a run) on the
interpreter the run shares. The handler now turns that automatic update off.

`UsbStream.java` drives the CP210x with its vendor requests (UART enable, 8N1, baud rate, DTR and RTS)
and the same bulk reader and writer as native USB. A classic ESP32 on a CP210x completed retail
FireRed/LeafGreen trades on a contributor's phone through an earlier version that used the
usb-serial-for-android library. CH34x and FTDI bridges are not driven.

`touch files/data/ui_trace.on` (with `adb shell run-as org.pokeldn.usbprobe`) makes the app write
`files/data/ui_trace.txt` (`pokeldn.app.sampler.trace_updates`): every Flet patch by control type and
calling `gui` function, page property changes and browser events, every 10 s. Never sample other
threads' frames under Chaquopy: dropping a frame there freed a Java object on an unattached thread and
the app aborted (JNI DeleteRef, JNIEnv from another thread), even after attaching the thread.

## How it works

| piece | what it does |
|---|---|
| `PokeldnActivity` | starts the embedded Python (Chaquopy), which serves `gui/main.py` as Flet's web app on 127.0.0.1:8550, and shows it in a full-screen WebView |
| `src/python/android_gui.py` | sets the environment, installs the Android pieces below, applies the run tuning (Scheduling) and starts the interface |
| `pokeldn/app/android.py` | the board as a pyserial port, `android://board`: `serial.Serial`, `serial_for_url` and the port list all reach `UsbStream.java`, so the Board page, the launchers and esptool run unchanged; Android's file pickers in place of Flet's |
| `pokeldn/app/runner.py` `InProcess` | runs a launcher on the app's own interpreter, since Android starts no second Python; it holds stdout, argv, the environment and the working directory while it runs |
| `Bridge.java` | USB state, the USB access prompt, Settings, the file pickers and the foreground service, called from Python |
| `RunService.java` | a connected-device foreground service while a run holds the board |
| `src/python/fastapi/` | the part of FastAPI that Flet's web server uses, on starlette: pydantic-core has no Android build |
| `build_native.py` | PKHeX (`services/pkhex`) compiled ahead of time for linux-bionic-arm64, and an ARM-only Unicorn; both ship as native libraries |

Below 760 points wide the interface shows a bottom tab bar and one panel at a time
([Phones](../../docs/gui.md#phones)). The guided USB setup is the Board page on Android
([Android setup requirements](../../docs/gui.md#android-setup-requirements)).

### WebView

Android WebView sets its text zoom to the system font size. With text zoom above 100%, Flutter's web
engine draws every text so large that it is clipped away: the screens show icons and empty panels,
and dialogs and the tab bar stretch to the full height (measured at font scale 1.3 and 2.0 on the
emulator, and reported from Galaxy phones). `PokeldnActivity` sets text zoom to 100%.

The interface needs Android System WebView 119 or later with WebGL. Flutter's web engine draws with
skwasm only when WebAssembly GC (Chrome 119) and WebGL are present, and otherwise falls back to
CanvasKit, which draws this interface's text but none of its images. Before loading the interface,
`PokeldnActivity` probes both in a blank page, logs `WebView <package> <version>, WasmGC, WebGL` under
the `PokeLDN` tag, and on a failure shows a native screen with a Play Store link to the WebView
package and a "Continue anyway" button. If the page's loading spinner, which Flutter removes at its
first frame, is still present after 60 s, the same screen offers the update or "Keep waiting".
`adb shell am start -n org.pokeldn.usbprobe/.PokeldnActivity --ez oldwebview true` shows the screen
on any phone.

## Build

Needs JDK 21, Android SDK 36 with build tools 36.1.0 and an NDK, Gradle 8.13 to 9.5 (AGP 8.13 fails
on 9.6 and later), the .NET 10 SDK, CMake and the repository's `.venv` (Python 3.13). Unicorn's
source comes from `scripts/build_unicorn.py`; run it once.

```sh
./.venv/bin/python examples/android/build.py --install DEVICE
```

`build.py` builds the local wheels into `wheels/` (sdists the Android build cannot compile, and
msgpack without its C extension), the native helpers into `jniLibs/` when they are missing
(`--native` rebuilds them), the staged sources into `staged/` (`stage.py`: tracked and untracked
sources, the firmware images and Unicorn's binding), then the APK. `GRADLE` names a Gradle when the
newest wrapper download is not the one to use. `--release` builds the release APK, signed with the
local debug key; `POKELDN_ANDROID_KEYSTORE` selects an existing one, which an update needs to keep
the app's private files.

### Releases

A `v*` tag's release workflow builds `pokeldn-android-arm64.apk` with `--release`, numbered by the
run so each installs as an update, and signs it with the release key in the `ANDROID_RELEASE_*`
secrets when they are set (`POKELDN_ANDROID_RELEASE_KEYSTORE` and `POKELDN_ANDROID_RELEASE_PASSWORD`
locally). `scripts/android_release_key.py` makes the key in `~/.config/pokeldn/` once and stores
the secrets. An APK signed with another key does not install over it: a phone holding one
uninstalls it first.

The APK carries no keys or Pokemon. The player picks `prod.keys` on the welcome screen or in
Settings; Android's picker copies it into the app's private files.

## Self-test

```sh
adb shell am start -n org.pokeldn.usbprobe/.PokeldnActivity --ez selftest true
adb logcat -s PokeLDN
```

About 15 s after start it logs one `selftest PASS` or `selftest FAIL` line per check: every module
a run imports, PKHeX listing species, Unicorn running ARM code, the simulated-board tests of
`tests/test_esp32.py` and `tests/test_host_end_to_end.py` (53 of 56; three read desktop tools the
app does not ship), each catalog tool reading its launcher's flags, a launcher run in-process
(`bin/swsh_gift_host.py --dump`), and the screen and service hold turning on and off. No board is
needed; the arm64 emulator passes all 26.

The foreground service starts only while the app holds USB access to the board: Android 14 refuses
a connected-device service without it and then stops the app.

## The diagnostic frontend

`MainActivity` is the first prototype: a FireRed host trade with inputs that `provision.py` copies
over ADB. It is reachable from ADB only:

```sh
python examples/android/provision.py --device PHONE_IP:PORT --keys /path/to/prod.keys --offer /path/to/offer.pk3
adb shell am start -f 0x20000000 -n org.pokeldn.usbprobe/.MainActivity --es mode trade
```

## Scheduling and validation

The protocol coroutine runs on the same Trio thread as LDN. Before creating radio and network
threads, the worker selects the allowed CPU with highest sysfs `cpu_capacity` and restricts its
CPU affinity to that core. The worker restores its original affinity during cleanup. On the
SM6375 test phone this selected core 6. The tested configuration uses synchronous USB writes,
a 1 ms Python thread-switch interval and `ctypes.PyDLL` for the tiny native crypto calls.

The initial host ran about 10 parent slots/s with slow movement and an extended animation wait.
The shared Trio loop alone improved scheduling but remained slow. With affinity, the player
reported smooth movement and a completed trade; the capture measured 51.1 unique parent UNI
slots/s. Every console block fragment was echoed, and the received PK3 passed desktop PKHeX.
These observations cover this phone and board; other devices need measurement.

```sh
python examples/android/check_shared_loop.py
```

This desktop check verifies protocol ticks run on the network's Trio thread, room-close grace
continues after departure and cleanup stops the worker. The Activity's Test Python button runs
imports, AES known-answer and Trio checks, existing simulated fragmented LDN and two-trade loss/
duplicate/reordering tests, 100 real HELLOs, receive BENCH and a 5000-command output count check.

## Diagnostics

Logs use `PokeLDNPython`, `python.stderr` and `AndroidRuntime`. The host aggregates numeric call
counts, elapsed time and calling-thread CPU time every five seconds into `timing.jsonl` and
`HOST_TIMING`. `async_wait.cpu_ms` includes LDN tasks running on the same thread while the
protocol coroutine waits.

Activity intent modes `profile`, `uplink` and `replay` select developer diagnostics. Profile
measures packet processing with idle or receiving USB traffic. Uplink compares original and
performance-core CPU placement, with optional Java write batching, while the radio is idle;
each case checks board command counts and wire checksums. Replay runs the most recent private
host capture through the full peer/session with a virtual protocol clock. All diagnostics
require a connected board; replay requires an existing capture and private keys.

While a trade worker is active, `--es experiment stop` requests cleanup, `memory_trace` retains
trace records in memory until cleanup, and `switch_us_N` changes the thread-switch interval.
Use these with `am start -f 0x20000000` as above. Force-stopping a memory-trace run loses that
portion of its capture. Java queued writes remain disabled in the validated live configuration.

A private `files/trade/enable_profile` marker enables a short connected cProfile recording.
Live cProfile results in this embedded runtime interleaved threads and produced unreliable
caller relationships. A cross-thread `sys._current_frames` sampler triggered a JNI reference
error and was removed. Debug APKs enable CheckJNI; release APKs omit that extra checking.
`run-as` requires a debuggable APK, so stop the release worker before temporarily updating to
debug to retrieve private outputs, then restore the tested release. Wi-Fi APK installation can
progress silently for several minutes.
