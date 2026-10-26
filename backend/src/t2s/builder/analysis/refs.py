"""Constants and reference data of the Builder's analyses, each with its source (verified 2026-10-25 unless marked).

REFS holds the sources; every Calc names the REFS keys it rests on. Values that could not be verified against a
primary source are marked `verified: False` and used only as ASSUMED design parameters.
"""
from __future__ import annotations

ACCESSED = "2026-10-25"

REFS = {
    "wgs84": {"title": "WGS 84 — Defining Parameters", "publisher": "National Geospatial-Intelligence Agency (NGA)",
              "url": "https://earth-info.nga.mil/index.php?dir=wgs84&action=wgs84"},
    "nssdca_earth": {"title": "Earth Fact Sheet", "publisher": "NASA GSFC NSSDCA (updated 15 Nov 2024)",
                     "url": "https://nssdc.gsfc.nasa.gov/planetary/factsheet/earthfact.html"},
    "sso_rate": {"title": "Analysis of the effects of mean local node-crossing time on the evolution of "
                          "Sun-synchronous orbits (Jordan, Blaes, Roszman, Cooley, 1993)",
                 "publisher": "NASA GSFC / NTRS", "url": "https://ntrs.nasa.gov/citations/19930015517"},
    "tsi": {"title": "SORCE — total solar irradiance 1360.8 W/m² at the 2008 solar minimum (Kopp & Lean 2011, GRL "
                     "38, L01706)", "publisher": "NASA GSFC",
            "url": "https://earth.gsfc.nasa.gov/climate/projects/solar-irradiance/missions/sorce"},
    "ecss_albedo": {"title": "ECSS-E-ST-10-04C Space environment (2008), Annex F.5.1 Earth albedo (SPENVIS copy; "
                             "superseded by Rev.1 2020, not checked)", "publisher": "ECSS / SPENVIS",
                    "url": "https://spenvis.oma.be/ecss/e_st_10_04c/ecss_17_05_01.htm"},
    "ecss_ir": {"title": "ECSS-E-ST-10-04C Space environment (2008), Annex F.5.2 Earth infrared (SPENVIS copy)",
                "publisher": "ECSS / SPENVIS", "url": "https://spenvis.oma.be/ecss/e_st_10_04c/ecss_17_05_02.htm"},
    "vallado_atm": {"title": "Exponential atmosphere model (Vallado, Fundamentals of Astrodynamics and "
                             "Applications; data file ATMOSEXP.DAT, 1000 km row from two agreeing reproductions)",
                    "publisher": "CelesTrak / D. Vallado",
                    "url": "https://raw.githubusercontent.com/CelesTrak/fundamentals-of-astrodynamics/main/software/"
                           "misc/pascal/ATMOSEXP.DAT"},
    "igrf14": {"title": "Magnetic North, Geomagnetic and Magnetic Poles (IGRF-14 dipole moment by epoch)",
               "publisher": "World Data Center for Geomagnetism, Kyoto University",
               "url": "https://wdc.kugi.kyoto-u.ac.jp/poles/polesexp.html"},
    "cds": {"title": "CubeSat Design Specification Rev. 14.1 (CP-CDS-R14.1, February 2022); mass limits read from "
                     "search indexing of the PDF and two agreeing reproductions",
            "publisher": "The CubeSat Program, Cal Poly SLO", "url": "https://www.cubesat.org/cubesatinfo"},
    "nasa_soa_struct": {"title": "State-of-the-Art of Small Spacecraft Technology, 6.0 Structures, Table 6-1 "
                                 "(CubeSat standard structure dimensions)",
                        "publisher": "NASA Small Spacecraft Systems Virtual Institute",
                        "url": "https://www.nasa.gov/smallsat-institute/sst-soa/structures-materials-and-mechanisms/"},
    "cds_cg_secondary": {"title": "CDS Rev 14 (2020 draft) Table 2 centre-of-gravity ranges, reproduced in EPET 302 "
                                  "(UNVERIFIED against Rev 14.1)", "publisher": "University of Hawaii OER",
                         "url": "https://pressbooks-dev.oer.hawaii.edu/epet302/chapter/4-6-structural-analysis/"},
    "sentinel2": {"title": "S2 Mission — 10:30 mean local solar time at the descending node", "publisher": "ESA",
                  "url": "https://sentiwiki.copernicus.eu/web/s2-mission"},
    "landsat8": {"title": "Landsat 8 — 30 m multispectral, 15 m panchromatic", "publisher": "USGS",
                 "url": "https://www.usgs.gov/landsat-missions/landsat-8"},
    "rr_5282": {"title": "ITU Radio Regulations footnote 5.282 (amateur-satellite service in 435–438 MHz), as "
                         "reproduced in 47 CFR 2.106", "publisher": "Cornell LII / US CFR",
                "url": "https://www.law.cornell.edu/cfr/text/47/2.106"},
    "nas_spectrum": {"title": "Handbook of Frequency Allocations and Spectrum Protection for Scientific Uses, 2nd "
                              "ed. (2015), Table 5.1 (EESS 2200–2290 MHz and 8025–8400 MHz)",
                     "publisher": "National Academies Press", "url": "https://www.nationalacademies.org/read/21774/chapter/7"},
    "nist_k": {"title": "CODATA value: Boltzmann constant (exact)", "publisher": "NIST",
               "url": "https://physics.nist.gov/cgi-bin/cuu/Value?k"},
    "fcc_5yr": {"title": "Mitigation of Orbital Debris in the New Space Age (89 FR 65217, 2024): disposal no later "
                         "than five years after the end of the mission, for satellites launched after 29 Sep 2024",
                "publisher": "FCC / Federal Register",
                "url": "https://www.govinfo.gov/content/pkg/FR-2024-08-09/html/2024-17093.htm"},
    "bpsk": {"title": "Analytical expressions used in berawgn (BPSK: Pb = Q(√(2Eb/N0)), Proakis eq. 5.2-57); "
                      "9.6 dB at BER 1e-5 computed from it", "publisher": "MathWorks",
             "url": "https://www.mathworks.com/help/comm/ug/analytical-expressions-used-in-berawgn-function-and-bit-"
                    "error-rate-analysis-app.html"},
    "tsis_ssi": {"title": "TSIS-1 Hybrid Solar Reference Spectrum, 1 nm (Coddington et al. 2021)",
                 "publisher": "LASP / NASA TSIS-1", "url": "https://lasp.colorado.edu/lisird/"},
    "nasa_grc_liion": {"title": "Lithium-Ion Batteries Being Evaluated for Low-Earth-Orbit Applications (NASA GRC, "
                                "2005): LEO tests at 20–40 % depth of discharge", "publisher": "NASA GRC / NTRS",
                       "url": "https://ntrs.nasa.gov/citations/20050217178"},
    "si": {"title": "The International System of Units (SI), 9th ed. (2019): exact h, c, k; standard gravity "
                    "9.80665 m/s²", "publisher": "BIPM", "url": "https://www.bipm.org/en/publications/si-brochure"},
    "nasa_iss": {"title": "Spot the Station (ISS inclination 51.6°); ISS overview (operating altitude 370–460 km)",
                 "publisher": "NASA", "url": "https://www.nasa.gov/spot-the-station/"},
    "iers2010": {"title": "IERS Conventions (2010), obliquity of the ecliptic at J2000 ε0 = 84381.406″",
                 "publisher": "IERS", "url": "https://www.iers.org/IERS/EN/Publications/TechnicalNotes/tn36.html"},
}

ISS_INCLINATION_DEG = 51.6     # [nasa_iss]
ISS_ALTITUDE_KM = 400.0        # within NASA's 370–460 km operating band (ASSUMED value in the band) [nasa_iss]

# ---------------------------------------------------------------------------------------------- constants (SI)
MU = 3.986004418e14            # m³/s², WGS 84 [wgs84]
RE = 6378137.0                 # m, WGS 84 equatorial radius [wgs84]
J2 = 1.08263e-3                # [nssdca_earth]
OMEGA_E = 7.292115e-5          # rad/s, WGS 84 [wgs84]
SSO_RATE = 0.9856 * 3.141592653589793 / 180.0 / 86400.0   # rad/s, mean-Sun apparent precession [sso_rate]
S0 = 1360.8                    # W/m², total solar irradiance [tsi]
ALBEDO = 0.30                  # mean; 0.05–0.6 [ecss_albedo]
ALBEDO_RANGE = (0.05, 0.6)
EARTH_IR = 230.0               # W/m², mean; 150–350 [ecss_ir]
EARTH_IR_RANGE = (150.0, 350.0)
EARTH_DIPOLE = 7.69e15         # T·m³ (IGRF-14 2025: 7.69e22 A·m² × μ0/4π) [igrf14]
SIGMA = 5.670374419e-8         # W/m²/K⁴ (from exact SI constants) [si]
H_PLANCK = 6.62607015e-34      # J·s [si]
C_LIGHT = 299792458.0          # m/s [si]
K_BOLTZ = 1.380649e-23         # J/K [nist_k]
K_DB = -228.6                  # dBW/K/Hz, 10·log10(k) [nist_k]
G0 = 9.80665                   # m/s² [si]
SSI_550 = 1.9063               # W/m²/nm, top-of-atmosphere solar spectral irradiance at 550 nm (1 nm bins) [tsis_ssi]
EBN0_BPSK_1E5 = 9.6            # dB, uncoded BPSK at BER 1e-5 [bpsk]
FCC_DISPOSAL_YEARS = 5.0       # [fcc_5yr]
IADC_LIFETIME_YEARS = 25.0     # [fcc_5yr] (the notice states the IADC guideline)

# Vallado exponential atmosphere: (base altitude km, density kg/m³, scale height km) [vallado_atm]
ATMOSPHERE = ((300, 2.418e-11, 53.628), (350, 9.518e-12, 53.298), (400, 3.725e-12, 58.515),
              (450, 1.585e-12, 60.828), (500, 6.967e-13, 63.822), (600, 1.454e-13, 71.835),
              (700, 3.614e-14, 88.667), (800, 1.170e-14, 124.64), (900, 5.245e-15, 181.05),
              (1000, 3.019e-15, 268.00))

# CubeSat Design Specification Rev 14.1 [cds]: mass limits (kg) and nominal outer size (mm) [nasa_soa_struct]
CDS_MASS_KG = {1: 2.0, 1.5: 3.0, 2: 4.0, 3: 6.0, 6: 12.0, 12: 24.0}
CDS_SIZE_MM = {1: (100.0, 100.0, 113.5), 1.5: (100.0, 100.0, 170.2), 2: (100.0, 100.0, 227.0),
               3: (100.0, 100.0, 340.5), 6: (226.3, 100.0, 366.0), 12: (226.3, 226.3, 366.0)}
# centre-of-gravity ranges (± cm from the geometric centre) — UNVERIFIED against Rev 14.1 [cds_cg_secondary]
CDS_CG_CM = {1: (2, 2, 2), 1.5: (2, 2, 3), 2: (2, 2, 4.5), 3: (2, 2, 7), 6: (4.5, 2, 7), 12: (4.5, 4.5, 7)}
CDS_PROTRUSION_MM = 6.5        # beyond the rail plane, shaded sides [cds]

# design parameters that could not be verified against their usual source: ASSUMED, adjustable
ASSUMED = {
    "path_eff_eclipse": (0.65, ("power path efficiency array → battery → loads (eclipse); the value usually "
                                "attributed to SMAD for peak-power tracking, NOT verified here (ASSUMED)")),
    "path_eff_day": (0.85, ("power path efficiency array → loads (daylight); usually attributed to SMAD for "
                            "peak-power tracking, NOT verified here (ASSUMED)")),
    "battery_dod": (0.30, ("depth of discharge per orbit; NASA GRC tested Li-ion LEO cycling at 20–40 % DoD and a "
                           "JAXA review says LEO batteries run below 40 % (ASSUMED within that range)")),
}


def ref(key: str) -> dict:
    return {"key": key, **REFS[key], "accessed": ACCESSED}
