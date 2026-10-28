import base64
from dataclasses import dataclass

from meta_sam_parser import (
    CompletedOutcome,
    SegmentationBoxRecord,
    SegmentationMask,
    SegmentationMaskRecord,
    image_segmentation_format,
)

import meta_client


@dataclass
class Detection:
    box: tuple[int, int, int, int]  # x1, y1, x2, y2 in source pixels
    confidence: float | None
    mask: SegmentationMask | None

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.box
        return (x1 + x2) // 2, (y1 + y2) // 2


def parse(text: str) -> list[Detection]:
    """Parse SAM output into detections, best confidence first. Empty text means no match."""
    parser = image_segmentation_format().create_parser()
    parser.push(text, emit=False)
    records = parser.finish(CompletedOutcome()).result.records
    masks = {r.object_id: r.mask for r in records if isinstance(r, SegmentationMaskRecord)}
    detections = [
        Detection(
            box=(round(r.left), round(r.top), round(r.right), round(r.bottom)),
            confidence=r.confidence,
            mask=masks.get(r.object_id),
        )
        for r in records
        if isinstance(r, SegmentationBoxRecord)
    ]
    return sorted(detections, key=lambda d: d.confidence or 0, reverse=True)


def segment(image: bytes, phrase: str, purpose: str = "dev", mime: str = "image/png") -> list[Detection]:
    url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
    resp = meta_client.responses(
        model=meta_client.SAM,
        purpose=purpose,
        metadata={"include_confidence": "true"},
        input=[{"role": "user", "content": [
            {"type": "input_text", "text": phrase},
            {"type": "input_image", "image_url": url},
        ]}],
    )
    return parse(meta_client.output_text(resp))
