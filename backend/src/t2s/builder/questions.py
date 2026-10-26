"""The adaptive mission questionnaire of the CubeSat Builder.

Each Question says when it applies (`when`, on the requirements set so far), what it sets (`key`), how to read the
answer (`kind`, options, unit and range), and what to assume when the user answers "I don't know" (`default`, with
`default_why` in plain English). The engine asks the first applicable question that has no answer (`pending`), so the
questions adapt: imaging questions only for Earth observation, the local time only for a sun-synchronous orbit, and so
on. Changing an answer re-applies every other answer: requirements of questions that no longer apply are dropped (their
answers are kept, so switching back restores them).

Defaults are design choices (ASSUMED), never measurements; where a default quotes a fact, it names its source.
Advanced questions (expert mode) refine values that otherwise take their defaults.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from . import regions
from .model import now_iso, req, touch

UNKNOWN = "__unknown__"


@dataclass(frozen=True)
class Option:
    value: object
    label: str
    explain: str = ""


@dataclass(frozen=True)
class Question:
    id: str
    section: str
    prompt: str
    help: str
    kind: str                                     # choice | multi | number | bool | region | station | text
    key: str
    options: tuple = ()
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    when: Callable[[dict], bool] = field(default=lambda r: True)
    default: object = None                        # a value, or callable(requirements) -> value
    default_why: object = ""                      # a text, or callable(requirements) -> text
    advanced: bool = False

    def default_value(self, r: dict):
        return self.default(r) if callable(self.default) else self.default

    def default_reason(self, r: dict) -> str:
        return self.default_why(r) if callable(self.default_why) else self.default_why


def _v(r: dict, key: str, default=None):
    x = r.get(key)
    return default if x is None else x["value"]


def _is(key: str, *values) -> Callable[[dict], bool]:
    return lambda r: _v(r, key) in values


def _all(*preds) -> Callable[[dict], bool]:
    return lambda r: all(p(r) for p in preds)


EO = _is("mission.type", "earth_observation")
COMMS = _is("mission.type", "communications")
SCIENCE = _is("mission.type", "science")
ASTRO = _is("mission.type", "astronomy")
DEMO = _is("mission.type", "tech_demo")
CUSTOM_PAYLOAD = _is("mission.type", "science", "astronomy", "tech_demo", "other")

# defaults of the imaging questions follow what is being imaged (design choices, ASSUMED)
_GSD_BY_SUBJECT = {"urban": 3.0, "land": 10.0, "fire": 30.0, "water": 30.0, "night": 100.0, "weather": 250.0}
_BANDS_BY_SUBJECT = {"land": ["rgb", "nir"], "urban": ["pan", "rgb"], "fire": ["rgb", "nir", "swir"],
                     "water": ["rgb", "nir"], "weather": ["rgb", "tir"], "night": ["pan"]}


def _subjects(r: dict) -> list:
    return list(_v(r, "imaging.subject") or ["land"])


def _gsd_default(r: dict) -> float:
    return min(_GSD_BY_SUBJECT.get(s, 10.0) for s in _subjects(r))


def _bands_default(r: dict) -> list:
    out: list = []
    for s in _subjects(r):
        for b in _BANDS_BY_SUBJECT.get(s, ["rgb"]):
            if b not in out:
                out.append(b)
    return out


def _orbit_needs_altitude(r: dict) -> bool:
    return _v(r, "orbit.choice") in ("sso", "custom")


QUESTIONS: tuple[Question, ...] = (
    # ------------------------------------------------------------------------------------------------- mission
    Question(
        "mission.type", "mission", "What is the primary purpose of the satellite?",
        "Everything else follows from this: the payload, the orbit, how precisely the satellite must point, how much "
        "data it makes and how big it has to be.",
        "choice", "mission.type",
        options=(Option("earth_observation", "Earth observation", "Take pictures or measurements of the Earth."),
                 Option("communications", "Communications", "Relay or collect radio messages and signals."),
                 Option("science", "Science", "Measure something in space: radiation, magnetic fields, the upper "
                                                "atmosphere…"),
                 Option("astronomy", "Astronomy", "Look away from the Earth at stars and other objects."),
                 Option("tech_demo", "Technology demonstration", "Test new hardware in orbit."),
                 Option("other", "Something else", "Describe your own payload's size, power and data.")),
        default="tech_demo",
        default_why="A technology demonstration is the simplest mission to start from; you can change it any time."),
    Question(
        "mission.fidelity", "mission", "How far do you want to take this design?",
        "This sets how the results are labelled. The Builder never claims a satellite is flight-ready: a flight design "
        "still needs detailed verification, environmental testing, licensing and engineering review.",
        "choice", "mission.fidelity",
        options=(Option("conceptual", "Concept / learning", "Early feasibility with approximate sizing."),
                 Option("preliminary", "Preliminary engineering", "Traceable calculations and real components."),
                 Option("flight", "Intended for flight", "Shows what still has to be verified before flight.")),
        default="conceptual", default_why="Concept level is the honest starting point for any new design."),
    Question(
        "mission.lifetime_years", "mission", "How long should the mission last?",
        "A longer mission needs a higher orbit (less drag), more battery charge cycles and more radiation tolerance.",
        "number", "mission.lifetime_years", unit="years", min=0.1, max=15.0,
        default=2.0, default_why="Two years is taken as a starting point (ASSUMED); the analysis shows what the orbit "
                                 "and the hardware allow."),
    Question(
        "mission.budget_usd", "mission", "What is the hardware budget?",
        "The budget steers which components are recommended. Prices are shown only where manufacturers publish them; "
        "the rest are marked 'quote required'.",
        "choice", "mission.budget_usd",
        options=(Option(100_000, "Under $100,000"), Option(500_000, "Up to $500,000"),
                 Option(2_000_000, "Up to $2 million"), Option(None, "Not decided — show the costs")),
        default=None, default_why="Without a limit the Builder ranks components on performance and shows their costs."),
    # ------------------------------------------------------------------------------------------------- payload: EO
    Question(
        "imaging.subject", "payload", "What do you want to photograph?",
        "The subject sets the default resolution and the colour bands.",
        "multi", "imaging.subject", when=EO,
        options=(Option("land", "Land and agriculture", "Fields, forests, land use."),
                 Option("urban", "Cities and infrastructure", "Buildings, roads, construction."),
                 Option("fire", "Wildfires and disasters", "Fire fronts, burn scars, floods."),
                 Option("water", "Coasts, lakes and ocean", "Shorelines, water colour."),
                 Option("weather", "Clouds and weather", "Large-scale cloud patterns."),
                 Option("night", "Lights at night", "City lights after dark.")),
        default=["land"], default_why="A general-purpose choice; the analysis can be redone for any subject."),
    Question(
        "imaging.gsd_m", "payload", "How small should one image pixel be on the ground?",
        "This is the ground sample distance (GSD). Smaller pixels show more detail but need a larger, heavier "
        "telescope, steadier pointing and much more data. The analysis checks what your CubeSat size can reach.",
        "number", "imaging.gsd_m", unit="m", min=0.3, max=2000.0, when=EO,
        options=(Option(1.0, "About 1 m", "Cars and single trees."),
                 Option(3.0, "About 3 m", "Houses and roads."),
                 Option(5.0, "About 5 m", "Buildings and small fields."),
                 Option(10.0, "About 10 m", "Fields and land use."),
                 Option(30.0, "About 30 m", "Land cover (Landsat's multispectral bands are 30 m, USGS)."),
                 Option(100.0, "About 100 m", "Regional patterns."),
                 Option(250.0, "About 250 m or more", "Weather-scale views.")),
        default=_gsd_default,
        default_why=lambda r: f"{_gsd_default(r):g} m suits {', '.join(_subjects(r))} imaging (ASSUMED design choice)."),
    Question(
        "imaging.bands", "payload", "Which colours (spectral bands) do you need?",
        "Visible colour shows what people see; near-infrared shows plant health; short-wave and thermal infrared see "
        "fire and heat but need special detectors (cooled thermal detectors need extra power and volume).",
        "multi", "imaging.bands", when=EO,
        options=(Option("rgb", "Visible colour (red, green, blue)"), Option("pan", "Panchromatic (one sharp band)"),
                 Option("nir", "Near-infrared"), Option("red_edge", "Red edge (vegetation)"),
                 Option("swir", "Short-wave infrared"), Option("tir", "Thermal infrared"),
                 Option("hyper", "Hyperspectral (many narrow bands)")),
        default=_bands_default,
        default_why=lambda r: f"{', '.join(_bands_default(r))} suit {', '.join(_subjects(r))} imaging (ASSUMED)."),
    Question(
        "target.region", "payload", "Which area do you want to observe?",
        "Coverage, revisit time and data volume all depend on where you image.",
        "region", "target.region", when=_is("mission.type", "earth_observation", "communications"),
        options=(Option("california", "California"), Option("global", "Anywhere on Earth"),
                 Option("custom", "A latitude/longitude box")),
        default=lambda r: "global",
        default_why="Without a target region the analysis uses the whole Earth."),
    Question(
        "imaging.need", "payload", "Do you want to map the whole area, or image chosen sites?",
        "A small satellite images a narrow strip, so mapping a large area takes many passes; imaging chosen sites "
        "needs fewer images and less data.",
        "choice", "imaging.need", when=EO,
        options=(Option("targets", "Image chosen sites"), Option("map", "Map the whole area repeatedly")),
        default="targets", default_why="Chosen sites are the lighter task for a small satellite (ASSUMED)."),
    Question(
        "imaging.targets_per_day", "payload", "How many sites per day?",
        "Each site is one image; together they set the daily data volume and the time spent pointing.",
        "number", "imaging.targets_per_day", unit="sites/day", min=1, max=500,
        when=_all(EO, _is("imaging.need", "targets")),
        default=5.0, default_why="Five sites a day is taken as a starting point (ASSUMED)."),
    Question(
        "imaging.refresh_days", "payload", "How often should the whole area be mapped again?",
        "Mapping a large area often needs a wide swath or several satellites.",
        "number", "imaging.refresh_days", unit="days", min=1, max=365,
        when=_all(EO, _is("imaging.need", "map")),
        default=30.0, default_why="A monthly map is taken as a starting point (ASSUMED)."),
    Question(
        "target.revisit_h", "payload", "How quickly do you need a new image of the same place?",
        "The time between looks at one place (revisit). One satellite sees a given place only every few passes unless "
        "it points sideways; the analysis computes what your orbit gives.",
        "choice", "target.revisit_h", unit="h", when=EO,
        options=(Option(8.0, "Several times a day"), Option(24.0, "Daily"), Option(72.0, "Every few days"),
                 Option(168.0, "Weekly"), Option(720.0, "Monthly")),
        default=72.0, default_why="Every few days is taken as a starting point (ASSUMED)."),
    Question(
        "imaging.night", "payload", "Do you need images at night?",
        "Night images need very sensitive detectors and longer exposures; most daytime cameras cannot do it.",
        "bool", "imaging.night", when=EO, default=False, default_why="Daytime imaging only (ASSUMED)."),
    Question(
        "imaging.video", "payload", "Do you need video?", "Video needs the satellite to track a site while it flies "
        "over, which raises the pointing and data requirements.",
        "bool", "imaging.video", when=EO, default=False, default_why="Still images only (ASSUMED).", advanced=True),
    Question(
        "imaging.off_nadir_deg", "payload", "How far sideways may the satellite point to image a site?",
        "Pointing sideways (off-nadir) lets one satellite revisit a place more often, but the pixels get larger and "
        "the satellite needs agile attitude control.",
        "number", "imaging.off_nadir_deg", unit="deg", min=0.0, max=45.0, when=EO,
        default=30.0, default_why="Up to 30° is taken as a starting point (ASSUMED).", advanced=True),
    Question(
        "imaging.snr_min", "payload", "What minimum signal-to-noise ratio do the images need?",
        "Higher SNR means cleaner images; it needs a larger aperture or longer exposures.",
        "number", "imaging.snr_min", min=5, max=1000, when=EO,
        default=100.0, default_why="100 is taken as a design goal (ASSUMED).", advanced=True),
    Question(
        "imaging.geolocation_m", "payload", "How accurately must each image be located on the ground?",
        "This sets how well the satellite must know where it points (attitude knowledge).",
        "number", "imaging.geolocation_m", unit="m", min=1, max=10_000, when=EO,
        default=lambda r: 2.0 * float(_v(r, "imaging.gsd_m", 10.0)),
        default_why="Two pixels is taken as the goal (ASSUMED).", advanced=True),
    Question(
        "imaging.compression", "payload", "How will images be compressed?",
        "Compression reduces the data to download; lossy compression saves more but discards detail.",
        "choice", "imaging.compression", when=EO,
        options=(Option(1.0, "None"), Option(2.0, "Lossless (about 2:1)"), Option(5.0, "Lossy (about 5:1)")),
        default=2.0, default_why="Lossless compression at 2:1 is taken as the ratio (ASSUMED; it depends on the scene).",
        advanced=True),
    # ------------------------------------------------------------------------------------------------- payload: other
    Question(
        "comms.service", "payload", "What kind of communications service?",
        "The service decides the radio band, the antennas and how long the satellite must listen.",
        "choice", "comms.service", when=COMMS,
        options=(Option("store_forward", "Collect data from ground sensors (store and forward)"),
                 Option("ais_adsb", "Receive ship (AIS) or aircraft (ADS-B) signals"),
                 Option("amateur", "Amateur radio repeater or beacon"),
                 Option("relay", "Real-time relay")),
        default="store_forward", default_why="Store and forward suits one small satellite (ASSUMED)."),
    Question(
        "comms.throughput_kbps", "payload", "How much user data per second must it carry?",
        "This sets the radio, the antenna and the power.", "number", "comms.throughput_kbps", unit="kbit/s",
        min=0.1, max=100_000, when=COMMS, default=9.6, default_why="9.6 kbit/s is taken as a starting point (ASSUMED)."),
    Question(
        "science.instrument", "payload", "What will the instrument measure?",
        "The instrument sets the pointing, the power and the data rate.", "choice", "science.instrument",
        when=SCIENCE,
        options=(Option("radiation", "Radiation or particles"), Option("magnetometer", "Magnetic field"),
                 Option("atmosphere", "The upper atmosphere (spectrometer)"), Option("ionosphere", "Space weather / "
                                                                                                    "ionosphere"),
                 Option("biology", "A biology or materials experiment"), Option("other", "Something else")),
        default="radiation", default_why="A radiation monitor is a common first science payload (ASSUMED)."),
    Question(
        "astro.goal", "payload", "What will the telescope do?",
        "Astronomy from a CubeSat is limited by the aperture and by how steadily it can point.", "choice",
        "astro.goal", when=ASTRO,
        options=(Option("photometry", "Measure star brightness (e.g. exoplanet transits)"),
                 Option("imaging", "Take images"), Option("spectroscopy", "Spectroscopy"),
                 Option("uv_xray", "Ultraviolet or X-ray survey")),
        default="photometry", default_why="Photometry suits a small aperture (ASSUMED)."),
    Question(
        "astro.stability_arcsec", "payload", "How steady must the pointing be during an exposure?",
        "Pointing stability blurs or sharpens star images; arcseconds need a star tracker and fine control.",
        "number", "astro.stability_arcsec", unit="arcsec", min=0.1, max=3600, when=ASTRO,
        default=10.0, default_why="10 arcsec is taken as a starting point (ASSUMED)."),
    Question(
        "techdemo.item", "payload", "What technology will be demonstrated?",
        "The demonstration decides the payload's size, power and data.", "choice", "techdemo.item", when=DEMO,
        options=(Option("propulsion", "A thruster"), Option("deployable", "A deployable structure"),
                 Option("optical_comm", "Laser communication"), Option("processor", "A computer or AI processor"),
                 Option("sensor", "A new sensor"), Option("other", "Something else")),
        default="processor", default_why="A processor demonstration is the simplest payload to fly (ASSUMED)."),
    Question(
        "payload.mass_kg", "payload", "About how heavy is your payload?",
        "Your own instrument becomes a placeholder block of this mass in the design (clearly labelled).",
        "number", "payload.mass_kg", unit="kg", min=0.01, max=20, when=CUSTOM_PAYLOAD,
        default=0.5, default_why="0.5 kg is taken as a placeholder (ASSUMED)."),
    Question(
        "payload.power_w", "payload", "About how much power does it use when on?",
        "Payload power drives the solar panels and the battery.", "number", "payload.power_w", unit="W", min=0.0,
        max=200, when=CUSTOM_PAYLOAD, default=2.0, default_why="2 W is taken as a placeholder (ASSUMED)."),
    Question(
        "payload.volume_u", "payload", "About how much volume does it take?",
        "1U is a 10 cm cube; the payload's volume decides the CubeSat size.", "number", "payload.volume_u",
        unit="U", min=0.1, max=10, when=CUSTOM_PAYLOAD, default=0.5,
        default_why="Half a unit is taken as a placeholder (ASSUMED)."),
    Question(
        "payload.data_kbps", "payload", "How much data does it produce while on?",
        "Data volume sets the onboard storage and the radio downlink.", "number", "payload.data_kbps",
        unit="kbit/s", min=0.0, max=1_000_000, when=CUSTOM_PAYLOAD, default=1.0,
        default_why="1 kbit/s is taken as a placeholder (ASSUMED)."),
    Question(
        "payload.duty_pct", "payload", "What share of each orbit is the payload on?",
        "The duty cycle averages the payload's power and data over an orbit.", "number", "payload.duty_pct",
        unit="%", min=0, max=100, when=CUSTOM_PAYLOAD, default=50.0,
        default_why="Half of each orbit is taken as a placeholder (ASSUMED)."),
    Question(
        "payload.pointing", "payload", "Where must the payload point?",
        "Pointing decides the attitude control hardware.", "choice", "payload.pointing", when=CUSTOM_PAYLOAD,
        options=(Option("none", "Nowhere in particular"), Option("nadir", "At the Earth"), Option("sun", "At the Sun"),
                 Option("inertial", "At fixed stars")),
        default=lambda r: "inertial" if _v(r, "mission.type") == "astronomy" else "none",
        default_why=lambda r: ("A telescope points at fixed stars." if _v(r, "mission.type") == "astronomy" else
                               "No pointing need is assumed (ASSUMED).")),
    # ------------------------------------------------------------------------------------------------- orbit
    Question(
        "orbit.choice", "orbit", "Do you have an orbit in mind?",
        "If you are not sure, the Builder recommends one from your mission and explains the trade.",
        "choice", "orbit.choice",
        options=(Option("recommend", "Recommend one for me"),
                 Option("sso", "Sun-synchronous (same local time every pass)"),
                 Option("iss", "Deployed from the International Space Station"),
                 Option("custom", "A specific altitude and inclination")),
        default="recommend", default_why="The Builder picks an orbit that suits the mission and explains why."),
    Question(
        "orbit.altitude_km", "orbit", "At what altitude?",
        "Lower orbits give sharper images and shorter radio links but decay faster from atmospheric drag; higher "
        "orbits last longer, which debris rules also look at.",
        "number", "orbit.altitude_km", unit="km", min=300, max=1200, when=_orbit_needs_altitude,
        default=500.0, default_why="500 km is taken as a starting point (ASSUMED); the analysis shows the lifetime."),
    Question(
        "orbit.ltdn_h", "orbit", "At what local solar time should it cross the equator southbound (descending node)?",
        "In a sun-synchronous orbit the equator crossing happens at the same local time each pass. Mid-morning gives "
        "sunlit ground with moderate shadows; a dawn-dusk orbit keeps the solar panels in sunlight.",
        "number", "orbit.ltdn_h", unit="h", min=0, max=24,
        when=lambda r: _v(r, "orbit.choice") == "sso" or (_v(r, "orbit.choice") == "recommend" and EO(r)),
        default=10.5,
        default_why="10:30 is taken (ASSUMED): it is the descending-node time of ESA's Sentinel-2 imaging mission.",
        advanced=True),
    Question(
        "orbit.inclination_deg", "orbit", "At what inclination?",
        "Inclination sets the highest latitude the satellite flies over; it must be at least the latitude of the "
        "area you observe.", "number", "orbit.inclination_deg", unit="deg", min=0, max=180,
        when=_is("orbit.choice", "custom"), default=None,
        default_why="Sun-synchronous inclination for the altitude (derived in the analysis)."),
    Question(
        "launch.environment", "orbit", "How will it be launched?",
        "The launch sets the vibration and load levels the structure is checked against.", "choice",
        "launch.environment",
        options=(Option("gevs", "Not decided (NASA GEVS levels)"),
                 Option("spacex", "SpaceX rideshare (containerised CubeSat)"),
                 Option("nanoracks", "From the ISS (NanoRacks deployer)")),
        default=lambda r: "nanoracks" if _v(r, "orbit.choice") == "iss" else "gevs",
        default_why="GEVS levels are used until a launch is chosen (they are the V2 default)."),
    Question(
        "launch.max_size_u", "orbit", "Is the CubeSat size limited?",
        "Bigger CubeSats hold bigger payloads and solar panels but cost more to launch.", "choice",
        "launch.max_size_u",
        options=(Option(None, "No — recommend a size"), Option(1, "1U"), Option(2, "2U"), Option(3, "3U"),
                 Option(6, "6U"), Option(12, "12U")),
        default=None, default_why="The Builder recommends the smallest size that fits the requirements."),
    # ------------------------------------------------------------------------------------------------- spacecraft
    Question(
        "mission.reliability", "spacecraft", "How much redundancy do you want?",
        "Redundant parts survive a failure but add mass, power and cost.", "choice", "mission.reliability",
        options=(Option("single", "Single string (lowest cost)"), Option("selective", "Back-ups for key parts"),
                 Option("redundant", "Redundant throughout")),
        default="single", default_why="Single string is usual for a first concept (ASSUMED)."),
    Question(
        "propulsion.need", "spacecraft", "Does the satellite need a thruster?",
        "A thruster can keep a low orbit up, change the orbit or bring the satellite down at the end; it adds mass, "
        "volume, cost and safety reviews.", "choice", "propulsion.need",
        options=(Option("recommend", "Only if the analysis says so"), Option("none", "No"),
                 Option("drag", "Yes, to hold the altitude"), Option("deorbit", "Yes, to de-orbit at the end"),
                 Option("maneuver", "Yes, to change orbit")),
        default="recommend", default_why="The analysis decides from the orbit lifetime and the debris rules."),
    Question(
        "data.onboard_processing", "spacecraft", "Should the satellite process data on board?",
        "Processing on board (for example discarding cloudy images) saves downlink but needs a stronger computer.",
        "bool", "data.onboard_processing", default=False, default_why="No on-board processing (ASSUMED).",
        advanced=True),
    # ------------------------------------------------------------------------------------------------- operations
    Question(
        "comms.station", "operations", "Where is your ground station?",
        "The ground station sets how often and how long the satellite can download its data.", "station",
        "comms.station",
        options=(Option("uc-berkeley", "UC Berkeley"), Option("custom", "Somewhere else (latitude/longitude)")),
        default="uc-berkeley", default_why="UC Berkeley with a 10° elevation mask (the approved demo default)."),
    Question(
        "comms.band", "operations", "Which radio band for the data downlink?",
        "UHF is simple but slow; S-band is faster; X-band is fastest but needs a dish on the ground and more power.",
        "choice", "comms.band",
        options=(Option("recommend", "Recommend from the data volume"), Option("uhf", "UHF"), Option("s", "S-band"),
                 Option("x", "X-band")),
        default="recommend", default_why="The Builder picks the band from the daily data volume."),
    Question(
        "comms.licence", "operations", "Is the mission amateur (non-commercial) or commercial?",
        "Amateur radio bands are only for non-commercial use; a commercial or Earth-imaging downlink needs its own "
        "licence. This is a checklist item, not legal advice.", "choice", "comms.licence",
        options=(Option("amateur", "Amateur / educational"), Option("commercial", "Commercial or government"),
                 Option("unsure", "Not sure")),
        default="unsure", default_why="The licensing checklist lists both routes."),
)

BY_ID = {q.id: q for q in QUESTIONS}


# =================================================================================================== engine
def applicable(design: dict) -> list[Question]:
    r = design.get("requirements", {})
    return [q for q in QUESTIONS if q.when(r)]


def pending(design: dict, expert: bool = False) -> list[Question]:
    """The applicable questions without an answer, in asking order (advanced ones only in expert mode)."""
    ans = design.get("answers", {})
    return [q for q in applicable(design) if q.id not in ans and (expert or not q.advanced)]


def completeness(design: dict, expert: bool = False) -> dict:
    qs = [q for q in applicable(design) if expert or not q.advanced]
    done = sum(1 for q in qs if q.id in design.get("answers", {}))
    return {"answered": done, "total": len(qs), "complete": done == len(qs)}


def _check(q: Question, val):
    """The answer as stored, or ValueError with a plain reason."""
    if q.kind in ("choice",):
        allowed = [o.value for o in q.options]
        if val not in allowed:
            raise ValueError(f"{q.id}: choose one of {allowed}")
        return next(o.value for o in q.options if o.value == val)      # the option's own value (24 → 24.0)
    if q.kind == "multi":
        allowed = [o.value for o in q.options]
        vals = list(val) if isinstance(val, (list, tuple)) else [val]
        if not vals or any(x not in allowed for x in vals):
            raise ValueError(f"{q.id}: choose one or more of {allowed}")
        return [x for x in allowed if x in vals]
    if q.kind == "number":
        if val is None and q.default is None:
            return None
        try:
            x = float(val)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{q.id}: a number{f' in {q.unit}' if q.unit else ''}") from exc
        if (q.min is not None and x < q.min) or (q.max is not None and x > q.max):
            raise ValueError(f"{q.id}: between {q.min:g} and {q.max:g}{f' {q.unit}' if q.unit else ''}")
        return x
    if q.kind == "bool":
        if not isinstance(val, bool):
            raise ValueError(f"{q.id}: yes or no")
        return val
    if q.kind == "region":
        if isinstance(val, dict):
            return regions.custom_region(val["lat_min"], val["lat_max"], val["lon_min"], val["lon_max"],
                                         val.get("name", "Custom region"))
        if val == "global":
            return {"key": "global", "name": "Anywhere on Earth", "source": "the whole Earth"}
        r = regions.region(str(val))
        if r is None:
            raise ValueError(f"{q.id}: a known region ({', '.join(regions.REGIONS)}), 'global' or a box")
        return r
    if q.kind == "station":
        if isinstance(val, dict):
            return regions.custom_station(val["lat"], val["lon"], val.get("min_elev_deg", 10.0),
                                          val.get("name", "Ground station"))
        s = regions.station(str(val))
        if s is None:
            raise ValueError(f"{q.id}: a known station ({', '.join(regions.STATIONS)}) or lat/lon")
        return s
    if q.kind == "text":
        return str(val)
    raise ValueError(f"{q.id}: unknown kind {q.kind}")


def _apply_all(design: dict) -> None:
    """Rebuild the requirements from the answers, in asking order, so that `when` sees the answers before it."""
    design["requirements"] = {}
    r = design["requirements"]
    ans = design.get("answers", {})
    for q in QUESTIONS:
        if q.id not in ans or not q.when(r):
            continue
        a = ans[q.id]
        if a.get("unknown"):
            dv = _check(q, q.default_value(r)) if q.default_value(r) is not None else None
            r[q.key] = req(dv, "default", q.unit, q.default_reason(r), q.id)
        else:
            r[q.key] = req(a["value"], a.get("source", "user"), q.unit, "", q.id)


def answer(design: dict, qid: str, val=None, unknown: bool = False, source: str = "user") -> dict:
    """Record an answer (or "I don't know") and rebuild the requirements. ValueError on a bad answer."""
    q = BY_ID.get(qid)
    if q is None:
        raise KeyError(qid)
    r = design.get("requirements", {})
    if not q.when(r):
        raise ValueError(f"{qid} does not apply to this design")
    if unknown:
        entry = {"value": None, "unknown": True, "at": now_iso(), "source": "default"}
    else:
        entry = {"value": _check(q, val), "unknown": False, "at": now_iso(), "source": source}
    design.setdefault("answers", {})[qid] = entry
    _apply_all(design)
    touch(design, f"answered {qid}" + (" (I don't know)" if unknown else ""))
    return design


def unanswer(design: dict, qid: str) -> dict:
    """Forget an answer (the question is asked again)."""
    if design.get("answers", {}).pop(qid, None) is not None:
        _apply_all(design)
        touch(design, f"cleared {qid}")
    return design


def accept_defaults(design: dict, expert: bool = False) -> dict:
    """Answer every pending question with "I don't know" (its default), repeatedly until nothing applicable is left
    (a default can make further questions apply)."""
    for _ in range(len(QUESTIONS)):
        todo = pending(design, expert)
        if not todo:
            break
        for q in todo:
            if q.when(design.get("requirements", {})) and q.id not in design.get("answers", {}):
                design.setdefault("answers", {})[q.id] = {"value": None, "unknown": True, "at": now_iso(),
                                                          "source": "default"}
                _apply_all(design)
    touch(design, "accepted the defaults for the remaining questions")
    return design


def display(q: Question, val) -> str:
    """An answer in words (option labels, units, region and station names)."""
    labels = {repr(o.value): o.label for o in q.options}
    if q.kind == "choice":
        return labels.get(repr(val), "not set" if val is None else str(val))
    if val is None:
        return "not set"
    if q.kind == "multi":
        return ", ".join(labels.get(repr(x), str(x)) for x in val)
    if q.kind == "number":
        return f"{float(val):g}{f' {q.unit}' if q.unit else ''}"
    if q.kind == "bool":
        return "Yes" if val else "No"
    if q.kind == "region":
        if val.get("key") == "global":
            return val["name"]
        return (f"{val['name']} ({_lat(val['lat_min'])} to {_lat(val['lat_max'])}, "
                f"{_lon(val['lon_min'])} to {_lon(val['lon_max'])})")
    if q.kind == "station":
        return f"{val['name']} ({_lat(val['lat'])}, {_lon(val['lon'])}), {val['min_elev_deg']:g}° elevation mask"
    return str(val)


def _lat(x: float) -> str:
    return f"{abs(float(x)):g}° {'N' if float(x) >= 0 else 'S'}"


def _lon(x: float) -> str:
    return f"{abs(float(x)):g}° {'E' if float(x) >= 0 else 'W'}"


def describe(q: Question, design: dict) -> dict:
    """The question as the app shows it: text, options, its default and why, and the current answer."""
    r = design.get("requirements", {})
    a = design.get("answers", {}).get(q.id)
    dv = q.default_value(r)
    return {"id": q.id, "section": q.section, "prompt": q.prompt, "help": q.help, "kind": q.kind, "key": q.key,
            "unit": q.unit, "min": q.min, "max": q.max, "advanced": q.advanced,
            "options": [{"value": o.value, "label": o.label, "explain": o.explain} for o in q.options],
            "default": dv, "default_why": q.default_reason(r), "answer": a}


SECTIONS = {"mission": "Mission", "payload": "Payload", "orbit": "Orbit and launch", "spacecraft": "Spacecraft",
            "operations": "Operations"}
