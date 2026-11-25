// Sun position (NOAA solar calculator algorithm, no refraction) and what it means for the viewer's sun.
const rad = (d: number) => (d * Math.PI) / 180;
const deg = (r: number) => (r * 180) / Math.PI;

/** Sun azimuth (degrees clockwise from true north) and elevation (degrees above the horizon) at a UTC instant. */
export function sunPosition(lat: number, lon: number, utcMs: number): { azimuth: number; elevation: number } {
  const T = (utcMs / 86400000 + 2440587.5 - 2451545) / 36525;
  const L0 = (280.46646 + T * (36000.76983 + 0.0003032 * T)) % 360;
  const M = rad(357.52911 + T * (35999.05029 - 0.0001537 * T));
  const e = 0.016708634 - T * (0.000042037 + 0.0000001267 * T);
  const C = Math.sin(M) * (1.914602 - T * (0.004817 + 0.000014 * T)) + Math.sin(2 * M) * (0.019993 - 0.000101 * T) + Math.sin(3 * M) * 0.000289;
  const omega = rad(125.04 - 1934.136 * T);
  const lambda = rad(L0 + C - 0.00569 - 0.00478 * Math.sin(omega));
  const eps = rad(23 + (26 + (21.448 - T * (46.815 + T * (0.00059 - T * 0.001813))) / 60) / 60 + 0.00256 * Math.cos(omega));
  const decl = Math.asin(Math.sin(eps) * Math.sin(lambda));
  const y = Math.tan(eps / 2) ** 2;
  const l0 = rad(L0);
  const eqTime = 4 * deg(y * Math.sin(2 * l0) - 2 * e * Math.sin(M) + 4 * e * y * Math.sin(M) * Math.cos(2 * l0) - 0.5 * y * y * Math.sin(4 * l0) - 1.25 * e * e * Math.sin(2 * M));
  const utcMin = (((utcMs / 60000) % 1440) + 1440) % 1440;
  const H = rad((utcMin + eqTime + 4 * lon) / 4 - 180);
  const phi = rad(lat);
  const sinEl = Math.sin(phi) * Math.sin(decl) + Math.cos(phi) * Math.cos(decl) * Math.cos(H);
  const azimuth = (deg(Math.atan2(Math.sin(H), Math.cos(H) * Math.sin(phi) - Math.tan(decl) * Math.cos(phi))) + 180 + 360) % 360;
  return { azimuth, elevation: deg(Math.asin(Math.max(-1, Math.min(1, sinEl)))) };
}

/** Unit vector from the scene origin towards the sun in viewer axes (X = plan x, Y up, Z = -plan y).
 *  `northDeg` is the clockwise angle from plan +Y to true north, so the sun's plan bearing is azimuth - northDeg. */
export function sunDirection(azimuth: number, elevation: number, northDeg: number): [number, number, number] {
  const b = rad(azimuth - northDeg);
  const el = rad(elevation);
  return [Math.sin(b) * Math.cos(el), Math.sin(el), -Math.cos(b) * Math.cos(el)];
}

/** Sun and sky strength (0..1) from the sun's elevation: the sun fades out over the first ~10 degrees and
 *  the sky never goes fully black. */
export function daylight(elevation: number): { sun: number; sky: number } {
  const t = Math.max(0, Math.min(1, elevation / 10));
  return { sun: t * t * (3 - 2 * t), sky: 0.15 + 0.85 * Math.max(0, Math.min(1, (elevation + 6) / 16)) };
}
