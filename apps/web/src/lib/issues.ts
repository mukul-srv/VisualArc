import type { Issue } from "./api";
import { refs } from "./selection";

// Presentation only: issues are grouped, ordered and explained for reading. Nothing is dropped or
// changed; every group keeps all its issues and the counts are the issue counts.
export type Level = "error" | "warning" | "info";
export const LEVEL_LABEL: Record<Level, string> = { error: "Error", warning: "Warning", info: "Info" };

type Entry = { title: string; help: string; info?: true };

// What each engine code means in plain language and what to do about it. `info` = a value the
// engine assumed or a note about the input, not a defect (still counted and listed).
const CATALOG: Record<string, Entry> = {
  ambiguous_pairing: { title: "Wall line has partners at different distances", help: "A wall line pairs with more than one parallel line. Check the wall lines are drawn once, as clean pairs." },
  ceiling_above_walls: { title: "Ceiling is higher than the walls", help: "There would be a gap above the walls. Check the ceiling and wall heights." },
  ceiling_height_defaulted: { title: "Ceiling height assumed", help: "The drawing gives none, so the preset value was used. Enter your own to replace it.", info: true },
  ceiling_height_missing: { title: "Ceiling height needed", help: "Enter the ceiling height in the form before generating." },
  ceiling_not_built: { title: "No ceiling built", help: "A ceiling height was given but there is no floor boundary to build it from." },
  balcony_detached: { title: "Balcony not attached to a wall", help: "A balcony outline touches no wall. It was built as drawn; check the outline and its layer." },
  balcony_overlaps_room: { title: "Balcony overlaps a room", help: "A balcony outline lies over a room, so it is not outside the walls. It was built as drawn; check the layer." },
  content_not_reconstructed: { title: "Content not modelled", help: "Parts of the drawing (for example roofs, title blocks or floors you excluded) are outside what is reconstructed. Nothing was lost from the file." },
  degenerate_segment: { title: "Zero-length lines", help: "Some lines have no length and were skipped. Clean them up in the drawing." },
  door_swing_ambiguous: { title: "Door with several swing arcs", help: "More than one swing arc is centred on this door's corners, so the swing was not guessed. Keep one arc per door." },
  door_swing_not_found: { title: "Door swing not found", help: "No swing arc on the door layer is centred on a corner of these door markers, so swing and hinge are left unset. Draw the arc centred on the hinge corner.", info: true },
  elevation_defaulted: { title: "Floor elevation assumed", help: "No elevation was given, so one was derived. Enter the real elevation if you know it.", info: true },
  floor_split_unconfirmed: { title: "Floors need confirming", help: "This drawing holds several floors. Confirm which to build, with names and elevations." },
  gap_closed_by_jamb_pair: { title: "Ambiguous door or window gap", help: "Jamb lines close a gap, so it is unclear whether it is a solid wall or an opening. Mark an opening or remove the jambs." },
  invalid_balcony: { title: "Unusable balcony outline", help: "A balcony outline is not a closed, valid polygon, so no balcony was built from it." },
  invalid_column: { title: "Unusable column", help: "Columns must be a closed axis-aligned rectangle (4 vertices) or a circle. This one was not built." },
  invalid_floor_boundary: { title: "Unusable floor outline", help: "A floor outline is not a valid closed shape. Fix it in the drawing." },
  invalid_opening_marker: { title: "Invalid door or window marker", help: "A marker must be a closed 4-corner rectangle with straight edges, filling the wall gap." },
  layer_ignored_by_user: { title: "Layers you chose to ignore", help: "These layers were not read because you mapped them to ignore.", info: true },
  lintel_below_sill: { title: "Lintel height not above the sill", help: "The lintel height you gave is not above the window sill, so window heights were not derived from it." },
  multiple_opening_markers: { title: "Several markers in one gap", help: "One wall gap takes one opening marker. Delete the extras." },
  no_walls: { title: "No walls found", help: "No paired wall lines were recognised. Check the layer names (map your layers under Layer conventions) and that walls are drawn as parallel line pairs." },
  non_orthogonal_segment: { title: "Slanted wall lines", help: "Only horizontal and vertical walls are supported, so slanted lines were not read." },
  open_floor_boundary: { title: "Floor outline not closed", help: "A floor outline is open. Close the polyline." },
  opening_dimension_defaulted: { title: "Door and window sizes assumed", help: "No height or sill was given for these, so preset values were used.", info: true },
  opening_exceeds_wall_height: { title: "Opening taller than its wall", help: "A door or window is higher than the wall it sits in. Check the heights." },
  opening_host_mismatch: { title: "Opening between mismatched walls", help: "The walls on either side differ in thickness or position. Align them in the drawing." },
  opening_marker_mismatch: { title: "Marker does not fill its gap", help: "A door or window marker must fill the wall gap exactly (no snapping)." },
  opening_marker_outside_wall: { title: "Marker not on a wall", help: "A door or window marker overlaps no wall or gap. Move it onto the wall gap." },
  opening_marker_without_gap: { title: "Marker over solid wall", help: "Break the wall lines so the marker exactly fills a gap." },
  opening_spans_multiple_gaps: { title: "Marker covers several gaps", help: "One marker must fill exactly one wall gap." },
  opening_symbol_ignored: { title: "Door and window symbols skipped", help: "Swings, leaves, glass lines and tags on opening layers are never geometry, so they were skipped.", info: true },
  orphan_door_swing: { title: "Door swing without a marker", help: "A door swing arc is not on any door marker. There may be an unmarked door." },
  opening_detail_skipped: { title: "Opening too small for a frame", help: "These openings are too small for a frame around a door leaf or glass, so they are plain holes." },
  no_closed_rooms: { title: "No closed rooms", help: "The walls enclose no region, so no rooms were built. Check that wall outlines close." },
  overlapping_wall_lines: { title: "Duplicate wall lines", help: "Two lines lie on top of each other. Remove the duplicate." },
  partial_wall_gap: { title: "Wall gap broken on one side only", help: "One face of a wall continues across a gap while the other is broken. Break both or neither." },
  room_outline_open: { title: "Wall outline not closed", help: "Some wall ends are not joined to another wall, so no room closes through them. Join the walls in the drawing." },
  room_region_unusable: { title: "Room region not usable", help: "A closed region could not be turned into one room because of free-standing wall pieces inside it." },
  rooms_not_built: { title: "Rooms not built", help: "There are no walls, so text labels were not used as room names." },
  railing_height_defaulted: { title: "Railing height assumed", help: "The drawing gives none, so the preset value was used. Set it under Parameters.", info: true },
  railing_height_missing: { title: "No railing height", help: "Choose a building type or set the railing height so balcony railings can be built." },
  room_has_obstruction: { title: "Free-standing wall inside a room", help: "A wall piece not joined to the room's walls stands inside it; its area is excluded from the room." },
  room_label_unplaced: { title: "Text outside any closed room", help: "These text labels lie in no closed room: the room outline may be open, or the text is outside the walls. The text is not used as a name." },
  room_name_ambiguous: { title: "Several labels in one room", help: "The first label in reading order (top to bottom, left to right) was used as the name. Remove the extras or map their layer to ignore." },
  room_name_defaulted: { title: "Room names assumed", help: "No text label was found inside these rooms, so numbered names were used. Add a TEXT or MTEXT label inside the room.", info: true },
  unexplained_region: { title: "Enclosed area left empty", help: "An area enclosed by wall lines is neither a wall nor a junction, so it was left empty." },
  units_conflict: { title: "Units conflict", help: "The units you gave contradict the drawing's header. Fix the drawing or drop the units." },
  units_missing: { title: "Units needed", help: "The drawing has no units. Choose them in the form." },
  units_unsupported: { title: "Unsupported drawing units", help: "The drawing uses units that are not supported (mm, cm, m, in, ft). Re-export it in a supported unit." },
  units_user_provided: { title: "Units taken from you", help: "The drawing has no units, so the ones you chose were used.", info: true },
  unmapped_layer: { title: "Layers not mapped", help: "These layers are not read. Map them under Layer conventions if they hold walls, floors, doors or windows." },
  unmarked_wall_gap: { title: "Wall gaps without a marker", help: "A gap has no door or window marker, so it was left as a full-height void." },
  unpaired_segment: { title: "Wall lines without a partner", help: "These lines have no parallel partner at a wall thickness, so they were not made into walls." },
  unsupported_arc: { title: "Curved wall segments", help: "Curved segments are not supported and were skipped." },
  unsupported_entity: { title: "Unsupported drawing objects", help: "These object types are not read in this version and were skipped." },
  unsupported_extrusion: { title: "Objects drawn on a tilted plane", help: "These objects are not parallel to the plan and cannot be placed, so they were skipped." },
  unsupported_opening_block: { title: "Door or window blocks", help: "Block inserts are not read. Draw a closed rectangle marker filling the wall gap instead." },
  wall_height_defaulted: { title: "Wall height assumed", help: "The drawing gives none, so the preset value was used. Enter your own to replace it.", info: true },
  wall_height_missing: { title: "Wall height needed", help: "Enter the wall height in the form before generating." },
  wall_role_conflict: { title: "Wall on conflicting role layers", help: "A wall is drawn on both the exterior and interior layers. Fix it in the drawing." },
  wall_role_inferred: { title: "Wall roles inferred", help: "No role layer was found, so exterior/interior was worked out from the geometry. Use role layers to be exact.", info: true },
};

const humanize = (code: string) => {
  const t = code.replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
};

export const levelOf = (i: Issue): Level =>
  i.severity === "blocking" ? "error" : CATALOG[i.code]?.info || i.code.endsWith("_defaulted") ? "info" : "warning";

/** `info` groups are still engine *warnings* (severity is never changed); `tag` says why they are quieter. */
export type IssueGroup = { code: string; title: string; help: string; level: Level; issues: Issue[]; tag?: string };

const ORDER: Record<Level, number> = { error: 0, warning: 1, info: 2 };

/** Group by code, most severe first, then largest, then title. Every issue lands in exactly one group. */
export function groupIssues(issues: Issue[]): IssueGroup[] {
  const by = new Map<string, IssueGroup>();
  for (const i of issues) {
    const level = levelOf(i);
    const key = `${level}:${i.code}`; // one code never mixes levels
    let g = by.get(key);
    if (!g) {
      const e = CATALOG[i.code];
      g = {
        code: i.code,
        title: e?.title ?? humanize(i.code),
        help: e?.help ?? "See the details below.",
        level,
        issues: [],
        ...(i.code.endsWith("_defaulted") ? { tag: "assumed default" } : {}),
      };
      by.set(key, g);
    }
    g.issues.push(i);
  }
  return [...by.values()].sort(
    (a, b) => ORDER[a.level] - ORDER[b.level] || b.issues.length - a.issues.length || a.title.localeCompare(b.title),
  );
}

export type Summary = { error: number; warning: number; info: number; total: number };
export function summarize(issues: Issue[]): Summary {
  const s = { error: 0, warning: 0, info: 0, total: issues.length };
  for (const i of issues) s[levelOf(i)]++;
  return s;
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
/** "2 errors, 14 warnings, 5 info"; zero counts are left out. */
export function summaryLine(s: Summary): string {
  const parts = [
    s.error && plural(s.error, "error"),
    s.warning && plural(s.warning, "warning"),
    s.info && `${s.info} info`,
  ].filter(Boolean);
  return parts.join(", ");
}

/** Where an issue points, as layer:handle strings (never dropped; the UI folds the list away). */
export const locations = (i: Issue): string[] => refs(i.sources);
