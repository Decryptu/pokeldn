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
