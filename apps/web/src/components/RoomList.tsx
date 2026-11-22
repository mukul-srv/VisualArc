import { m2, PROVENANCE_LABEL, type RoomData } from "../lib/selection";

// Rooms of the shown floor with areas (to the inner wall faces); click one for its details.
export function RoomList({ rooms, onSelect }: { rooms: RoomData[]; onSelect: (r: RoomData) => void }) {
  if (!rooms.length) return null;
  return (
    <section aria-label="Rooms" style={{ marginBottom: 8 }}>
      <b>Rooms ({rooms.length})</b>
      <ul style={{ margin: 0, paddingLeft: 18 }}>
        {rooms.map((r) => (
          <li key={r.id}>
            <button type="button" onClick={() => onSelect(r)}>{r.name}</button> {m2(r.area)}
            {r.name_source === "defaulted" && <small> [{PROVENANCE_LABEL.defaulted}]</small>}
          </li>
        ))}
      </ul>
    </section>
  );
}
