# pyright: strict
"""Bounded PNG inputs for an explicitly selected local vision route."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from typing import Literal, TypeGuard

MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_IMAGE_BATCH_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 4
MAX_IMAGE_DIMENSION = 4096
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True, slots=True)
class LLMImage:
    """One immutable image; bytes are excluded from diagnostic representations.

    Header validation bounds input and advertised dimensions. It is not a
    decoder or proof of readability; the vision runtime must decode the image.
    """

    data: bytes = field(repr=False)
    media_type: Literal["image/png"] = "image/png"

    def __post_init__(self) -> None:
        _validate_png(self.data, self.media_type)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


def _validate_png(data: object, media_type: object) -> None:
    if not isinstance(data, bytes) or not 33 <= len(data) <= MAX_IMAGE_BYTES:
        raise ValueError("A local vision input must contain 33 bytes to 4 MiB of PNG data")
    if media_type != "image/png":
        raise ValueError("This local vision input route supports PNG only")
    if (
        not data.startswith(_PNG_SIGNATURE)
        or data[8:12] != b"\x00\x00\x00\r"
        or data[12:16] != b"IHDR"
    ):
        raise ValueError("A local vision input must have a PNG signature and IHDR header")
    width, height = struct.unpack(">II", data[16:24])
    if not (0 < width <= MAX_IMAGE_DIMENSION and 0 < height <= MAX_IMAGE_DIMENSION):
        raise ValueError("Local vision PNG dimensions must be between 1 and 4096 pixels")


def validate_images(images: object) -> None:
    """Enforce the same structural bounds at router and direct provider seams."""
    if not _is_tuple(images) or len(images) > MAX_IMAGES:
        raise ValueError("A local vision call accepts an immutable tuple of at most four images")
    total_bytes = 0
    for image in images:
        if not isinstance(image, LLMImage):
            raise ValueError("A local vision call requires validated LLMImage values")
        total_bytes += len(image.data)
    if total_bytes > MAX_IMAGE_BATCH_BYTES:
        raise ValueError("Local vision inputs exceed the 8 MiB combined byte limit")


def _is_tuple(value: object) -> TypeGuard[tuple[object, ...]]:
    return isinstance(value, tuple)
