"""
Project scanner — the mechanical (no-LLM) part of ingestion.

Turns a raw folder (from clone_repo / extract_zip) into a structured
`project_snapshot`:
    file_tree     -> clean nested tree with noise filtered out
    languages     -> file counts by extension + primary language
    project_type  -> detected via marker files
    entry_points  -> likely starting files
    size_stats    -> total files / dirs / bytes

This maps to Steps 2-3 of the workflow and IngestionAgent's output in CLAUDE.md.
"""

from __future__ import annotations

import os

# Directories that are build artifacts, dependencies, or VCS internals.
# Filtered out so the tree reflects the actual source.
NOISE_DIRS = {
    ".git", ".hg", ".svn",
    "node_modules", "bower_components",
    "dist", "build", "out", "target",
    ".venv", "venv", "env", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".idea", ".vscode",
    ".next", ".nuxt", ".cache", "coverage",
    "vendor", ".gradle",
}

# Individual files to ignore in the tree/counts.
NOISE_FILES = {".DS_Store", "Thumbs.db"}

# Marker file -> project type. First match (by priority order) wins.
PROJECT_MARKERS = [
    ("javascript", ["package.json"]),
    ("python", ["pyproject.toml", "requirements.txt", "setup.py", "Pipfile"]),
    ("java", ["pom.xml", "build.gradle", "build.gradle.kts"]),
    ("go", ["go.mod"]),
    ("rust", ["Cargo.toml"]),
    ("ruby", ["Gemfile"]),
    ("php", ["composer.json"]),
    ("dotnet", ["*.csproj", "*.sln"]),
]

# Common entry-point filenames by project type.
ENTRY_POINTS = {
    "python": ["main.py", "app.py", "manage.py", "run.py", "__main__.py", "wsgi.py", "asgi.py"],
    "javascript": ["index.js", "server.js", "app.js", "main.js", "index.ts", "server.ts", "main.ts"],
    "java": ["Main.java", "Application.java"],
    "go": ["main.go"],
    "rust": ["main.rs"],
    "ruby": ["main.rb", "app.rb", "config.ru"],
    "php": ["index.php"],
    "dotnet": ["Program.cs"],
}

# Reverse lookup for exact-name markers -> project type (built from
# PROJECT_MARKERS). Wildcard markers (e.g. "*.csproj") are handled separately.
_MARKER_TO_TYPE = {
    marker: ptype
    for ptype, markers in PROJECT_MARKERS
    for marker in markers
    if not marker.startswith("*")
}
_WILDCARD_MARKERS = [
    (marker[1:], ptype)  # (".csproj", "dotnet")
    for ptype, markers in PROJECT_MARKERS
    for marker in markers
    if marker.startswith("*")
]

# Map file extension -> language label for the language breakdown.
_EXT_LANG = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".java": "Java", ".go": "Go", ".rs": "Rust",
    ".rb": "Ruby", ".php": "PHP", ".cs": "C#",
    ".c": "C", ".h": "C", ".cpp": "C++", ".cc": "C++", ".hpp": "C++",
    ".html": "HTML", ".css": "CSS", ".scss": "CSS",
    ".json": "JSON", ".yaml": "YAML", ".yml": "YAML",
    ".md": "Markdown", ".sh": "Shell", ".sql": "SQL",
}


def _is_noise_dir(name: str) -> bool:
    return name in NOISE_DIRS


def _is_noise_file(name: str) -> bool:
    return name in NOISE_FILES


def scan_file_tree(root: str) -> dict:
    """
    Walk `root` and return a nested dict tree with noise filtered out.

    Shape:
        {"name": "<dir>", "type": "dir",
         "children": [ {"name": "x.py", "type": "file"}, {...dir...} ]}
    """
    root = os.path.abspath(root)

    def build(path: str) -> dict:
        node = {"name": os.path.basename(path) or path, "type": "dir", "children": []}
        try:
            entries = sorted(os.scandir(path), key=lambda e: (e.is_file(), e.name.lower()))
        except OSError:
            return node

        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                if _is_noise_dir(entry.name):
                    continue
                node["children"].append(build(entry.path))
            elif entry.is_file(follow_symlinks=False):
                if _is_noise_file(entry.name):
                    continue
                node["children"].append({"name": entry.name, "type": "file"})
        return node

    return build(root)


def _iter_files(root: str):
    """Yield absolute paths of all non-noise files under root."""
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune noise dirs in place so os.walk doesn't descend into them.
        dirnames[:] = [d for d in dirnames if not _is_noise_dir(d)]
        for fname in filenames:
            if _is_noise_file(fname):
                continue
            yield os.path.join(dirpath, fname)


def detect_languages(root: str) -> dict:
    """
    Count files per extension and derive a language breakdown.

    Returns:
        {"by_extension": {".py": 12, ...},
         "by_language": {"Python": 12, ...},
         "primary": "Python" | None}
    """
    by_ext: dict[str, int] = {}
    by_lang: dict[str, int] = {}

    for fpath in _iter_files(root):
        ext = os.path.splitext(fpath)[1].lower()
        if not ext:
            continue
        by_ext[ext] = by_ext.get(ext, 0) + 1
        lang = _EXT_LANG.get(ext)
        if lang:
            by_lang[lang] = by_lang.get(lang, 0) + 1

    primary = max(by_lang, key=by_lang.get) if by_lang else None
    return {
        "by_extension": dict(sorted(by_ext.items(), key=lambda kv: -kv[1])),
        "by_language": dict(sorted(by_lang.items(), key=lambda kv: -kv[1])),
        "primary": primary,
    }


def _marker_type_for_dir(filenames: list[str]) -> tuple[str, list[str]] | None:
    """
    Given the filenames in a single directory, return (type, [matched markers])
    if any project marker is present, else None. A directory can match multiple
    markers of the same type (e.g. requirements.txt + setup.py).
    """
    matched: dict[str, list[str]] = {}
    for name in filenames:
        ptype = _MARKER_TO_TYPE.get(name)
        if ptype:
            matched.setdefault(ptype, []).append(name)
        else:
            for suffix, wtype in _WILDCARD_MARKERS:
                if name.endswith(suffix):
                    matched.setdefault(wtype, []).append(name)

    if not matched:
        return None
    # If a dir somehow has markers for multiple types, prefer PROJECT_MARKERS order.
    for ptype, _ in PROJECT_MARKERS:
        if ptype in matched:
            return ptype, sorted(matched[ptype])
    return None


def detect_sub_projects(root: str) -> list[dict]:
    """
    Walk the whole tree (skipping noise) and find every directory that holds
    project marker files. Each such directory is reported as one sub-project.

    Handles monorepos: e.g. backend/ (Python) + frontend/ (JS) + service/ (Java)
    each become a separate entry.

    Returns a list of:
        {"type": "python", "path": "backend", "markers": ["requirements.txt"],
         "entry_points": ["backend/main.py"]}
    sorted shallowest-path first. Paths are repo-relative ("." for root).
    """
    root = os.path.abspath(root)
    sub_projects: list[dict] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _is_noise_dir(d)]
        match = _marker_type_for_dir(filenames)
        if match is None:
            continue

        ptype, markers = match
        rel = os.path.relpath(dirpath, root).replace(os.sep, "/")
        sub_projects.append(
            {
                "type": ptype,
                "path": rel,
                "markers": markers,
                "entry_points": find_entry_points(dirpath, ptype, root),
            }
        )

    sub_projects.sort(key=lambda sp: (sp["path"].count("/"), sp["path"]))
    return sub_projects


def find_entry_points(scan_dir: str, project_type: str, rel_base: str | None = None) -> list[str]:
    """
    Find likely entry-point files for a project type within `scan_dir`.

    Returns paths relative to `rel_base` (defaults to `scan_dir`), nearest-to-
    root first — so entry points read naturally against the repo root.
    """
    wanted = set(ENTRY_POINTS.get(project_type, []))
    if not wanted:
        return []

    base = os.path.abspath(rel_base) if rel_base else os.path.abspath(scan_dir)

    found: list[tuple[int, str]] = []
    for fpath in _iter_files(scan_dir):
        if os.path.basename(fpath) in wanted:
            rel = os.path.relpath(fpath, base).replace(os.sep, "/")
            depth = rel.count("/")
            found.append((depth, rel))

    found.sort()  # shallow paths first
    return [rel for _, rel in found]


def get_size_stats(root: str) -> dict:
    """Return total file count, directory count, and total size in bytes."""
    total_files = 0
    total_size = 0
    dir_count = 0

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _is_noise_dir(d)]
        dir_count += len(dirnames)
        for fname in filenames:
            if _is_noise_file(fname):
                continue
            total_files += 1
            try:
                total_size += os.path.getsize(os.path.join(dirpath, fname))
            except OSError:
                pass

    return {
        "total_files": total_files,
        "total_dirs": dir_count,
        "total_size_bytes": total_size,
    }


def build_project_snapshot(root: str) -> dict:
    """
    Assemble the full project_snapshot for a freshly ingested project.

    This is the single entry point IngestionAgent (and the endpoints) call.

    `project_type` is:
      - the single sub-project's type, if exactly one was found,
      - "multi" if more than one distinct type was found (monorepo),
      - "unknown" if no markers were found at all.
    `entry_points` aggregates entry points across all sub-projects.
    """
    sub_projects = detect_sub_projects(root)

    distinct_types = {sp["type"] for sp in sub_projects}
    if not sub_projects:
        project_type = "unknown"
    elif len(distinct_types) == 1:
        project_type = next(iter(distinct_types))
    else:
        project_type = "multi"

    entry_points = [ep for sp in sub_projects for ep in sp["entry_points"]]

    return {
        "root_path": os.path.abspath(root),
        "project_type": project_type,
        "sub_projects": sub_projects,
        "languages": detect_languages(root),
        "entry_points": entry_points,
        "size_stats": get_size_stats(root),
        "file_tree": scan_file_tree(root),
    }
