#!/usr/bin/env python3
"""Build the static software catalog from public GitHub release metadata."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "sources.json"
DEFAULT_OUTPUT = ROOT / "data" / "apps.json"
ALLOWED_DOWNLOAD_HOSTS = {
    "github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
}


class CatalogError(RuntimeError):
    """Raised when an upstream response cannot produce a safe catalog."""


def fetch_json(url: str, token: str | None = None, attempts: int = 3) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-actions-software-catalog/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=25) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(2**attempt)

    raise CatalogError(f"Request failed after {attempts} attempts: {url}: {last_error}")


def parse_notes(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    notes = []
    for line in value.splitlines():
        cleaned = line.strip()
        while cleaned.startswith(("*", "-")):
            cleaned = cleaned[1:].strip()
        if cleaned:
            notes.append(cleaned)
    return notes


def validate_download_url(url: Any) -> str:
    if not isinstance(url, str):
        raise CatalogError("A download entry is missing download_url")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS:
        raise CatalogError(f"Refusing untrusted download URL: {url}")
    return url


def build_interfaces(config: dict[str, Any]) -> list[dict[str, str]]:
    result = []
    for item in config.get("interfaces", []):
        missing = [key for key in ("id", "name", "url") if not item.get(key)]
        if missing:
            raise CatalogError(f"Interface is missing required fields: {', '.join(missing)}")
        parsed = urlparse(item["url"])
        if parsed.scheme != "https" or not parsed.hostname:
            raise CatalogError(f"Interface URL must use HTTPS: {item['url']}")
        result.append(
            {
                "id": str(item["id"]),
                "name": str(item["name"]),
                "description": str(item.get("description", "")),
                "url": item["url"],
            }
        )
    return result


def build_mirrors(config: dict[str, Any]) -> list[dict[str, str]]:
    result = []
    for item in config.get("download_mirrors", []):
        required = ("id", "label", "provider", "url_template")
        missing = [key for key in required if not item.get(key)]
        if missing:
            raise CatalogError(f"Download mirror is missing required fields: {', '.join(missing)}")
        template = str(item["url_template"])
        if template.count("{url}") != 1:
            raise CatalogError(f"Download mirror template must contain one {{url}}: {template}")
        parsed = urlparse(template.replace("{url}", "https://example.com/file"))
        if parsed.scheme != "https" or not parsed.hostname:
            raise CatalogError(f"Download mirror must use HTTPS: {template}")
        result.append(
            {
                "id": str(item["id"]),
                "label": str(item["label"]),
                "provider": str(item["provider"]),
                "url_template": template,
            }
        )
    return result


def create_mirror_downloads(mirrors: list[dict[str, str]], direct_url: str) -> list[dict[str, str]]:
    return [
        {
            "id": mirror["id"],
            "label": mirror["label"],
            "provider": mirror["provider"],
            "url": mirror["url_template"].replace("{url}", direct_url),
        }
        for mirror in mirrors
    ]


def github_api_url(repository: str, suffix: str) -> str:
    safe_repo = "/".join(quote(part, safe="") for part in repository.split("/"))
    return f"https://api.github.com/repos/{safe_repo}/{suffix}"


def build_source(
    source: dict[str, Any],
    getter: Callable[[str], Any],
    mirrors: list[dict[str, str]],
) -> dict[str, Any]:
    required = ("id", "name", "repository", "branch", "directory", "packages")
    missing = [key for key in required if not source.get(key)]
    if missing:
        raise CatalogError(f"Source is missing required fields: {', '.join(missing)}")

    repository = source["repository"]
    branch = source["branch"]
    directory = source["directory"].strip("/")
    contents_url = github_api_url(
        repository,
        f"contents/{quote(directory, safe='/')}?ref={quote(branch, safe='')}",
    )
    contents = getter(contents_url)
    if not isinstance(contents, list):
        raise CatalogError(f"Unexpected directory response for {repository}/{directory}")
    files = {item.get("name"): item for item in contents if item.get("type") == "file"}

    commits_url = github_api_url(
        repository,
        f"commits?sha={quote(branch, safe='')}&path={quote(directory, safe='/')}&per_page=1",
    )
    commits = getter(commits_url)
    try:
        updated_at = commits[0]["commit"]["committer"]["date"]
        source_revision = commits[0]["sha"]
    except (IndexError, KeyError, TypeError) as error:
        raise CatalogError(f"Cannot read latest commit for {repository}/{directory}") from error

    releases = []
    for package in source["packages"]:
        metadata_name = package.get("metadata")
        metadata_file = files.get(metadata_name)
        if not metadata_file:
            raise CatalogError(f"Missing metadata file: {metadata_name}")
        metadata_url = validate_download_url(metadata_file.get("download_url"))
        metadata = getter(metadata_url)
        version = str(metadata.get("name", "")).strip()
        if not version:
            raise CatalogError(f"Metadata {metadata_name} has no version name")

        downloads = []
        for download in package.get("downloads", []):
            filename = download.get("filename")
            file_info = files.get(filename)
            if not file_info:
                raise CatalogError(f"Missing configured download: {filename}")
            direct_url = validate_download_url(file_info.get("download_url"))
            downloads.append(
                {
                    "filename": filename,
                    "label": download.get("label", filename),
                    "architecture": download.get("architecture", "unknown"),
                    "recommended": bool(download.get("recommended")),
                    "size": int(file_info.get("size") or 0),
                    "url": direct_url,
                    "mirrors": create_mirror_downloads(mirrors, direct_url),
                }
            )

        releases.append(
            {
                "id": package["id"],
                "label": package["label"],
                "platform": package["platform"],
                "version": version,
                "version_code": metadata.get("code"),
                "notes": parse_notes(metadata.get("desc")),
                "updated_at": updated_at,
                "downloads": downloads,
            }
        )

    return {
        "id": source["id"],
        "name": source["name"],
        "description": source.get("description", ""),
        "homepage": source.get("homepage", f"https://github.com/{repository}"),
        "repository": repository,
        "icon": source.get("icon", ""),
        "source_revision": source_revision,
        "updated_at": updated_at,
        "releases": releases,
    }


def build_catalog(config: dict[str, Any], getter: Callable[[str], Any]) -> dict[str, Any]:
    sources = config.get("sources")
    if not isinstance(sources, list) or not sources:
        raise CatalogError("Config must contain at least one source")

    mirrors = build_mirrors(config)
    apps = [build_source(source, getter, mirrors) for source in sources]
    latest = max(app["updated_at"] for app in apps)
    return {
        "schema_version": 1,
        "generated_at": latest,
        "interfaces": build_interfaces(config),
        "apps": apps,
    }


def write_if_changed(path: Path, catalog: dict[str, Any]) -> bool:
    rendered = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == rendered:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        token = os.environ.get("GITHUB_TOKEN")
        catalog = build_catalog(config, lambda url: fetch_json(url, token=token))
        changed = write_if_changed(args.output, catalog)
    except (CatalogError, OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    status = "updated" if changed else "already current"
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"Catalog {status}: {args.output} (checked {timestamp})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
