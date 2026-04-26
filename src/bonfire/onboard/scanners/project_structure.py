"""Project Structure Scanner — Reel 1.

Async adapter over ``TechScanner`` that emits streaming
``ScanUpdate`` events for detected languages, frameworks, test tools,
build systems, and package managers.

Scanner interface::

    async def scan(project_path: Path, emit: ScanCallback) -> int

"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bonfire.onboard.protocol import ScanCallback, ScanUpdate
from bonfire.scan.tech_scanner import TechScanner

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["scan"]

PANEL = "project_structure"


async def scan(project_path: Path, emit: ScanCallback) -> int:
    """Scan project structure and emit ScanUpdate events.

    Wraps ``TechScanner`` to produce streaming events for the
    Front Door scan reel.

    Returns the total number of items emitted.
    """
    scanner = TechScanner(project_path, project_name=project_path.name)
    entries = await scanner.scan()

    count = 0
    for entry in entries:
        meta = entry.metadata
        technology = meta.get("technology", "unknown")
        category = meta.get("category", "unknown")
        file_count = meta.get("file_count")

        if file_count is not None:
            detail = f"{file_count} files"
        else:
            detail = meta.get("source_file", "")
            # Fall back: source_file lives in metadata for frameworks,
            # but for the scanner it's baked into the content string.
            # Extract from the VaultEntry's source_file construction.
            if not detail:
                # The scanner builds content as:
                #   "{tech}\n\nDetected from {source_file} in {project}."
                lines = entry.content.split("\n")
                for line in lines:
                    if line.startswith("Detected from "):
                        # "Detected from requirements.txt in project."
                        part = line[len("Detected from ") :]
                        detail = part.split(" in ")[0]
                        break

        event = ScanUpdate(
            panel=PANEL,
            label=category,
            value=technology,
            detail=detail,
        )
        await emit(event)
        count += 1

    return count
