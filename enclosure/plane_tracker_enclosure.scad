// Plane Tracker enclosure - 10.1" display + Raspberry Pi 4 + HC-SR505 PIR + KY-040 encoder
// Landscape, tilted-back stand. Wide LEFT bezel holds the PIR and the dial.
//
// !! Screen values below are PLACEHOLDERS for a typical 10.1" HDMI panel.
// !! Measure your PM-10.1inch-A1-V11 and edit the "SCREEN" section.
//
// Parts: set `part` to "front", "back", or "all" (preview). Print front face-down, back face-down.

part = "all";          // "front" | "back" | "all"

$fn = 64;
e = 0.01;

// ---------------- SCREEN (measure these!) ----------------
scr_w   = 235.0;   // panel glass+frame width  (X)
scr_h   = 143.0;   // panel height             (Y)
scr_t   = 6.0;     // panel thickness incl. frame
bez_l = 6; bez_r = 8; bez_t = 10; bez_b = 10;  // panel's own borders
view_w  = scr_w - bez_l - bez_r;   // visible/active area width
view_h  = scr_h - bez_t - bez_b;   // visible/active area height
view_dx = (bez_r - bez_l)/2;  // visible area offset from panel centre; sign is flipped because the whole model is mirrored in X below
view_dy = 0;       // (Y, +up). Many panels sit lower: adjust.
conn_depth = 12;

// ---------------- LEFT BEZEL (sensor + dial) ----------------
left_bezel = 38;   // extra width on the left for controls
pir_dia    = 10.5; // HC-SR505 dome hole (dome ~10 mm)
pir_board  = [10, 23, 12]; // PCB footprint (w,h) + depth behind face
enc_shaft  = 7.2;  // KY-040 shaft thread hole (M7 bushing)
pir_pocket = 3.6;  // total extra width/height of the PIR pocket over the board (1.5 mm per side + clr)
enc_pcb    = [26, 19];
enc_extra  = 3;    // extra recess length toward the bottom edge // KY-040 PCB w,h
enc_shaft_off = 6; // shaft centre from PCB edge

// ---------------- SHELL ----------------
wall      = 3.0;
bezel     = 10;    // top/right/bottom border around the visible area
face_t    = 3.0;   // front plate thickness
clr       = 0.6;   // fit clearance
depth     = 38;    // inner depth behind the front plate (Pi 4 ~17mm + screen conn + cables)
corner_r  = 6;
tilt      = 70;    // degrees from horizontal for the back-leg stand (screen leans back)

// ---------------- RASPBERRY PI 4 ----------------
pi_w = 85; pi_h = 56;
pi_holes = [[3.5,3.5],[61.5,3.5],[3.5,52.5],[61.5,52.5]]; // 58 x 49 pattern
standoff_h = 5; standoff_d = 6; pi_screw_d = 2.6;

// DC005 (5.5x2.1 mm) barrel jack: body ~9 x 11 mm; the jack is pushed in from inside and
// hot-glued, so the rear-plate hole is the body cross-section plus ~1 mm clearance.
dc_hole = [10, 12];     // [x, y] opening in the rear plate
dc_off  = [11.2, -22];  // jack centre relative to the Pi origin (x along the Pi, y below it)

// ---------------- derived ----------------
// `rim` = solid plastic around the panel on the top, bottom and screen-side edges, so the
// screw posts sit OUTSIDE the panel footprint and the front has material to screw into.
rim    = 8;
post_d = 7;
out_w = scr_w + left_bezel + 2*wall + 2*clr + rim;
out_h = scr_h + 2*wall + 2*clr + 2*rim;
// Panel centre in the front plate (left bezel on one side, rim on the other)
pan_cx = (left_bezel - rim)/2;
// Screw posts: 4 corners + 2 on top/bottom clear of the vent slots
post_o = wall + post_d/2;
posts = concat(
    [for (sx=[-1,1], sy=[-1,1]) [sx*(out_w/2 - post_o), sy*(out_h/2 - post_o)]],
    [for (sy=[-1,1]) [pan_cx + 70, sy*(out_h/2 - post_o)]]);
// Left control column centre
ctl_cx = -out_w/2 + wall + left_bezel/2 - 0;
// Pi board origin (its corner nearest the USB-C port) inside the back shell
// Pi sits at the far (screen-side) end, 8 mm in from the wall, so there is a big open area
// between it and the PIR/encoder column for slack in the sensor wiring.
pi_x0 = out_w/2 - wall - 8 - pi_w;
pi_y0 = -pi_h/2;
pir_y = 46;
enc_y = 22;

module rrect(w, h, r, t) {
    linear_extrude(t) offset(r) square([w-2*r, h-2*r], center=true);
}

// ---------- FRONT: bezel plate with window, panel pocket, controls ----------
module front() {
    difference() {
        union() {
            rrect(out_w, out_h, corner_r, face_t + scr_t + clr);
        }
        // panel pocket (from the back side, z = face_t upwards)
        translate([pan_cx, 0, face_t])
            rrect(scr_w + 2*clr, scr_h + 2*clr, 1.5, scr_t + clr + e);
        // visible window
        translate([pan_cx + view_dx, view_dy, -e])
            linear_extrude(face_t + 2*e) square([view_w, view_h], center=true);
        // PIR hole (upper left column)
        translate([ctl_cx, pir_y, -e]) cylinder(d=pir_dia, h=face_t+2*e);
        // encoder shaft hole (lower left column)
        translate([ctl_cx, enc_y, -e]) cylinder(d=enc_shaft, h=face_t+2*e);
        // knob recess ring (cosmetic)
        translate([ctl_cx, enc_y, -e]) cylinder(d=enc_shaft+2, h=0.4);
        // blind M3 pilot holes for the rear screws (do not reach the face plate)
        for (q = posts)
            translate([q[0], q[1], face_t + 1])
                cylinder(d=2.8, h=scr_t + clr);
        // PCB pockets: open to the rear so the boards drop in from behind.
        // PIR: dome pokes through the hole, board sits flat against the plate underside.
        translate([ctl_cx, pir_y, face_t])
            translate([-(pir_board[0]+pir_pocket)/2, -(pir_board[1]+pir_pocket)/2, 0])
                cube([pir_board[0]+pir_pocket, pir_board[1]+pir_pocket, scr_t + clr + 1]);
        // Encoder: encoder body sits against the plate underside and is clamped by the
        // bushing nut on the front; the PCB hangs behind it.
        // The recess runs through to the panel pocket (no wall) for wire clearance, and is
        // enc_extra mm longer toward the bottom edge so the full PCB fits.
        enc_x0 = ctl_cx - (enc_pcb[0] + clr)/2;
        enc_x1 = pan_cx - (scr_w + 2*clr)/2 + 1;   // overlaps the panel pocket edge
        translate([enc_x0, enc_y - (enc_pcb[1] + clr)/2 - enc_extra, face_t])
            cube([enc_x1 - enc_x0, enc_pcb[1] + clr + enc_extra, scr_t + clr + 1]);
    }
}

// ---------- BACK: walls, Pi standoffs, vents, ports, stand ----------
module back_body() {
    h = depth;
    difference() {
        rrect(out_w, out_h, corner_r, h);
        translate([0, 0, wall]) rrect(out_w-2*wall, out_h-2*wall, corner_r-wall/2, h);
        // vents: slots through the top, bottom and both side walls (z span clears the screw posts)
        for (i = [-4:4]) for (sy = [-1,1])
            translate([pan_cx + i*14, sy*(out_h/2 - wall/2), h/2 + 4])
                cube([8, wall*2, h-18], center=true);
        for (i = [-3:3]) for (sx = [-1,1])
            translate([sx*(out_w/2 - wall/2), i*14, h/2 + 4])
                cube([wall*2, 8, h-18], center=true);
        // DC power jack hole through the rear plate
        translate([pi_x0 + dc_off[0] - dc_hole[0]/2, pi_y0 + dc_off[1] - dc_hole[1]/2, -e])
            cube([dc_hole[0], dc_hole[1], wall + 2*e]);
    }
    // Pi standoffs, board sits to the right of the left bezel region
    translate([pi_x0, pi_y0, wall])
        for (p = pi_holes)
            translate([p[0], p[1], 0]) difference() {
                cylinder(d=standoff_d, h=standoff_h);
                translate([0,0,1]) cylinder(d=pi_screw_d, h=standoff_h);
            }
    // screw posts: screws go in from the rear (countersunk in the rear plate) and bite into
    // blind pilot holes in the front, so nothing shows on the front face. Use ~M3x45 flat-head.
    for (q = posts)
        translate([q[0], q[1], wall])
            cylinder(d=post_d, h=h-wall);
    // No hold-down tabs: the panel is fixed to the front bezel with VHB tape.
}

// Back piece with the screw holes cut through post AND rear plate (done after the union,
// otherwise the plate stays solid under each post).
module back_shell() {
    difference() {
        back_body();
        for (q = posts) translate([q[0], q[1], 0]) {
            translate([0,0,-e]) cylinder(d=3.4, h=depth + 1);             // M3 clearance
            translate([0,0,-e]) cylinder(d1=6.4, d2=3.4, h=1.7 + e);      // countersink, rear face
        }
    }
}

// Stand leg: hinged-free fixed prop that hangs off the back plate
module stand() {
    leg_h = 120;
    translate([out_w/4, -out_h/2 + 20, depth])
        rotate([-(90 - tilt), 0, 0])
            difference() {
                translate([-20, 0, 0]) cube([40, 6, leg_h]);
                translate([-10, -e, 20]) cube([20, 6+2*e, leg_h-40]);
            }
}

// ---------- assembly ----------
// Controls + connectors are on the RIGHT of the front. The modules above are modelled with the
// wide bezel on the left, so the whole model is mirrored in X here.
mirror([1,0,0]) {
    if (part == "front") front();
    else if (part == "back") { back_shell(); }
    else if (part == "stand") { rotate([90,0,0]) stand(); }
    else {
        color("gainsboro") front();
        translate([0, 0, face_t + scr_t + clr + depth + 20]) mirror([0,0,1]) { color("slategray") back_shell(); }
    }
}
