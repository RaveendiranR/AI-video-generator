from __future__ import annotations

import argparse
import logging
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass

LOGGER = logging.getLogger("faceless_video_generator.trends")


@dataclass(frozen=True)
class Trend:
    title: str
    traffic: str = ""
    link: str = ""


def fetch_google_trends(region: str = "US", limit: int = 10) -> list[Trend]:
    """Read Google's public daily trending RSS feed without an API key."""
    region = region.upper()
    url = f"https://trends.google.com/trending/rss?geo={urllib.parse.quote(region)}"
    request = urllib.request.Request(url, headers={"User-Agent": "faceless-video-generator/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            root = ET.fromstring(response.read())
    except (OSError, ET.ParseError) as exc:
        raise RuntimeError(f"Could not fetch Google Trends for {region}: {exc}") from exc

    trends: list[Trend] = []
    for item in root.iter():
        if item.tag.rsplit("}", 1)[-1] != "item":
            continue
        values = {
            child.tag.rsplit("}", 1)[-1]: (child.text or "").strip()
            for child in item
        }
        title = values.get("title")
        if title:
            trends.append(Trend(title=title, traffic=values.get("approx_traffic", ""), link=values.get("link", "")))
    return trends[: max(1, limit)]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Show current Google Trends topics for a region.")
    parser.add_argument("--region", default="US")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args(argv)
    try:
        for index, trend in enumerate(fetch_google_trends(args.region, args.limit), 1):
            traffic = f" ({trend.traffic})" if trend.traffic else ""
            print(f"{index}. {trend.title}{traffic}")
    except RuntimeError as exc:
        parser.exit(1, f"error: {exc}\n")


if __name__ == "__main__":
    main()