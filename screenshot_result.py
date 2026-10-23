"""Bounded in-memory MCP screenshot results; no disk/URL reads or metadata.

Called only after the existing owner guard has validated a session capability.
The guard still rejects images in public listings and unowned results.
"""
from __future__ import annotations

import base64
import binascii
from mcp.server.mcpserver.exceptions import ToolError

PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
MAX_PNG_BYTES = 12 * 1024 * 1024


class ScreenshotResultError(ToolError):
    """Fixed error code only; image data and provider text must never be logged."""


def image_result(value):
    """Copy an exact SDK image into a fresh PNG helper, or return None.

    Do not use duck typing or call to_image_content on an input: that method
    can read a local file, and a subclass can override it. Screenshot bytes
    must already be in memory. Rebuilding drops metadata and extra fields.
    """
    from mcp.server.mcpserver.utilities.types import Image
    from mcp_types import ImageContent

    if type(value) is Image:
        if value.path is not None or type(value.data) is not bytes:
            raise ScreenshotResultError('SCREENSHOT_IN_MEMORY_REQUIRED')
        if value._mime_type != 'image/png':
            raise ScreenshotResultError('SCREENSHOT_PNG_REQUIRED')
        raw = value.data
    elif type(value) is ImageContent:
        if value.mime_type != 'image/png' or type(value.data) is not str:
            raise ScreenshotResultError('SCREENSHOT_PNG_REQUIRED')
        if len(value.data) > 4 * ((MAX_PNG_BYTES + 2) // 3):
            raise ScreenshotResultError('SCREENSHOT_TOO_LARGE_USE_VIEWPORT')
        try:
            raw = base64.b64decode(value.data, validate=True)
        except (ValueError, binascii.Error):
            raise ScreenshotResultError('SCREENSHOT_PNG_INVALID') from None
    else:
        return None

    if len(raw) > MAX_PNG_BYTES:
        raise ScreenshotResultError('SCREENSHOT_TOO_LARGE_USE_VIEWPORT')
    # PNG must contain its IHDR. We do not decode untrusted pixels here.
    if (len(raw) < 33 or not raw.startswith(PNG_SIGNATURE)
            or raw[8:16] != b'\x00\x00\x00\rIHDR'
            or int.from_bytes(raw[16:20], 'big') == 0
            or int.from_bytes(raw[20:24], 'big') == 0):
        raise ScreenshotResultError('SCREENSHOT_PNG_INVALID')
    return Image(data=raw, format='png')
