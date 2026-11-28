import { HELP } from "../lib/help";
import { HelpLine, useHelp } from "./HelpLine";

type Props = {
  walking: boolean;
  walkBlocked?: string | null; // why Walk cannot work for this model (it is then disabled)
  top: boolean;
  measuring: boolean;
  roofPresent: boolean;
  roofOn: boolean;
  onWalk: () => void;
  onRoof: () => void;
  onTop: () => void;
  onMeasure: () => void;
  /** OBJ and IFC download links (absent for local /models files, which have no API model). */
  exports?: { obj: string; ifc: string } | null;
};

/** The viewer's essentials are always visible: walk and roof (when the model has one). The less
 *  common tools (top-down plan, measuring) sit under More. Labels never change; the pressed state is
 *  aria-pressed. What a tool does is shown as text on hover and on keyboard focus. */
export function ViewerToolbar(p: Props) {
  const { help, about } = useHelp();
  return (
    <div>
      <div role="toolbar" aria-label="Viewer tools" style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        <button onClick={p.onWalk} aria-pressed={p.walking} disabled={!!p.walkBlocked} {...about(HELP.walk)}>Walk</button>
        {p.roofPresent && (
          <button onClick={p.onRoof} aria-pressed={p.roofOn} {...about(HELP.roof)}>Roof</button>
        )}
        <details>
          <summary style={{ cursor: "pointer" }} {...about(HELP.more)}>More</summary>
          <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
            <button disabled={p.walking} onClick={p.onTop} aria-pressed={p.top} {...about(HELP.topdown)}>Top-down</button>
            <button disabled={p.walking} onClick={p.onMeasure} aria-pressed={p.measuring} {...about(HELP.measure)}>Measure</button>
            {p.exports && <a href={p.exports.obj} download {...about(HELP.exportObj)}>Export OBJ</a>}
            {p.exports && <a href={p.exports.ifc} download {...about(HELP.exportIfc)}>Export IFC</a>}
          </div>
        </details>
      </div>
      <HelpLine text={help} />
      <small role="note">{p.walkBlocked ?? "Drag to look around. Walk: use W A S D to move."}</small>
    </div>
  );
}
