"""Genera el icono .ico (brutalista: cuadro naranja con sombra dura y una P blanca)."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

destino = Path(sys.argv[1])
destino.parent.mkdir(parents=True, exist_ok=True)
S = 512
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
borde = 28
d.rectangle([60, 60, S - 8, S - 8], fill="#0a0a0a")  # sombra dura
d.rectangle([8, 8, S - 60, S - 60], fill="#ff3d00", outline="#0a0a0a", width=borde)
try:
    fuente = ImageFont.truetype("arialbd.ttf", 330)
except OSError:
    fuente = ImageFont.load_default()
caja = d.textbbox((0, 0), "P", font=fuente)
w, h = caja[2] - caja[0], caja[3] - caja[1]
cx, cy = (S - 52) / 2, (S - 52) / 2
d.text((cx - w / 2 - caja[0], cy - h / 2 - caja[1]), "P", font=fuente, fill="#ffffff")
img.save(destino, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.resize((256, 256), Image.LANCZOS).save(destino.with_suffix(".png"))
print("icono:", destino)
