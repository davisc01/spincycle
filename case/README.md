# case/

3D-printed enclosure files for the car-stereo-style Spin Cycle housing go here
(STL, STEP, F3D/CAD source, whatever your tool of choice exports). Empty
for now -- fill in as the design comes together.

## Things to account for in the design

**Front panel (the "face" of the stereo):**
- 16x2 LCD cutout -- get exact bezel dimensions from the LCD you actually
  buy; sizes vary a bit between suppliers even for "16x2 HD44780." Leave
  clearance for the LCD's mounting holes/standoffs, not just the visible
  glass.
- Two round holes for the rotary encoder shafts, sized for a 6mm D-shaft
  (confirm against the actual encoders once they arrive -- some are
  metric, some aren't quite). Each needs enough flat clearance behind the
  panel for the encoder body plus the threaded bushing/nut/washer that
  panel-mounts it.

**Interior volume -- what has to physically fit inside:**
- Raspberry Pi 4 board (85 x 56mm footprint, plus mounting hole positions
  for M2.5 standoffs)
- Perfboard with the soldered LCD + encoder wiring
- Cable routing/slack for jumper or hookup wire runs from the perfboard to
  the Pi's GPIO header
- Ventilation for the Pi -- it can run warm under sustained mpv decode
  load, don't fully seal the case

**External access (ports that need to reach the case exterior):**
- HDMI out (to the TV)
- USB port(s) for the external SSD -- decide whether the SSD sits outside
  the case on its own cable, or gets mounted inside with just a short USB
  jumper to an external port
- Power in (USB-C for the Pi)
- Maybe a physical power switch, if you want one beyond just pulling the plug

## Once real dimensions exist

Drop the exported files here and note in this README which file is the
current/final version if there end up being multiple iterations.
