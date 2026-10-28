from pathlib import Path

from meta_sam_parser import decode_mask_to_raster

import sam

FIXTURE = Path(__file__).parent / "fixtures" / "sam_two_buttons.txt"


def test_parse_real_output_sorted_by_confidence():
    best, other = sam.parse(FIXTURE.read_text())
    assert best.box == (280, 407, 400, 442)
    assert best.center == (340, 424)
    assert best.confidence > other.confidence > 0.5
    assert sum(decode_mask_to_raster(best.mask)) > 0


def test_parse_empty_output_means_no_match():
    assert sam.parse("") == []
