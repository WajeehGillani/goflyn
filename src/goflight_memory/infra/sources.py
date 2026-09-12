"""Immutable UTF-8 notes with JSON-quoted YAML front matter; no YAML dependency."""

import json
import re
from pathlib import Path

from goflight_memory.core.models import SourceMetadata

SOURCE_ID = re.compile(r"source-[0-9]{3,}")
SEPARATOR = b"\n---\n\n"


def source_path(raw_dir: Path, source_id: str) -> Path:
    if not SOURCE_ID.fullmatch(source_id):
        raise ValueError("Invalid source ID")
    path = raw_dir / f"{source_id}.md"
    if path.is_symlink():
        raise ValueError("Source symlinks are not supported")
    return path


def next_source_id(raw_dir: Path) -> str:
    numbers = [
        int(path.stem.removeprefix("source-"))
        for path in raw_dir.glob("source-*.md")
        if SOURCE_ID.fullmatch(path.stem)
    ]
    return f"source-{max(numbers, default=0) + 1:03d}"


def save_source(raw_dir: Path, metadata: SourceMetadata, text: str) -> Path:
    path = source_path(raw_dir, metadata.source_id)
    lines = ["---"] + [
        f"{key}: {json.dumps(value, ensure_ascii=False)}"
        for key, value in metadata.model_dump(mode="json").items()
    ]
    content = "\n".join(lines).encode("utf-8") + SEPARATOR + text.encode("utf-8")
    # Exclusive creation never truncates an existing source, even outside our lock.
    with path.open("xb") as handle:
        try:
            handle.write(content)
            handle.flush()
        except BaseException:
            # A failed creation is not a preserved source; remove only this partial file.
            path.unlink()
            raise
    return path


def read_source(path: Path) -> tuple[SourceMetadata, str]:
    if path.is_symlink():
        raise ValueError("Source symlinks are not supported")
    header, body = path.read_bytes().split(SEPARATOR, 1)
    lines = header.decode("utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise ValueError("Invalid raw source header")
    data = {}
    for line in lines[1:]:
        key, value = line.split(": ", 1)
        if key in data:
            raise ValueError("Duplicate raw source metadata")
        data[key] = json.loads(value)
    metadata = SourceMetadata.model_validate(data)
    if path.stem != metadata.source_id or not SOURCE_ID.fullmatch(metadata.source_id):
        raise ValueError("Source ID does not match its filename")
    return metadata, body.decode("utf-8")
