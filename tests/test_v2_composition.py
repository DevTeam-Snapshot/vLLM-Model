from PIL import ImageFont

from v2.ad_drawing import FONT_PATH, wrap_text


def test_wrap_preserves_characters_when_korean_copy_is_long() -> None:
    text = "한글 숙소명과  두 칸 공백, 확정 문구를 그대로 보존합니다."
    font = ImageFont.truetype(str(FONT_PATH), 42)
    result = wrap_text(text, font, 230)
    assert "".join(result) == text
    assert all(font.getlength(line) <= 230 for line in result)
