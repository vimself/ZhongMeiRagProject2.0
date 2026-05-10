from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedBBox:
    x: float
    y: float
    width: float
    height: float

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


def normalize_pixel_bbox(
    bbox: list[float] | tuple[float, float, float, float],
    *,
    page_width: float,
    page_height: float,
) -> NormalizedBBox:
    x1, y1, x2, y2 = bbox
    return NormalizedBBox(
        x=_ratio(x1, page_width),
        y=_ratio(y1, page_height),
        width=_ratio(x2 - x1, page_width),
        height=_ratio(y2 - y1, page_height),
    )


def normalize_pdf_bbox_from_left_bottom(
    bbox: list[float] | tuple[float, float, float, float],
    *,
    page_width: float,
    page_height: float,
) -> NormalizedBBox:
    x1, y1, x2, y2 = bbox
    top_y = page_height - y2
    return normalize_pixel_bbox(
        [x1, top_y, x2, page_height - y1],
        page_width=page_width,
        page_height=page_height,
    )


def _ratio(value: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, value / total))
