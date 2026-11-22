"""Layer-naming conventions as per-project config: a preset plus the user's mapping of other layers.

A preset fixes the layer names the engine recognises (`Settings` layer fields). The user's mapping
adds layers the preset does not know, each with one role; `ignore` is an explicit decision and is
still reported as an issue. A layer is mapped at most once: the mapping may not touch a layer the
preset already defines. Names are matched upper-case.

Sources (read this before trusting a preset):
- `aia`: the names the engine has used since MVP-0 (ADR-002 section 1): A-WALL, A-FLOR, A-DOOR,
  A-GLAZ, plus A-WALL-EXTR / A-WALL-INTR as wall-role layers. The first four follow the AIA CAD Layer
  Guidelines naming; the two role layers are a project extension, not AIA text. Not re-verified
  against the guideline document (paywalled).
- `iso13567`: a MINIMAL SUBSET. ISO 13567-2 builds a name from agent (2 chars) + element (6 chars) +
  presentation (2 chars), padded with `-`; the element field uses a national classification, so the
  codes differ per country. This subset uses the architect agent `A-`, presentation `E-` (element
  graphics) and the Uniclass 1.4 table G element codes as listed in the public ISO 13567 article
  (https://en.wikipedia.org/wiki/ISO_13567, "Architectural layers using Uniclass"): A-G25---E- walls,
  A-G251--E- external walls, A-G252--E- internal walls, A-G22---E- floors/slabs, A-G321--E- windows,
  A-G322--E- doors. The standard text itself is paywalled and was NOT checked, and optional suffix
  fields (status, sector, ...) are not matched: map such layers with Custom.
- `custom`: the AIA names stay recognised and the user maps every other layer.
"""

from dataclasses import dataclass, replace

from api.engine.adapters.dxf.split import strip_floor_prefix
from api.engine.settings import DEFAULTS, Settings

ROLES: tuple[str, ...] = ("wall", "wall_exterior", "wall_interior", "floor", "door", "window", "ignore")


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    source: str
    settings: Settings


PRESETS: dict[str, Preset] = {
    "aia": Preset("aia", "AIA (default)", "Engine MVP-0 names (ADR-002 section 1)", DEFAULTS),
    "iso13567": Preset(
        "iso13567",
        "ISO 13567 (minimal subset)",
        "Uniclass 1.4 element codes from the public ISO 13567 article; not checked against the standard text",
        replace(
            DEFAULTS,
            wall_layer="A-G25---E-",
            wall_role_layers=(("A-G251--E-", "exterior"), ("A-G252--E-", "interior")),
            floor_layer="A-G22---E-",
            door_layer="A-G322--E-",
            window_layer="A-G321--E-",
        ),
    ),
    "custom": Preset("custom", "Custom (AIA names + your mapping)", "AIA names; you map every other layer", DEFAULTS),
}


def known_roles(settings: Settings) -> dict[str, str]:
    """Layer (upper case) -> role for every layer the settings already recognise."""
    out = {l: "wall" for l in settings.wall_layers}
    out.update({l: f"wall_{r}" for l, r in settings.wall_role_layers})
    out.update({l: "floor" for l in settings.floor_layers})
    out.update({l: "door" for l in settings.door_layers})
    out.update({l: "window" for l in settings.window_layers})
    return out


def resolve(preset: str, mapping: dict[str, str] | None = None) -> Settings:
    """Settings for a preset plus the user's layer->role mapping. ValueError on a bad request."""
    if preset not in PRESETS:
        raise ValueError(f"unknown conventions preset {preset!r}; choose one of {sorted(PRESETS)}")
    base = PRESETS[preset].settings
    known = known_roles(base)
    extra: dict[str, list[str]] = {r: [] for r in ROLES}
    seen: dict[str, str] = {}  # normalised layer -> role
    for layer, role in (mapping or {}).items():
        # the reader matches names with the floor prefix stripped (L1|WALLS -> WALLS), upper case
        up = strip_floor_prefix(layer.strip(), base).upper()
        if not up:
            raise ValueError("layer names in the mapping must not be empty")
        if role not in ROLES:
            raise ValueError(f"unknown role {role!r} for layer {layer!r}; choose one of {list(ROLES)}")
        if up in known:
            raise ValueError(f"layer {layer!r} is already mapped by the {preset} preset ({known[up]})")
        if up in seen:  # the same layer on several floors may repeat, with one role
            if seen[up] != role:
                raise ValueError(f"layer {up!r} is mapped to both {seen[up]} and {role}")
            continue
        seen[up] = role
        extra[role].append(up)
    return replace(
        base,
        wall_extra=tuple(extra["wall"]),
        wall_role_layers=(
            *base.wall_role_layers,
            *((l, "exterior") for l in extra["wall_exterior"]),
            *((l, "interior") for l in extra["wall_interior"]),
        ),
        floor_extra=tuple(extra["floor"]),
        door_extra=tuple(extra["door"]),
        window_extra=tuple(extra["window"]),
        ignore_layers=tuple(extra["ignore"]),
    )


def layer_roles(preset: str, mapping: dict[str, str] | None, layers: list[str]) -> list[dict]:
    """Each layer with its role under preset + mapping (None = unmapped; the engine reports it)."""
    s = resolve(preset, mapping)
    roles = {**known_roles(s), **dict.fromkeys(s.ignore_layers, "ignore")}
    return [{"layer": l, "role": roles.get(strip_floor_prefix(l, s).upper())} for l in layers]
