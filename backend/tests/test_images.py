from PIL import Image, ImageDraw

from app.images import place_hat_on_original


def test_hat_paste_leaves_the_outfit_unchanged():
    original = Image.new("RGB", (200, 400), (200, 20, 20))
    generated = Image.new("RGB", (200, 400), (20, 20, 200))
    ImageDraw.Draw(generated).rectangle((40, 8, 160, 70), fill=(10, 180, 40))
    face = (70, 90, 60, 60)
    result = place_hat_on_original(original, generated, face, face)
    assert result.getpixel((100, 360)) == (200, 20, 20)
    hat = result.getpixel((100, 24))
    assert hat[1] > hat[0]
    assert hat[1] > hat[2]
