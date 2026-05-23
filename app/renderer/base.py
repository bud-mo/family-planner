"""Abstract base class for all renderers."""
from __future__ import annotations

from abc import ABC, abstractmethod

from PIL import Image


class Renderer(ABC):
    @abstractmethod
    def render(self) -> Image.Image:
        """Produce a full-frame ``PIL.Image`` in RGB mode."""
        ...
