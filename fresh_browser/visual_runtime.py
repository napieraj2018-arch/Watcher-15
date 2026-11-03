"""Visual extension for the existing ESAVS reader.

This module adds no network client, public endpoint, authentication path or
credential access. The original read_esavs_disk action remains responsible
for authorization, profile ownership, course scope and obtaining the PDF.
Only that reader's already-validated temporary local file is rendered.
"""
from __future__ import annotations
import asyncio
import contextvars
import io
import math
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException
from PIL import Image, ImageDraw
from pypdf import PdfReader
import pypdfium2 as pdfium

import navigation_runtime
import server
import esavs_offline

app = navigation_runtime.app
VISUAL_ACTIONS = {"esavs_visual_page", "esavs_visual_sheet", "esavs_media_inventory"}
CROPS = {"full", "top-left", "top-right", "bottom-left", "bottom-right"}
_mode = contextvars.ContextVar("esavs_visual_mode", default=None)
_last_frame = None
_original_extract = esavs_offline._extract_pdf
_original_action = server.workspace.action
_original_screenshot = server.workspace.screenshot


def validate_visual(args):
    if args.get("name") != "esavs-ophthalmology-i":
        raise HTTPException(403, "Tylko istniejący profil ESAVS.")
    number, index, crop = args.get("delta", 0), args.get("index", -1), args.get("key", "full")
    if (type(number) is not int or not 0 <= number < 600 or type(index) is not int
            or not 0 <= index < 150 or crop not in CROPS):
        raise HTTPException(400, "Nieprawidłowa strona, indeks albo obszar.")
    return number, index, crop


def page_image(document, number, bound=1800, crop="full"):
    page = document[number]
    bitmap = None
    try:
        width, height = page.get_size()
        if min(width, height) <= 0 or max(width, height) > 20000:
            raise HTTPException(422, "Niewspierany rozmiar strony.")
        bitmap = page.render(scale=min(bound / max(width, height), 3.0))
        image = bitmap.to_pil().convert("RGB").copy()
    finally:
        if bitmap is not None:
            bitmap.close()
        page.close()
    if crop != "full":
        width, height = image.size
        left = 0 if crop.endswith("left") else width // 2
        top = 0 if crop.startswith("top") else height // 2
        cropped = image.crop((left, top, min(width, left + (width + 1)//2), min(height, top + (height + 1)//2)))
        image.close()
        image = cropped
    return image


def render_pdf(path, start, contact=False, crop="full"):
    if type(start) is not int or start < 0 or crop not in CROPS:
        raise HTTPException(400, "Nieprawidłowy zakres.")
    doc = pdfium.PdfDocument(str(path))
    try:
        total = len(doc)
        if total > 600 or start >= total:
            raise HTTPException(416, "Poza zakresem PDF.")
        count = min(9, total - start) if contact else 1
        if contact:
            w, h, columns = 540, 440, 3
            image = Image.new("RGB", (columns*w, math.ceil(count/columns)*h), "white")
            draw = ImageDraw.Draw(image)
            for position, number in enumerate(range(start, start + count)):
                panel = page_image(doc, number, 1000)
                panel.thumbnail((w-12, h-30))
                x, y = (position % columns)*w, (position//columns)*h
                draw.text((x+8, y+5), "PDF page " + str(number+1), fill="black")
                image.paste(panel, (x+(w-panel.width)//2, y+25))
                panel.close()
        else:
            image = page_image(doc, start, crop=crop)
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=False)
        dimensions = image.size
        image.close()
        raw = output.getvalue()
        if len(raw) > 7000000:
            raise HTTPException(413, "Obraz przekracza limit.")
        pages = list(range(start+1, start+count+1))
        return raw, {"total_pages":total, "visual_pages":pages, "crop":crop,
                     "pixels":list(dimensions), "contact_sheet":contact,
                     "next_start_page": start+count if start+count < total else None,
                     "visual_review_performed_by_tool":False}
    finally:
        doc.close()


def resolve(value):
    return value.get_object() if hasattr(value, "get_object") else value


def media_inventory(path):
    with Path(path).open("rb") as stream:
        reader = PdfReader(stream, strict=False)
        if len(reader.pages) > 600:
            raise HTTPException(413, "PDF zbyt obszerny.")
        candidates, images = [], []
        for number, page in enumerate(reader.pages, 1):
            resources = resolve(page.get("/Resources", {}))
            objects = resolve(resources.get("/XObject", {})) if resources else {}
            count = sum(1 for val in objects.values() if resolve(val).get("/Subtype") == "/Image")
            if count:
                images.append({"page":number,"direct_image_objects":count})
            for value in list(page.get("/Annots", []))[:500]:
                item = resolve(value)
                kind = str(item.get("/Subtype", ""))
                action = resolve(item.get("/A", {}))
                address = str(action.get("/URI", "")) if isinstance(action, dict) else ""
                parsed = urlsplit(address)
                hint = (parsed.path.lower().endswith((".mp4", ".mov", ".m4v", ".avi", ".webm", ".mp3"))
                        or parsed.hostname in ("youtube.com", "www.youtube.com", "youtu.be", "vimeo.com", "player.vimeo.com"))
                if kind in ("/Movie", "/RichMedia", "/Screen", "/FileAttachment") or hint:
                    candidates.append({"page":number, "kind":kind, "external_media_hint":hint})
        root = resolve(reader.trailer["/Root"])
        names = resolve(root.get("/Names", {}))
        embedded = resolve(names.get("/EmbeddedFiles", {})) if names else {}
        def number_names(node, depth=0):
            if not node or depth>6:
                return 0
            node = resolve(node)
            return len(node.get("/Names", []))//2 + sum(number_names(child, depth+1) for child in node.get("/Kids", [])[:100])
        return {"total_pages":len(reader.pages), "next_start_page":None,
                "image_pages":images, "media_candidates":candidates[:100],
                "embedded_file_count":number_names(embedded),
                "limitation":"Image objects are not cases. Printed video stills, omitted lecture media and nested form images are not fully covered. No film has been watched."}


def extraction_hook(path, offset):
    config = _mode.get()
    if config is None:
        return _original_extract(path, offset)
    if config["action"] == "esavs_media_inventory":
        return media_inventory(path)
    frame, info = render_pdf(path, offset, config["action"] == "esavs_visual_sheet", config["crop"])
    config["frame"] = frame
    return info


async def visual_action(data, automated=False, owner_context=None):
    global _last_frame
    action = data.get("action")
    if action not in VISUAL_ACTIONS:
        if action not in ("snapshot", "tabs", "save"):
            _last_frame = None
        return await _original_action(data, automated=automated, owner_context=owner_context)
    _, _, crop = validate_visual(data)
    config = {"action":action,"crop":crop}
    token = _mode.set(config)
    _last_frame = None
    try:
        request = dict(data)
        request["action"] = "read_esavs_disk"
        result = await _original_action(request, automated=automated, owner_context=owner_context)
        if config.get("frame"):
            ws = server.workspace
            _last_frame = {"frame":config["frame"],"context":ws.context,"page":ws.page(),
                           "url":ws.page().url,"time":time.monotonic()}
            result["image_delivery"] = "Call screenshot for this profile next; owner UI remains unchanged."
        return result
    finally:
        _mode.reset(token)


async def visual_screenshot(name, owner_context=None, with_metadata=False):
    global _last_frame
    ws = server.workspace
    async with ws.lock:
        frame = _last_frame
        if (frame and name == "esavs-ophthalmology-i" and ws.profile == name and not ws.human
                and owner_context is None and not with_metadata and ws.context is frame["context"]
                and ws.page() is frame["page"] and ws.page().url == frame["url"]
                and time.monotonic()-frame["time"] < 120):
            _last_frame = None
            return frame["frame"]
    return await _original_screenshot(name, owner_context=owner_context, with_metadata=with_metadata)


esavs_offline._extract_pdf = extraction_hook
server.workspace.action = visual_action
server.workspace.screenshot = visual_screenshot
