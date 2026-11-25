"use client";

import { useState } from "react";
import { buildPdfBody, EMPTY_PDF_FORM, type PdfBody, type PdfPage, type PdfScaleForm } from "@/lib/pdf-scale";

type Props = { pages: PdfPage[]; busy: boolean; onConvert: (body: PdfBody) => void };

/** A PDF has no units: the user picks the page and confirms a scale. Suggestions (from a note or the
 *  dimension text) only fill the field; nothing is converted until the confirmation box is ticked. */
export function PdfScalePanel({ pages, busy, onConvert }: Props) {
  const usable = pages.filter((p) => !p.raster_only);
  const [f, setF] = useState<PdfScaleForm>({ ...EMPTY_PDF_FORM, page: usable[0]?.number ?? 1 });
  const [errors, setErrors] = useState<string[]>([]);
  const page = pages.find((p) => p.number === f.page);
  const set = (patch: Partial<PdfScaleForm>) => setF({ ...f, ...patch });
  const submit = () => {
    const r = buildPdfBody(f);
    setErrors(r.ok ? [] : r.errors);
    if (r.ok) onConvert(r.body);
  };
  return (
    <section aria-label="PDF scale">
      <h2>PDF scale</h2>
      <p>A PDF has no real-world units. Choose the page and confirm the scale of the drawing; the model is only as accurate as this scale.</p>
      {pages.length > 1 && (
        <label>
          Page{" "}
          <select value={f.page} disabled={busy} onChange={(e) => set({ page: Number(e.target.value), ratio: "" })}>
            {pages.map((p) => (
              <option key={p.number} value={p.number} disabled={p.raster_only}>
                {p.number}: {p.raster_only ? "scanned image (not supported yet)" : `${p.vector_objects} vector objects`}
              </option>
            ))}
          </select>
        </label>
      )}
      {page && page.groups.length > 0 && (
        <p><small>Line groups on this page (by colour and width; you map them to walls, floors and so on next): {page.groups.map((g) => `${g.layer} (${g.objects})`).join(", ")}</small></p>
      )}
      {page && page.images > 0 && <p role="note"><small>{page.images} image(s) on this page are not reconstructed.</small></p>}
      {page && page.scale_candidates.length === 0 && <p>No scale was found in this page. Enter the scale, or two points a known distance apart.</p>}
      {page?.scale_candidates.map((c) => (
        <p key={`${c.source}-${c.ratio}`}>
          Suggested 1:{Number(c.ratio.toFixed(2))} (
          {c.source === "note" ? `from the note "${c.text}"` : `from ${c.count} dimensions: ${c.text}`}){" "}
          <button type="button" disabled={busy} onClick={() => set({ mode: "ratio", ratio: String(Number(c.ratio.toFixed(2))) })}>Use this</button>
        </p>
      ))}
      <fieldset disabled={busy}>
        <legend>Scale</legend>
        <label><input type="radio" checked={f.mode === "ratio"} onChange={() => set({ mode: "ratio" })} /> Ratio 1:</label>{" "}
        <input aria-label="Scale ratio N of 1:N" inputMode="decimal" size={6} value={f.ratio} onChange={(e) => set({ mode: "ratio", ratio: e.target.value })} />
        <br />
        <label><input type="radio" checked={f.mode === "two_points"} onChange={() => set({ mode: "two_points" })} /> Two points a known distance apart (PDF points, origin bottom-left)</label>
        {f.mode === "two_points" && (
          <div>
            {(["x1", "y1", "x2", "y2"] as const).map((n, i) => (
              <input key={n} aria-label={n} placeholder={n} size={6} value={f.points[i]} onChange={(e) => set({ points: f.points.map((v, j) => (j === i ? e.target.value : v)) as PdfScaleForm["points"] })} />
            ))}{" "}
            <input aria-label="Real distance in mm" placeholder="distance, mm" size={10} value={f.distance} onChange={(e) => set({ distance: e.target.value })} />
          </div>
        )}
      </fieldset>
      <label>
        <input type="checkbox" checked={f.confirmed} onChange={(e) => set({ confirmed: e.target.checked })} /> I confirm this scale is correct
      </label>
      {errors.map((e) => <p key={e} role="alert" style={{ color: "#b00020" }}>{e}</p>)}
      <p><button type="button" disabled={busy} onClick={submit}>Convert page {f.page}</button></p>
    </section>
  );
}
