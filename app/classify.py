"""Static knowledge: aircraft-type -> silhouette class, rare airframes, military heuristics."""
import re

QUAD = {"A388", "B744", "B748", "B74S", "B742", "B743", "B74R", "A124", "A225", "A342", "A343",
        "A345", "A346", "IL96", "DC8", "B703", "B52", "VC10"}
WIDE = {"A306", "A30B", "A310", "A332", "A333", "A338", "A339", "A359", "A35K", "B762", "B763",
        "B764", "B772", "B773", "B77L", "B77W", "B788", "B789", "B78X", "DC10", "MD11", "L101",
        "IL86", "B703", "E3TF", "E3CF", "E6", "E8", "KC10", "K35R", "KC46", "A332"}
TRANSPORT = {"C17", "C5M", "C5", "C130", "C30J", "A400", "A3ST", "A337", "C2", "AN12", "IL76",
             "C160", "C295", "CN35", "A400", "P3", "P8", "E2", "V22", "AN26", "AN24"}
FIGHTER = {"F16", "F15", "F18", "F18H", "F18S", "F22", "F35", "EUFI", "TOR", "RFAL", "GRIP", "HAWK",
           "M346", "T38", "A10", "HARR", "F5", "F4", "MIR2", "J11", "SU27", "SU30", "B1", "B2",
           "T6", "TEX2", "PC21", "PC9"}
PROP = {"AT42", "AT43", "AT44", "AT45", "AT46", "AT72", "AT73", "AT75", "AT76", "DH8A", "DH8B",
        "DH8C", "DH8D", "SF34", "JS31", "JS32", "JS41", "E120", "B190", "C208", "PC12", "BE20",
        "BE9L", "SW4", "D228", "DHC6", "F50", "F27", "L410", "B350", "TBM8", "TBM9", "DHC7", "SB20"}
HELI = {"R44", "R22", "R66", "EC35", "EC45", "EC30", "EC20", "AS50", "AS55", "AS65", "H60", "A109",
        "A139", "A169", "S76", "S92", "B06", "B407", "B412", "EC55", "H47", "CH47", "MI8", "AW19"}
GLIDER = {"GLID", "ASK2", "DG80", "LS8", "DISC", "ARCE"}
LIGHT = {"C172", "C150", "C152", "C162", "C182", "C206", "C210", "PA28", "PA32", "PA34", "PA44",
         "PA46", "SR20", "SR22", "DA40", "DA42", "DA62", "TB20", "P28A", "BE33", "BE36", "AA5",
         "RV7", "RV8", "M20P", "G115", "TOBA", "AC11", "J3", "SIRA", "EVOT", "DR40", "PC6T"}

# Rare / crowd-pleasing airframes: ICAO type -> display name
RARE = {
    "C17": "Boeing C-17 Globemaster III", "C5M": "Lockheed C-5M Galaxy", "C5": "Lockheed C-5 Galaxy",
    "A3ST": "Airbus Beluga", "A337": "Airbus BelugaXL", "A124": "Antonov An-124 Ruslan",
    "A225": "Antonov An-225 Mriya", "AN12": "Antonov An-12", "IL76": "Ilyushin Il-76",
    "B52": "Boeing B-52 Stratofortress", "B1": "Rockwell B-1B Lancer", "B2": "Northrop B-2 Spirit",
    "SPIT": "Supermarine Spitfire", "P51": "North American P-51 Mustang", "B17": "Boeing B-17",
    "B29": "Boeing B-29", "LANC": "Avro Lancaster", "HURI": "Hawker Hurricane", "DC3": "Douglas DC-3",
    "DC6": "Douglas DC-6", "DC4": "Douglas DC-4", "CONC": "Concorde", "VC10": "Vickers VC10",
    "E3TF": "Boeing E-3 Sentry (AWACS)", "E3CF": "Boeing E-3 Sentry (AWACS)", "E6": "Boeing E-6 Mercury",
    "E8": "Northrop E-8 JSTARS", "KC10": "McDonnell Douglas KC-10", "K35R": "Boeing KC-135",
    "KC46": "Boeing KC-46 Pegasus", "A400": "Airbus A400M Atlas", "V22": "Bell Boeing V-22 Osprey",
    "U2": "Lockheed U-2", "P8": "Boeing P-8 Poseidon", "R135": "Boeing RC-135", "RQ4": "Northrop RQ-4 Global Hawk",
    "A388": "Airbus A380", "B748": "Boeing 747-8", "B744": "Boeing 747-400", "B74S": "Boeing 747SP",
    "HAWK": "BAE Hawk (Red Arrows?)", "F35": "Lockheed F-35", "F22": "Lockheed F-22 Raptor",
    "TOR": "Panavia Tornado", "EUFI": "Eurofighter Typhoon", "RFAL": "Dassault Rafale",
}

MIL_HEX_RANGES = [  # (low, high) inclusive. DB flags are the primary source; this is a safety net.
    (0xADF7C8, 0xAFFFFF),  # USA military
    (0x43C000, 0x43CFFF),  # UK military
]
MIL_CALLSIGN = re.compile(
    r"^(RCH|REACH|CNV|RRR|ASCOT|NATO|FORTE|HAF|GAF|BAF|IAM|FAF|CTM|PLF|MMF|NAVY|PAT|KNIGHT|"
    r"JAKE|HOMER|BOLT|DUKE|TOPCAT|LAGR|TARTAN|COLT|VIPER|REAPER|CHAOS|MAGMA|HERKY|PEARL|SHELL|"
    r"TEAL|RFR|NOBLE|HUNTER|RAZOR|IRON|SWORD|SENTRY|NCHO|PYTHON|BLKCAT)\d")
VIP_CALLSIGN = re.compile(r"^(SAM|SPAR|EXEC|AF1|AF2|VENUS|KAF|KOWL|RFF|ZZ\d|MAGIC)\d*")
VIP_OWNER = re.compile(r"GOVERNMENT|MINISTRY|PRESIDENT|ROYAL FLIGHT|STATE OF|REPUBLIC OF|AMIRI", re.I)
MIL_OWNER = re.compile(r"AIR FORCE|NAVY|ARMY|MARINE|MILITARY|DEFENCE|DEFENSE|LUFTWAFFE|ARMEE|MINISTRY OF DEFEN", re.I)

# Police / air-ambulance / emergency-service flights: loiter for ages, so they are demoted in selection.
SERVICE_OWNER = re.compile(r"POLICE|AMBULANCE|HEMS|NPAS|AIR SUPPORT|CONSTABULARY|FIRE (AND|&|SERVICE|BRIGADE)|"
                           r"RESCUE|\bNHS\b|MEDICAL|PARAMEDIC|LIFEGUARD|GNAAS|SHERIFF", re.I)
SERVICE_CALLSIGN = re.compile(r"^(NPAS|POLICE|MEDIC|AMBULANCE|HEMS|AIRMED|LIFEGUARD|AIRAMB|HLE|SHERIFF|COPTER)\d*")

CALLSIGN_RE =re.compile(r"^([A-Z]{3})(\d{1,4}[A-Z]{0,2})$")


def is_military_hex(hex_):
    try:
        h = int(hex_, 16)
    except (TypeError, ValueError):
        return False
    return any(lo <= h <= hi for lo, hi in MIL_HEX_RANGES)


def silhouette(type_code, category="", military=False):
    t = (type_code or "").upper()
    if t in QUAD:
        return "quad"
    if t in TRANSPORT:
        return "transport"
    if t in FIGHTER:
        return "fighter"
    if t in WIDE:
        return "widebody"
    if t in HELI or category == "A7":
        return "heli"
    if t in GLIDER or category == "B1":
        return "glider"
    if t in PROP:
        return "prop"
    if t in LIGHT or category == "A1":
        return "light"
    if t:
        return "jet"
    # no type known: guess from ADS-B emitter category
    return {"A5": "widebody", "A4": "widebody", "A2": "prop"}.get(category, "jet")


def split_callsign(cs):
    m = CALLSIGN_RE.match(cs or "")
    return (m.group(1), m.group(2)) if m else (None, None)
