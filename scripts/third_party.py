"""Collect installed production-dependency notices for distributable bundles."""

import importlib.metadata as metadata
import json
from pathlib import Path
import shutil

from packaging.requirements import Requirement


def collect(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    pending = [("videobot-desktop", set())]
    seen = set()
    entries = []
    while pending:
        name, extras = pending.pop()
        dist = metadata.distribution(name)
        canonical = dist.metadata["Name"].lower().replace("_", "-")
        if canonical in seen:
            continue
        seen.add(canonical)
        target = output / canonical
        target.mkdir(exist_ok=True)
        for item in dist.files or []:
            if any(word in item.name.lower() for word in ("license", "copying", "notice")):
                source = Path(dist.locate_file(item))
                if source.is_file() and source.stat().st_size < 10 * 1024 * 1024:
                    safe = str(item).replace("/", "_").replace("\\", "_")
                    shutil.copyfile(source, target / safe)
        entries.append(
            {
                "name": dist.metadata["Name"],
                "version": dist.version,
                "license": dist.metadata.get("License-Expression") or dist.metadata.get("License"),
                "project_urls": dist.metadata.get_all("Project-URL", []),
            }
        )
        for text in dist.requires or []:
            requirement = Requirement(text)
            if requirement.marker and not any(requirement.marker.evaluate({"extra": extra}) for extra in {""} | extras):
                continue
            pending.append((requirement.name, requirement.extras))
    (output / "INDEX.json").write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    return entries


if __name__ == "__main__":
    import sys

    collect(sys.argv[1])
