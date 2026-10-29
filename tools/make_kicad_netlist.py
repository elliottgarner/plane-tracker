"""Generate hardware/plane_tracker_carrier.net (KiCad netlist) and hardware/bom.csv.

Single source of truth for the carrier board in docs/pcb_schematic.svg.
    python tools/make_kicad_netlist.py
In KiCad's PCB editor: File > Import > Netlist..., pick the .net, tick "Re-link footprints to
schematic symbols based on their reference designators", Update PCB.
"""
import csv
import datetime
import sys
from collections import defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "hardware"

HDR = "Connector_PinHeader_2.54mm:PinHeader_1x{n:02d}_P2.54mm_Vertical"
TERM = "TerminalBlock:TerminalBlock_bornier-2_P5.08mm"
ELEC = "Capacitor_THT:CP_Radial_D6.3mm_P2.50mm"

# ref -> (value, footprint, note)
PARTS = {
    "J1": ("Barrel jack 12V", "Connector_BarrelJack:BarrelJack_Horizontal", "pin1 tip +, pin2 sleeve GND, pin3 switch (unused)"),
    "F1": ("2A PTC", "Fuse:Fuse_1812_4532Metric", "resettable fuse"),
    "D1": ("SMBJ15A", "Diode_SMD:D_SMB", "TVS on the 12V rail, K=1 A=2"),
    "C1": ("100uF 25V", ELEC, "12V bulk, pin1 +"),
    "U1": ("Buck module (Pi, 5.17V)", HDR.format(n=4), "pins IN+ GND OUT+ EN - CHECK YOUR MODULE'S PIN ORDER"),
    "U2": ("Buck module (display, 5.0V)", HDR.format(n=4), "pins IN+ GND OUT+ EN - CHECK YOUR MODULE'S PIN ORDER"),
    "C2": ("100uF 10V", ELEC, "5V_PI bulk, pin1 +"),
    "C3": ("100uF 10V", ELEC, "5V_DISP bulk, pin1 +"),
    "J2": ("To Pi USB-C power", TERM, "pin1 +5V_PI, pin2 GND"),
    "J3": ("To display 5V", TERM, "pin1 +, pin2 GND"),
    "JP1": ("Display 5V bypass", "Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm", "close it if no relay is fitted"),
    "J8": ("Relay contacts COM/NO", TERM, "pin1 COM (5V_DISP), pin2 NO (to J3)"),
    "J4": ("Pi 40-pin socket", "Connector_PinSocket_2.54mm:PinSocket_2x20_P2.54mm_Vertical", "odd pins = left column, pin1 3V3"),
    "J5": ("PIR SR505", HDR.format(n=3), "1 VCC, 2 OUT, 3 GND - check your module's order"),
    "J6": ("Encoder HW-040", HDR.format(n=5), "1 CLK, 2 DT, 3 SW, 4 +, 5 GND"),
    "C4": ("100nF", "Capacitor_SMD:C_0805_2012Metric", "CLK debounce (optional)"),
    "C5": ("100nF", "Capacitor_SMD:C_0805_2012Metric", "DT debounce (optional)"),
    "J7": ("Relay module header", HDR.format(n=3), "1 VCC, 2 IN, 3 GND (use this OR the Q1 driver)"),
    "R1": ("1k", "Resistor_SMD:R_0805_2012Metric", "Q1 base resistor (optional driver)"),
    "Q1": ("BC337", "Package_TO_SOT_THT:TO-92_Inline", "1 C, 2 B, 3 E (optional driver)"),
    "D2": ("1N4148", "Diode_SMD:D_SOD-123", "flyback, K=1 A=2 (optional driver)"),
    "J9": ("Relay coil (bare relay)", HDR.format(n=2), "1 +5V_PI, 2 Q1 collector (optional driver)"),
}

NETS = {
    "GND": ["J1.2", "U1.2", "U2.2", "J2.2", "J3.2", "J4.6", "J4.9", "J4.14", "J4.20", "J5.3", "J6.5",
            "J7.3", "Q1.3", "D1.2", "C1.2", "C2.2", "C3.2", "C4.2", "C5.2"],
    "+12V": ["J1.1", "F1.1"],
    "+12V_F": ["F1.2", "U1.1", "U2.1", "D1.1", "C1.1"],
    "+5V_PI": ["U1.3", "J2.1", "C2.1", "J7.1", "J9.1", "D2.1"],
    "+5V_DISP": ["U2.3", "C3.1", "JP1.1", "J8.1"],
    "+5V_DISP_OUT": ["JP1.2", "J8.2", "J3.1"],
    "PI_5V": ["J4.2", "J4.4", "J5.1"],          # the Pi's own 5V pins: never joined to the buck rails
    "+3V3": ["J4.1", "J4.17", "J6.4"],
    "GPIO14_PIR": ["J4.8", "J5.2"],
    "GPIO27_SW": ["J4.13", "J6.3"],
    "GPIO22_CLK": ["J4.15", "J6.1", "C4.1"],
    "GPIO23_DT": ["J4.16", "J6.2", "C5.1"],
    "GPIO26_RELAY": ["J4.37", "J7.2", "R1.1"],
    "Q1_BASE": ["R1.2", "Q1.2"],
    "COIL_LOW": ["Q1.1", "D2.2", "J9.2"],
}


def check():
    seen = defaultdict(list)
    for net, nodes in NETS.items():
        for n in nodes:
            ref = n.split(".")[0]
            if ref not in PARTS:
                sys.exit(f"net {net}: unknown part {n}")
            seen[n].append(net)
    dup = {n: v for n, v in seen.items() if len(v) > 1}
    if dup:
        sys.exit(f"pins on more than one net: {dup}")


def q(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main():
    check()
    OUT.mkdir(exist_ok=True)
    lines = ["(export (version \"E\")",
             f"  (design (source {q('plane_tracker_carrier')}) (date {q(datetime.date.today().isoformat())})"
             f" (tool {q('make_kicad_netlist.py')}))", "  (components"]
    for ref, (val, fp, _) in PARTS.items():
        lines.append(f"    (comp (ref {q(ref)}) (value {q(val)}) (footprint {q(fp)}))")
    lines.append("  )")
    lines.append("  (nets")
    for code, (net, nodes) in enumerate(NETS.items(), 1):
        nodes_s = " ".join(f"(node (ref {q(n.split('.')[0])}) (pin {q(n.split('.')[1])}))" for n in nodes)
        lines.append(f"    (net (code {q(str(code))}) (name {q(net)}) {nodes_s})")
    lines.append("  )")
    lines.append(")")
    (OUT / "plane_tracker_carrier.net").write_text("\n".join(lines) + "\n", "utf-8")
    with open(OUT / "bom.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Ref", "Value", "Footprint", "Note"])
        for ref, (val, fp, note) in PARTS.items():
            w.writerow([ref, val, fp, note])
    print(f"wrote {OUT / 'plane_tracker_carrier.net'} ({len(PARTS)} parts, {len(NETS)} nets)")


if __name__ == "__main__":
    main()
