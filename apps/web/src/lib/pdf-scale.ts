export type PdfPage = {
  number: number;
  width_pt: number;
  height_pt: number;
  vector_objects: number;
  images: number;
  raster_only: boolean;
  groups: { layer: string; objects: number }[];
  scale_candidates: { ratio: number; source: "note" | "dimensions"; text: string; count: number }[];
};

export type PdfScaleForm = {
  page: number;
  mode: "ratio" | "two_points";
  ratio: string; // N of 1:N
  points: [string, string, string, string]; // x1 y1 x2 y2, PDF points
  distance: string; // mm
  confirmed: boolean;
};

export const EMPTY_PDF_FORM: PdfScaleForm = { page: 1, mode: "ratio", ratio: "", points: ["", "", "", ""], distance: "", confirmed: false };

export type PdfBody = {
  page: number;
  confirmed: true;
  scale: { kind: "ratio"; ratio: number } | { kind: "two_points"; p1: [number, number]; p2: [number, number]; distance_mm: number };
};

const num = (s: string) => (s.trim() === "" ? NaN : Number(s));

/** The scale is never applied unless the user ticked the confirmation; suggestions only fill the ratio field. */
export function buildPdfBody(f: PdfScaleForm): { ok: true; body: PdfBody } | { ok: false; errors: string[] } {
  const errors: string[] = [];
  if (!f.confirmed) errors.push("Confirm that the scale is correct.");
  let scale: PdfBody["scale"] | null = null;
  if (f.mode === "ratio") {
    const r = num(f.ratio);
    if (!(r > 0)) errors.push("Scale: enter the N of 1:N, a number above 0.");
    else scale = { kind: "ratio", ratio: r };
  } else {
    const [x1, y1, x2, y2] = f.points.map(num);
    const d = num(f.distance);
    if (![x1, y1, x2, y2].every(Number.isFinite)) errors.push("Two points: enter all four coordinates.");
    else if (x1 === x2 && y1 === y2) errors.push("Two points: the points must differ.");
    if (!(d > 0)) errors.push("Two points: enter the real distance in mm, above 0.");
    if (!errors.length) scale = { kind: "two_points", p1: [x1, y1], p2: [x2, y2], distance_mm: d };
  }
  return errors.length || !scale ? { ok: false, errors } : { ok: true, body: { page: f.page, confirmed: true, scale } };
}
