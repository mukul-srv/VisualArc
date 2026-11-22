// Short plain-language hints shown on hover (title) next to controls. One place so wording stays
// consistent and every parameter has one (tested).
export const HELP = {
  buildingType: "Residential or commercial. It decides the typical room height, roof, stair and slab values used wherever your drawing says nothing.",
  advancedUpload: "Heights, units for the drawing, and adding the model to a project. Empty fields use the defaults for the building type, and every default is reported as assumed.",
  conventions: "Which CAD layer means what (walls, floors, doors, columns...). The standard names work as they are; open this only when your drawing uses other names.",
  roles: "Viewer: can look. Editor: can add floors and change parameters. Only you (the owner) can share and delete.",
  link: "Anyone with the link can look at the model, read-only. Revoke it to stop that.",
  versions: "Every change makes a new version. Open one to look at it, or restore it to make it current again.",
  parameters: "Values used to build the model where the drawing is silent. Change one and every floor is rebuilt as a new version.",
  more: "Less common actions",
  account: "Your profile and log out",
  provenance: "Where a value comes from: read from your drawing, given by you, or assumed as a default.",
  walk: "Walk through the building with W A S D or the arrow keys; drag to look; E opens a nearby door.",
  roof: "Show or hide the roof to see inside.",
  topdown: "Look straight down at the plan.",
  measure: "Click two points to measure the distance between them.",
} as const;

export const PARAM_HELP: Record<string, string> = {
  wall_height: "How tall the walls are: the height of the rooms you see.",
  ceiling_height: "Height of the ceiling inside rooms. Only drawn in walk mode.",
  slab_thickness: "Thickness of the floor slab under the building (it sits below the floor level).",
  roof_type: "Flat, gable (two slopes) or hip (four slopes).",
  roof_pitch: "Slope of a gable or hip roof, in degrees.",
  stair_rise: "Height of one step. Sets how many steps a stair has.",
  stair_run: "Depth of one step. The drawn stair length is checked against it.",
  window_sill: "Height of the bottom of windows above the floor.",
  lintel_height: "Height of the top of door and window openings above the floor.",
  railing_height: "Height of balcony railings.",
};
