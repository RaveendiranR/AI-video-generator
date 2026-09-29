"""Reliable faceless video generation from a script and images."""

from .envfile import load_env

load_env()  # makes keys from a .env file visible to every entry point (CLI, web page, render subprocesses)

from .config import VideoConfig  # noqa: E402
from .pipeline import VideoGenerator  # noqa: E402

__all__ = ["VideoConfig", "VideoGenerator"]
__version__ = "1.13.1"