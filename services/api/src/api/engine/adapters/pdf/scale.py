"""Scale suggestions for a PDF page. These are only SUGGESTIONS shown to the user: the conversion always
needs the user's explicit confirmation of a scale (a ratio, or a known distance between two points).

Sources: a "1:100" / "SCALE 1/100" / 1/4" = 1'-0" note, and dimension text (a number of mm drawn next to a
segment of that length) when at least `MIN_DIM_AGREE` of them imply the same scale.
"""

import math
import re
from dataclasses import asdict, dataclass

MM_PER_PT_AT_1 = 25.4 / 72
COMMON_RATIOS = {1, 2, 5, 10, 20, 25, 50, 75, 100, 125, 150, 200, 250, 500, 1000}
MIN_DIM_AGREE = 3
DIM_AGREE_TOL = 0.02  # implied scales within 2 % agree
DIM_NEAR_PT = 40.0  # a dimension text belongs to a segment whose midpoint is this close
DIM_MIN_SEGMENT_PT = 20.0

_RATIO = re.compile(r"(?<![\d.])1\s*[:/]\s*(\d{1,5})(?![\d.])")
_IMPERIAL = re.compile(r"""(\d+)\s*/\s*(\d+)\s*(?:"|in)\s*=\s*1\s*(?:'|ft)""", re.IGNORECASE)


@dataclass(frozen=True)
class ScaleCandidate:
    ratio: float  # real size / paper size (100 = 1:100)
    source: str  # "note" | "dimensions"
    text: str  # what it was read from
    count: int = 1  # dimension candidates: how many dimensions agree

    @property
    def mm_per_pt(self) -> float:
        return self.ratio * MM_PER_PT_AT_1

    def to_dict(self) -> dict:
        return {**asdict(self), "mm_per_pt": self.mm_per_pt}


def _notes(texts: list[dict]) -> list[ScaleCandidate]:
    out = []
    for t in texts:
        s = t["text"]
        if m := _IMPERIAL.search(s):
            num, den = int(m[1]), int(m[2])
            if num and den:
                out.append(ScaleCandidate(12 * den / num, "note", s))  # 1/4" = 1'-0": 48
            continue
        keyword = re.search(r"scale|sc\.|maßstab|echelle|escala", s, re.IGNORECASE) is not None
        for m in _RATIO.finditer(s):
            n = int(m[1])
            if n > 0 and (keyword or n in COMMON_RATIOS):
                out.append(ScaleCandidate(float(n), "note", s))
    return out


def _dimensions(texts: list[dict], segments) -> ScaleCandidate | None:
    """Plain integers of 3-5 digits read as mm, matched to the nearest long segment's midpoint."""
    implied = []
    for t in texts:
        if not re.fullmatch(r"\d{3,5}", t["text"]):
            continue
        value = float(t["text"])
        best = None
        for (a, b) in segments:
            length = math.dist(a, b)
            if length < DIM_MIN_SEGMENT_PT:
                continue
            d = math.dist(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), (t["x"], t["y"]))
            if d <= max(DIM_NEAR_PT, length / 2 + DIM_NEAR_PT) and (best is None or d < best[0]):
                best = (d, length)
        if best:
            implied.append((value / best[1] / MM_PER_PT_AT_1, t["text"]))  # ratio implied by this dimension
    implied.sort()
    best_run: list = []
    for i, (r, _) in enumerate(implied):
        run = [x for x in implied[i:] if x[0] <= r * (1 + DIM_AGREE_TOL)]
        if len(run) > len(best_run):
            best_run = run
    if len(best_run) < MIN_DIM_AGREE:
        return None
    ratio = sum(r for r, _ in best_run) / len(best_run)
    return ScaleCandidate(ratio, "dimensions", ", ".join(t for _, t in best_run[:6]), len(best_run))


def detect_scale_candidates(texts: list[dict], segments) -> list[ScaleCandidate]:
    """Texts are {text, x, y} (PDF points, y up); segments ((x, y), (x, y)). Never chooses one."""
    out = _notes(texts)
    if (d := _dimensions(texts, segments)) is not None:
        out.append(d)
    seen, uniq = set(), []
    for c in out:
        if (key := (c.source, round(c.ratio, 3))) not in seen:
            seen.add(key)
            uniq.append(c)
    return uniq


def ratio_from_two_points(p1, p2, distance_mm: float) -> float:
    """Real size / paper size from two points (PDF points) a known real distance apart."""
    paper = math.dist(p1, p2) * MM_PER_PT_AT_1
    if paper <= 0 or not distance_mm > 0:
        raise ValueError("two different points and a positive distance are needed")
    return distance_mm / paper
