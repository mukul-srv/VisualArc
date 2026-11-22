"""Project parameters: name -> unit. The value comes from the user (`user_provided`) or from the
building-type preset (`defaulted`, same attribute name on `BuildingPreset`). One list, used by the
reader (canonical `Project.parameters`) and the API (GET/PATCH), so they cannot drift."""

PARAMS: dict[str, str] = {
    "wall_height": "mm",
    "ceiling_height": "mm",
    "slab_thickness": "mm",
    "roof_type": "none",  # "flat" | "gable" | "hip"
    "roof_pitch": "deg",
    "stair_rise": "mm",
    "stair_run": "mm",
    "window_sill": "mm",
    "lintel_height": "mm",
    "railing_height": "mm",
}
ROOF_TYPES = ("flat", "gable", "hip")
