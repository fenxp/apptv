#!/usr/bin/env python3
"""Build the static software catalog from public GitHub release metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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


def parse_release_notes(value: Any) -> list[str]:
    """Prefer the changelog code block used by the release workflow."""
    if not isinstance(value, str):
        return []
    match = re.search(r"```[^\n]*\n(?P<notes>.*?)```", value, flags=re.DOTALL)
    return parse_notes(match.group("notes") if match else value)


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


def release_tag(release: dict[str, Any]) -> str:
    return str(release.get("tag_name") or release.get("name") or "").strip()


def release_version(release: dict[str, Any]) -> str:
    return release_tag(release).removeprefix("v")


def release_updated_at(release: dict[str, Any]) -> str:
    return str(release.get("published_at") or release.get("updated_at") or "")


def release_is_formal(release: Any) -> bool:
    return isinstance(release, dict) and not release.get("draft") and not release.get("prerelease")


def fetch_all_releases(repository: str, getter: Callable[[str], Any]) -> list[dict[str, Any]]:
    """Fetch all formal releases for the one-time history initialization."""
    releases: list[dict[str, Any]] = []
    page = 1
    while True:
        payload = getter(github_api_url(repository, f"releases?per_page=100&page={page}"))
        if not isinstance(payload, list):
            raise CatalogError(f"Unexpected release history response for {repository}")
        releases.extend(item for item in payload if release_is_formal(item))
        if len(payload) < 100:
            break
        page += 1
    return releases


def release_entry_key(release: dict[str, Any]) -> tuple[str, str]:
    return (str(release.get("tag_name") or release.get("version") or ""), str(release.get("id") or ""))


def package_matches_release(package: dict[str, Any], release: dict[str, Any]) -> bool:
    tag = release_tag(release)
    pattern = package.get("tag_pattern")
    excluded_pattern = package.get("exclude_tag_pattern")
    try:
        if pattern and not re.search(str(pattern), tag):
            return False
        if excluded_pattern and re.search(str(excluded_pattern), tag):
            return False
    except re.error as error:
        raise CatalogError(f"Invalid release tag pattern for package {package.get('id')}: {error}") from error
    return True


def release_history_signature(source: dict[str, Any]) -> str:
    """Identify the package matching rules used to build release history."""
    payload = [{"history_namespace": source.get("history_namespace", "")}]
    for package in source["packages"]:
        payload.append(
            {
                "id": package.get("id"),
                "tag_pattern": package.get("tag_pattern"),
                "exclude_tag_pattern": package.get("exclude_tag_pattern"),
                "downloads": [
                    {
                        "asset_suffix": download.get("asset_suffix"),
                        "architecture": download.get("architecture"),
                        "label": download.get("label"),
                        "recommended": bool(download.get("recommended")),
                        "optional": bool(download.get("optional")),
                    }
                    for download in package.get("downloads", [])
                ],
            }
        )
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def merge_release_history(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge newly fetched entries before old entries, keeping one copy per package/version."""
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for release in [*incoming, *existing]:
        key = release_entry_key(release)
        if key in seen:
            continue
        seen.add(key)
        merged.append(release)
    return sorted(merged, key=lambda item: str(item.get("updated_at", "")), reverse=True)


def build_release_entries(
    source: dict[str, Any],
    release: dict[str, Any],
    mirrors: list[dict[str, str]],
) -> list[dict[str, Any]]:
    version = release_version(release)
    if not version:
        raise CatalogError(f"Latest release has no version for {source['repository']}")
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise CatalogError(f"Latest release has no assets for {source['repository']}")

    entries = []
    updated_at = release_updated_at(release)
    tag_name = release_tag(release)
    for package in source["packages"]:
        if not package_matches_release(package, release):
            continue
        downloads = []
        for download in package.get("downloads", []):
            suffix = str(download.get("asset_suffix", ""))
            if not suffix:
                raise CatalogError(f"Release download is missing asset_suffix: {package.get('id')}")
            matches = [asset for asset in assets if str(asset.get("name", "")).endswith(suffix)]
            if len(matches) != 1:
                if download.get("optional") and not matches:
                    continue
                raise CatalogError(
                    f"Expected one asset ending with {suffix!r}, found {len(matches)} for {source['repository']}"
                )
            asset = matches[0]
            direct_url = validate_download_url(asset.get("browser_download_url"))
            downloads.append(
                {
                    "filename": asset["name"],
                    "label": download.get("label", asset["name"]),
                    "architecture": download.get("architecture", "unknown"),
                    "recommended": bool(download.get("recommended")),
                    "size": int(asset.get("size") or 0),
                    "url": direct_url,
                    "mirrors": create_mirror_downloads(mirrors, direct_url),
                }
            )
        if not downloads:
            raise CatalogError(f"Release package has no downloads: {package.get('id')}")
        entries.append(
            {
                "id": package["id"],
                "label": package["label"],
                "platform": package["platform"],
                "version": version,
                "tag_name": tag_name,
                "version_code": None,
                "notes": parse_release_notes(release.get("body")),
                "updated_at": updated_at,
                "downloads": downloads,
            }
        )
    if not entries:
        raise CatalogError(f"Release has no matching packages for {source['repository']}: {tag_name}")
    return entries


def build_release_source(
    source: dict[str, Any],
    getter: Callable[[str], Any],
    mirrors: list[dict[str, str]],
    existing_app: dict[str, Any] | None = None,
) -> dict[str, Any]:
    required = ("id", "name", "repository", "packages")
    missing = [key for key in required if not source.get(key)]
    if missing:
        raise CatalogError(f"Release source is missing required fields: {', '.join(missing)}")

    repository = str(source["repository"])
    existing_releases = existing_app.get("releases", []) if isinstance(existing_app, dict) else []
    if not isinstance(existing_releases, list):
        existing_releases = []
    history_signature = release_history_signature(source)
    history_initialized = (
        isinstance(existing_app, dict)
        and existing_app.get("history_complete")
        and existing_app.get("history_signature") == history_signature
    )

    if not history_initialized:
        # A source migration (for example branch files -> GitHub Releases) must
        # rebuild its history so stale download URLs are not retained.
        existing_releases = []
        history = fetch_all_releases(repository, getter)
        if not history:
            raise CatalogError(f"No formal releases found for {repository}")
        latest = max(history, key=release_updated_at)
        incoming: list[dict[str, Any]] = []
        for release in history:
            try:
                incoming.extend(build_release_entries(source, release, mirrors))
            except CatalogError:
                if release is latest:
                    raise
                # Older releases can legitimately have different asset names. Keep the
                # releases whose configured assets are still available.
                continue
    else:
        latest = getter(github_api_url(repository, "releases/latest"))
        if not release_is_formal(latest):
            raise CatalogError(f"Unexpected release response for {repository}")
        latest_tag = release_tag(latest)
        known = {
            (
                str(item.get("tag_name") or item.get("version") or ""),
                str(item.get("id") or ""),
            )
            for item in existing_releases
        }
        expected = {
            (latest_tag, str(package.get("id") or ""))
            for package in source["packages"]
            if package_matches_release(package, latest)
        }
        incoming = [] if expected <= known else build_release_entries(source, latest, mirrors)

    updated_at = release_updated_at(latest)
    releases = merge_release_history(existing_releases, incoming)

    return {
        "id": source["id"],
        "name": source["name"],
        "description": source.get("description", ""),
        "homepage": source.get("homepage", f"https://github.com/{repository}"),
        "repository": repository,
        "icon": source.get("icon", ""),
        "source_revision": latest.get("target_commitish", ""),
        "updated_at": updated_at,
        "history_complete": True,
        "history_signature": history_signature,
        "releases": releases,
    }


def build_source(
    source: dict[str, Any],
    getter: Callable[[str], Any],
    mirrors: list[dict[str, str]],
    existing_app: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if source.get("type") == "github-release":
        return build_release_source(source, getter, mirrors, existing_app)

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

    existing_releases = existing_app.get("releases", []) if isinstance(existing_app, dict) else []
    if not isinstance(existing_releases, list):
        existing_releases = []

    return {
        "id": source["id"],
        "name": source["name"],
        "description": source.get("description", ""),
        "homepage": source.get("homepage", f"https://github.com/{repository}"),
        "repository": repository,
        "icon": source.get("icon", ""),
        "source_revision": source_revision,
        "updated_at": updated_at,
        "history_complete": True,
        "releases": merge_release_history(existing_releases, releases),
    }


def build_catalog(
    config: dict[str, Any],
    getter: Callable[[str], Any],
    existing_catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sources = config.get("sources")
    if not isinstance(sources, list) or not sources:
        raise CatalogError("Config must contain at least one source")

    mirrors = build_mirrors(config)
    existing_apps = {
        app.get("id"): app
        for app in (existing_catalog or {}).get("apps", [])
        if isinstance(app, dict) and app.get("id")
    }
    apps = [build_source(source, getter, mirrors, existing_apps.get(source.get("id"))) for source in sources]
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
        existing_catalog = None
        if args.output.exists():
            try:
                existing_catalog = json.loads(args.output.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing_catalog = None
        catalog = build_catalog(config, lambda url: fetch_json(url, token=token), existing_catalog)
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
