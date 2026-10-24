"""Registration only: importing the plugin must not start a search or contact a console."""
from pokeldn.plugins import Field, Tool


BUILDS = tuple((c, c) for c in ("BPRE", "BPGE", "BPRF", "BPGF"))
ENCOUNTERS = (("scripted", "Scripted / uncalibrated"), ("mewtwo", "Mewtwo / uncalibrated"),
              ("articuno", "Articuno / uncalibrated"), ("zapdos", "Zapdos / uncalibrated"),
              ("moltres", "Moltres / uncalibrated"), ("snorlax", "Snorlax / uncalibrated"))


def register(api):
    common = (
        Field("--build", "Cartridge", "choice", default="BPRE", choices=BUILDS),
        Field("--encounter", "Encounter label", "choice", default="scripted", choices=ENCOUNTERS,
              help="Record label only; a named encounter is not a verified timing profile."),
    )
    api.add_tool("frlg", Tool(
        "frlg-rng-assist-search", "RNG Assist: offline search", "search.py",
        "Predict natural RNG targets from a supplied seed. This is not live console telemetry.",
        ("Enter a measured seed and the game's actual TID/SID.",
         "Search in RNG advances; the result is a prediction, not a console input schedule."),
        fields=(*common,
                Field("--seed", "Current seed", required=True, help="Eight hex digits; optional 0x prefix."),
                Field("--tid", "Game TID", "number", required=True),
                Field("--sid", "Game SID", "number", required=True),
                Field("--method", "Model", "choice", default="1",
                      choices=(("1", "Method 1"), ("2", "Method 2"), ("4", "Method 4"))),
                Field("--start", "Start advance", "number", default="0"),
                Field("--advances", "Candidates", "number", default="100000"),
                Field("--max-results", "Maximum targets", "number", default="10"),
                Field("--any-shininess", "Allow non-shiny targets", "switch", default=False),
                Field("--nature", "Nature", help="Optional English name or index 0..24."),
                Field("--pid", "Exact PID filter", help="Optional hex PID to find, never written to the game."),
                Field("--iv-min", "Minimum IVs", default="0,0,0,0,0,0",
                      help="HP, Attack, Defense, Sp. Atk, Sp. Def, Speed (display order)."),
                Field("--iv-max", "Maximum IVs", default="31,31,31,31,31,31",
                      help="Optional upper bounds in HP, Attack, Defense, Sp. Atk, Sp. Def, Speed order."),
                Field("--offset", "Measured offset (advances)", "number",
                      help="Optional HIT-to-pre-PID offset; omitted means no trigger prediction.")),
    ))
    live_common = (
        Field("--build", "Cartridge", "choice", default="BPRE", choices=BUILDS),
        Field("--radio", "Radio override", help="Optional, for example esp32:COM8; normally use Board."),
        Field("--keys", "prod.keys path", help="Optional; normally supplied by the PokeLDN host."),
        Field("--output", "Capture/report path", help="Optional; defaults to the FRLG RNG Assist library."),
    )
    api.add_tool("frlg", Tool(
        "frlg-rng-assist-trace", "RNG Assist: trace seed", "trace.py",
        "Read gRngValue samples from the live cartridge; the default mode is read-only and the optional ROM call can verify LCG continuity.",
        ("Start this before using the result as a seed; default mode writes no console memory or save.",
         "On the console choose Mystery Gift -> Wonder Cards -> Friend when the host asks."),
        fields=(*live_common,
                Field("--samples", "Frames", "number", default="60"),
                Field("--trace-call", "Optional ROM call", help="Advanced hexadecimal THUMB address; default 0.")),
    ))
    api.add_tool("frlg", Tool(
        "frlg-rng-assist-state", "RNG Assist: read state", "state.py",
        "Read and decode the resident tracker state; this is a read-only memory dump.",
        ("Install the observer first; a soft reset clears its state.",
         "The state includes current seed/index, hit flags and the recorded target."),
        fields=(*live_common,
                Field("--state-address", "State address", help="Default 0x0203FF80.")),
    ))
    api.add_tool("frlg", Tool(
        "frlg-rng-assist-install", "RNG Assist: install observer", "install.py",
        "Install the read-only resident tracker until the next soft reset; Auto-A is off by default.",
        ("This replaces the VBlank handler in volatile RAM and never writes the save.",
         "Use the separate arm tool only after a live state and calibrated offset are confirmed."),
        fields=(*live_common,
                Field("--state-address", "State address", help="Default 0x0203FF80."),
                Field("--trigger-index", "Trigger index", "number", default="0"),
                Field("--offset", "Trigger offset", "number", default="0"),
                Field("--target-pid", "Target PID", default="0"),
                Field("--target-nature", "Target nature", "number", default="0"),
                Field("--mode", "Mode", default="0"),
                Field("--enable-auto-a", "Enable one-shot A", "switch", default=False)),
    ))
    api.add_tool("frlg", Tool(
        "frlg-rng-assist-arm", "RNG Assist: configure one-shot A", "arm.py",
        "Write the resident trigger parameters in volatile RAM; no save write is performed.",
        ("The runtime does not search for a target on the console; supply a measured trigger index and offset.",
         "Enable the switch only when the target and timing came from the same live session."),
        fields=(*live_common,
                Field("--trigger-index", "Trigger index", "number", default="0"),
                Field("--state-address", "State address", help="Must match install observer; default 0x0203FF80."),
                Field("--offset", "Trigger offset", "number", default="0"),
                Field("--target-pid", "Target PID", default="0"),
                Field("--target-nature", "Target nature", "number", default="0"),
                Field("--mode", "Mode", default="0"),
                Field("--enable-auto-a", "Enable one-shot A", "switch", default=False)),
    ))
    api.add_tool("frlg", Tool(
        "frlg-rng-assist-calibrate", "RNG Assist: calibration", "calibrate.py",
        "Recover candidate pre-PID states and record bounded HIT-to-generation distances.",
        ("Enter one measured HIT seed, the resulting PID and the six actual IVs.",
         "One record does not validate an encounter profile or enable Auto-A."),
        fields=(*common,
                Field("--hit-seed", "HIT seed", required=True),
                Field("--pid", "Actual PID", required=True),
                Field("--ivs", "Actual IVs", required=True,
                      help="HP, Attack, Defense, Sp. Atk, Sp. Def, Speed."),
                Field("--hit-boundary", "HIT sampling boundary", "choice", default="unspecified",
                      choices=(("unspecified", "Unspecified / manual"),
                               ("post-vblank", "Verified reading after original VBlank"))),
                Field("--max-offset", "Maximum plausible advances", "number", default="4096")),
    ))
