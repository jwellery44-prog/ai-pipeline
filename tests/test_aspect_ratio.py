import io
from PIL import Image
from app.services.pipeline import adjust_aspect_ratio

def create_test_image(width: int, height: int, mode: str = "RGB", fmt: str = "PNG") -> bytes:
    """Helper to create a dummy image in memory."""
    img = Image.new(mode, (width, height), color=(255, 0, 0))
    out = io.BytesIO()
    img.save(out, format=fmt)
    return out.getvalue()

def test_no_adjustment():
    # When target_ratio is "none", should return the original bytes
    orig_bytes = create_test_image(100, 200)
    adjusted_bytes = adjust_aspect_ratio(orig_bytes, "none")
    assert orig_bytes == adjusted_bytes

def test_square_padding_tall_rgb():
    # Tall image (100x200 RGB) -> should become 200x200
    orig_bytes = create_test_image(100, 200, mode="RGB")
    adjusted_bytes = adjust_aspect_ratio(orig_bytes, "1:1")
    
    img = Image.open(io.BytesIO(adjusted_bytes))
    assert img.size == (200, 200)
    assert img.mode == "RGB"

def test_square_padding_wide_rgba():
    # Wide image (300x150 RGBA) -> should become 300x300
    orig_bytes = create_test_image(300, 150, mode="RGBA")
    adjusted_bytes = adjust_aspect_ratio(orig_bytes, "1:1")
    
    img = Image.open(io.BytesIO(adjusted_bytes))
    assert img.size == (300, 300)
    assert img.mode == "RGBA"

def test_invalid_image_fallback():
    # Invalid image bytes should be returned unchanged without raising an exception
    bad_bytes = b"not an image"
    adjusted_bytes = adjust_aspect_ratio(bad_bytes, "1:1")
    assert adjusted_bytes == bad_bytes

def test_jpeg_rgba_conversion():
    # Create a valid RGBA PNG image bytes
    orig_bytes = create_test_image(100, 200, mode="RGBA", fmt="PNG")

    from unittest.mock import patch
    original_open = Image.open

    def mock_open(*args, **kwargs):
        img = original_open(*args, **kwargs)
        img.format = "JPEG"  # force format to JPEG
        return img

    with patch("PIL.Image.open", mock_open):
        adjusted_bytes = adjust_aspect_ratio(orig_bytes, "1:1")

    img = Image.open(io.BytesIO(adjusted_bytes))
    assert img.size == (200, 200)
    assert img.mode == "RGB"


if __name__ == "__main__":
    test_no_adjustment()
    test_square_padding_tall_rgb()
    test_square_padding_wide_rgba()
    test_invalid_image_fallback()
    test_jpeg_rgba_conversion()
    print("All aspect ratio tests passed successfully!")

