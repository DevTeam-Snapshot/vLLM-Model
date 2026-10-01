import pytest
from PIL import Image, ImageChops, ImageDraw

from v2 import photo_correction


@pytest.mark.parametrize("tilt", [-1.5, 1.5])
def test_straightens_when_multiple_long_edges_agree(tilt: float) -> None:
    # Given: several parallel architectural edges with a known small tilt.
    source = Image.new("RGB", (900, 700), "#909090")
    draw = ImageDraw.Draw(source)
    for y in (140, 260, 380, 500):
        draw.line((70, y, 830, y), fill="#eeeeee", width=4)
    tilted = source.rotate(tilt, resample=Image.Resampling.BICUBIC)
    # When: the conservative correction is estimated.
    angle = photo_correction.estimate_rotation(tilted)
    # Then: the correction cancels the input tilt within the search resolution.
    assert abs(angle + tilt) <= 0.5


def test_preserves_geometry_when_evidence_is_absent() -> None:
    # Given: a dark, featureless photo without reliable straight lines.
    source = Image.new("RGB", (800, 600), (80, 80, 80))
    original = source.copy()
    # When: bounded corrections run.
    corrected = photo_correction.correct_photo(source)
    # Then: the original is immutable, dimensions survive, and exposure stays mild.
    assert photo_correction.estimate_rotation(source) == 0
    assert corrected.size == source.size
    assert ImageChops.difference(source, original).getbbox() is None
    assert 80 < corrected.convert("L").getextrema()[0] <= 87


def test_skips_rotation_when_only_one_sloping_edge_exists() -> None:
    # Given: one edge could be scenery rather than a camera tilt.
    source = Image.new("RGB", (900, 700), "#888888")
    ImageDraw.Draw(source).line((50, 350, 850, 330), fill="white", width=4)
    # When / Then: insufficient evidence does not trigger a geometric edit.
    assert photo_correction.estimate_rotation(source) == 0


def test_rotated_photo_has_no_synthetic_border_when_corrected() -> None:
    # Given: a tilted photo whose original interior has no black pixels.
    source = Image.new("RGB", (900, 700), "#909090")
    draw = ImageDraw.Draw(source)
    for y in (140, 260, 380, 500):
        draw.line((70, y, 830, y), fill="#eeeeee", width=4)
    tilted = source.rotate(1.5, resample=Image.Resampling.BICUBIC)
    # When: correction rotates and crops the photo.
    corrected = photo_correction.correct_photo(tilted)
    # Then: output dimensions survive and empty rotation fill is removed.
    assert corrected.size == source.size
    assert corrected.convert("L").getextrema()[0] > 100


@pytest.mark.parametrize("size", [(2400, 400), (400, 2400), (1, 1)])
def test_correction_handles_small_and_panoramic_photos(size: tuple[int, int]) -> None:
    # Given: valid images at the edge-estimation size boundaries.
    source = Image.new("RGB", size, "#89919a")
    # When: corrections run without sufficient line evidence.
    corrected = photo_correction.correct_photo(source)
    # Then: no invalid crop or unintended geometry change occurs.
    assert corrected.size == size
