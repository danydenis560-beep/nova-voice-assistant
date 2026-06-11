"""Generate a glowing 'arc reactor' icon (nova.ico) for the desktop shortcut."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

BASE = Path(__file__).resolve().parent
S = 256
cx = cy = S // 2
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

# soft outer glow
glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
gd.ellipse([cx - 96, cy - 96, cx + 96, cy + 96], outline=(40, 200, 255, 255), width=16)
glow = glow.filter(ImageFilter.GaussianBlur(13))
img = Image.alpha_composite(img, glow)

d = ImageDraw.Draw(img)
d.ellipse([cx - 92, cy - 92, cx + 92, cy + 92], outline=(90, 220, 255, 255), width=7)
d.ellipse([cx - 62, cy - 62, cx + 62, cy + 62], outline=(120, 230, 255, 230), width=4)
for r, col in [(42, (110, 235, 255, 255)), (26, (200, 250, 255, 255)), (13, (255, 255, 255, 255))]:
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)

img.save(BASE / "nova.ico", format="ICO",
         sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print("wrote nova.ico")
