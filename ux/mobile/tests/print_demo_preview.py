"""Emit only a heavily compressed screenshot of the synthetic demo UI.

This must NEVER be reused for authenticated sites or customer screenshots.
"""
import base64
import io
from pathlib import Path
from PIL import Image

root=Path(__file__).resolve().parents[1]
path=root/"screenshots"/"mobile-home.png"
with Image.open(path) as original:
    view=original.convert("RGB")
view.thumbnail((340,740),Image.Resampling.LANCZOS)
buff=io.BytesIO()
view.save(buff,"WEBP",quality=48,method=6)
encoded=base64.b64encode(buff.getvalue()).decode("ascii")
if len(encoded)>150000:
    raise RuntimeError("Synthetic preview exceeds safe CI output limit")
print("AIB_UX_PREVIEW_BEGIN")
for idx in range(0,len(encoded),1800):
    print("AIB_UX_PREVIEW_PART:"+encoded[idx:idx+1800])
print("AIB_UX_PREVIEW_END")
