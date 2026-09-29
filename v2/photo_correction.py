"""Bounded pixel corrections; never synthesize facilities, scenery or missing edges."""

from math import ceil, cos, radians, sin

from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat


def _line_score(edges: Image.Image) -> float:
    margin = max(4, min(edges.size) // 12)
    interior = edges.crop((margin, margin, edges.width - margin, edges.height - margin))
    projection = interior.resize((1, interior.height), Image.Resampling.BOX).tobytes()
    peaks: list[tuple[int, int]] = []
    for row in sorted(range(len(projection)), key=projection.__getitem__, reverse=True):
        if projection[row] < 55:
            break
        if all(abs(row - previous) > 8 for previous, _ in peaks):
            peaks.append((row, projection[row]))
        if len(peaks) == 4:
            break
    return float(sum(value * value for _, value in peaks)) if len(peaks) >= 3 else 0.0


def estimate_rotation(image: Image.Image) -> float:
    """Require three separated long edges and a clear optimum within +/-2 degrees."""
    sample = ImageOps.contain(image.convert("L"), (384, 384))
    if min(sample.size) < 64:
        return 0.0
    edges = sample.filter(ImageFilter.FIND_EDGES)
    scores = [
        (
            _line_score(edges.rotate(step / 4, resample=Image.Resampling.BILINEAR)),
            step / 4,
        )
        for step in range(-8, 9)
    ]
    best_score, angle = max(scores)
    baseline = scores[8][0]
    alternatives = [
        score for score, candidate in scores if abs(candidate - angle) >= 0.75
    ]
    if (
        abs(angle) < 0.5
        or abs(angle) >= 2
        or best_score <= baseline * 1.2
        or best_score <= max(alternatives) * 1.1
    ):
        return 0.0
    return angle


def _straighten(image: Image.Image) -> Image.Image:
    angle = estimate_rotation(image)
    if angle == 0:
        return image.copy()
    theta = radians(abs(angle))
    width, height = image.size
    # Conservative inner crop removes rotation fill without inventing edge pixels.
    inset_x = ceil((height * sin(theta) + width * (1 - cos(theta))) / 2) + 2
    inset_y = ceil((width * sin(theta) + height * (1 - cos(theta))) / 2) + 2
    retained = (width - 2 * inset_x) * (height - 2 * inset_y) / (width * height)
    if min(width - 2 * inset_x, height - 2 * inset_y) <= 0 or retained < 0.9:
        return image.copy()
    rotated = image.rotate(angle, resample=Image.Resampling.BICUBIC)
    cropped = rotated.crop((inset_x, inset_y, width - inset_x, height - inset_y))
    return ImageOps.fit(cropped, image.size, method=Image.Resampling.LANCZOS)


def correct_photo(image: Image.Image) -> Image.Image:
    corrected = _straighten(image)
    sample = ImageOps.contain(corrected, (128, 128))
    channels = [list(channel.tobytes()) for channel in sample.split()]
    neutral = [
        pixel
        for pixel in zip(*channels, strict=True)
        if 50 <= min(pixel) and max(pixel) <= 235 and max(pixel) - min(pixel) <= 18
    ]
    if len(neutral) >= sample.width * sample.height * 0.05:
        means = [
            sum(pixel[index] for pixel in neutral) / len(neutral) for index in range(3)
        ]
        target = sum(means) / 3
        balanced = []
        for channel, mean in zip(corrected.split(), means, strict=True):
            gain = min(1.02, max(0.98, target / mean))
            balanced.append(
                channel.point([min(255, round(value * gain)) for value in range(256)])
            )
        corrected = Image.merge("RGB", tuple(balanced))
    luminance = ImageStat.Stat(sample.convert("L")).mean[0]
    exposure = min(1.06, max(0.96, 128 / max(1, luminance)))
    corrected = ImageEnhance.Brightness(corrected).enhance(exposure)
    corrected = ImageEnhance.Contrast(corrected).enhance(1.02)
    return ImageEnhance.Color(corrected).enhance(1.02)
