// Airplane knob for the KY-040 rotary encoder (6 mm D-shaft).
// Print upside-down? No: print as-is, flat base down, plane on top (no supports needed).
// If the fit is loose/tight, adjust `fit` (0.1 = snug press fit on most printers).

$fn = 64;
e = 0.01;

shaft_d    = 6.0;   // KY-040 shaft diameter
shaft_flat = 4.6;   // across-flats distance of the D (flat to opposite side)
shaft_len  = 8;     // exposed shaft above the bushing (per listing)
bush_d     = 7.0;   // threaded bushing diameter (M7)
bush_h     = 3.0;   // bushing protrusion above the front face (~6 mm bushing - 3 mm face plate; MEASURE)
gap        = 0.6;   // knob underside to front face (keep > 0 so it spins freely)
bore_clr   = 1.2;   // extra diameter on the bushing bore
fit        = 0.35;  // added clearance on the socket (was 0.1: too tight)

knob_d   = 15;      // grip body diameter
knob_h   = 12;      // grip body height (measured from its underside, which sits `gap` above the face)
ribs     = 16;      // knurl count
rib_d    = 1.2;     // knurl groove diameter
plane_h  = 2.0;     // raised airplane height above the top face
plane_scale = 0.5;  // silhouette is drawn ~24 mm wide; scaled to fit the knob
nose_ang = 0;       // rotate the plane so the nose points where you want at "12 o'clock"

// Airplane silhouette, top view, nose toward +Y, fits in ~24 x 24 mm.
module plane_2d() {
    half = [[0,12.5],[1.6,10.5],[2.3,6],[2.3,4],[12,-3],[12,-6],[2.3,-3],
            [2.0,-8],[5.5,-10.5],[5.5,-12.5],[0,-11.5]];
    offset(r=0.8) offset(delta=-0.8)
    polygon(concat(half, [for (i = [len(half)-1:-1:0]) [-half[i][0], half[i][1]]]));
}

// Underside bore swallows the bushing so the knob sits nearly flush on the front face.
bore_h = bush_h - gap + 0.4;
module bushing_bore() { cylinder(d=bush_d + bore_clr, h=bore_h); }

module d_socket() {
    d = shaft_d + fit;
    f = shaft_flat + fit;
    intersection() {
        cylinder(d=d, h=shaft_len + 0.3);
        translate([-d/2 - e, -d/2 - e, 0]) cube([d + 2*e, f + e, shaft_len + 0.3]);
    }
}

difference() {
    union() {
        // grip body with a soft top edge
        difference() {
            cylinder(d=knob_d, h=knob_h);
            for (i = [0:ribs-1]) rotate(i*360/ribs)
                translate([knob_d/2, 0, -e]) cylinder(d=rib_d, h=knob_h + 2*e, $fn=16);
        }
        // raised airplane
        translate([0, 0, knob_h - e]) rotate(nose_ang)
            linear_extrude(plane_h + e) scale(plane_scale) plane_2d();
    }
    translate([0, 0, -e]) bushing_bore();
    translate([0, 0, bore_h - e]) d_socket();
}
