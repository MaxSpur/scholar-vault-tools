from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

IGNORED_NAMES = {".DS_Store", ".sync-backups"}


@dataclass(frozen=True)
class SkillSyncPaths:
    source: Path
    target: Path


def default_source_skills_path() -> Path:
    return Path(__file__).resolve().parents[1] / ".agents" / "skills"


def vault_skills_path(vault: Path | str) -> Path:
    return Path(vault).expanduser().resolve() / ".agents" / "skills"


def _is_ignored(path: Path) -> bool:
    return any(part in IGNORED_NAMES for part in path.parts)


def _files(root: Path) -> dict[str, Path]:
    if not root.exists():
        return {}
    files: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.is_file():
            relative = path.relative_to(root)
            if not _is_ignored(relative):
                files[relative.as_posix()] = path
    return files


def _skill_dirs(root: Path) -> set[str]:
    if not root.exists():
        return set()
    return {
        path.name
        for path in root.iterdir()
        if path.is_dir() and not _is_ignored(Path(path.name))
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")


def _backup_path(root: Path, skill: str) -> Path:
    return root / ".sync-backups" / _timestamp() / skill


def _copy_skill(source_skill: Path, target_skill: Path) -> None:
    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in IGNORED_NAMES}

    target_skill.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_skill, target_skill, dirs_exist_ok=True, ignore=ignore)


def _copy_backup(existing: Path, backup_root: Path, skill: str) -> Path | None:
    if not existing.exists():
        return None
    backup = _backup_path(backup_root, skill)
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(existing, backup, dirs_exist_ok=True)
    return backup


def _skill_status(summary: dict[str, Any], skill: str) -> str:
    for row in summary["skills"]:
        if row["skill"] == skill:
            return str(row["status"])
    return "missing"


def compare_skillsets(source: Path | str, target: Path | str) -> dict[str, Any]:
    source_root = Path(source).expanduser().resolve()
    target_root = Path(target).expanduser().resolve()
    source_files = _files(source_root)
    target_files = _files(target_root)
    source_skills = _skill_dirs(source_root)
    target_skills = _skill_dirs(target_root)

    file_rows: list[dict[str, Any]] = []
    for relative in sorted(set(source_files) | set(target_files)):
        source_path = source_files.get(relative)
        target_path = target_files.get(relative)
        if source_path is None:
            status = "target-only"
        elif target_path is None:
            status = "source-only"
        else:
            status = "identical" if _sha256(source_path) == _sha256(target_path) else "changed"
        if status != "identical":
            file_rows.append(
                {"path": relative, "skill": relative.split("/", 1)[0], "status": status}
            )

    skills: list[dict[str, Any]] = []
    for skill in sorted(source_skills | target_skills):
        if skill not in source_skills:
            status = "target-only"
        elif skill not in target_skills:
            status = "source-only"
        elif any(row["skill"] == skill for row in file_rows):
            status = "changed"
        else:
            status = "identical"
        changed_files = [row for row in file_rows if row["skill"] == skill]
        skills.append(
            {
                "skill": skill,
                "status": status,
                "changed_files": len(changed_files),
                "files": changed_files,
            }
        )

    counts = {
        "identical": sum(1 for row in skills if row["status"] == "identical"),
        "changed": sum(1 for row in skills if row["status"] == "changed"),
        "source_only": sum(1 for row in skills if row["status"] == "source-only"),
        "target_only": sum(1 for row in skills if row["status"] == "target-only"),
    }
    return {
        "source": str(source_root),
        "target": str(target_root),
        "counts": counts,
        "skills": skills,
        "files": file_rows,
    }


def format_skillset_summary(summary: dict[str, Any]) -> str:
    lines = [
        f"Source: {summary['source']}",
        f"Target: {summary['target']}",
        (
            "Counts: "
            f"identical={summary['counts']['identical']}, "
            f"changed={summary['counts']['changed']}, "
            f"source-only={summary['counts']['source_only']}, "
            f"target-only={summary['counts']['target_only']}"
        ),
    ]
    for row in summary["skills"]:
        if row["status"] == "identical":
            continue
        lines.append(f"- {row['skill']}: {row['status']}")
        for file_row in row["files"][:8]:
            lines.append(f"  - {file_row['status']}: {file_row['path']}")
        if len(row["files"]) > 8:
            lines.append(f"  - ... {len(row['files']) - 8} more file(s)")
    if len(lines) == 3:
        lines.append("- No content differences.")
    return "\n".join(lines)


def adopt_skill(
    source: Path | str,
    target: Path | str,
    skill: str,
    *,
    apply: bool = False,
    force: bool = False,
    backup: bool = True,
) -> dict[str, Any]:
    source_root = Path(source).expanduser().resolve()
    target_root = Path(target).expanduser().resolve()
    source_skill = source_root / skill
    target_skill = target_root / skill
    if not target_skill.is_dir():
        raise FileNotFoundError(f"Target skill does not exist: {target_skill}")

    summary = compare_skillsets(source_root, target_root)
    status = _skill_status(summary, skill)
    if source_skill.exists() and status != "identical" and not force:
        return {
            "action": "blocked",
            "reason": "source skill already exists and differs; pass --force to overwrite",
            "skill": skill,
            "source": str(source_skill),
            "target": str(target_skill),
            "apply": apply,
        }

    result: dict[str, Any] = {
        "action": "adopt",
        "skill": skill,
        "from": str(target_skill),
        "to": str(source_skill),
        "apply": apply,
        "backup": None,
    }
    if not apply:
        return result
    if source_skill.exists() and backup:
        backup_path = _copy_backup(source_skill, source_root, skill)
        result["backup"] = str(backup_path) if backup_path else None
    _copy_skill(target_skill, source_skill)
    result["action"] = "adopted"
    return result


def publish_skillset(
    source: Path | str,
    target: Path | str,
    *,
    apply: bool = False,
    archive_extra: bool = False,
    backup: bool = True,
) -> dict[str, Any]:
    source_root = Path(source).expanduser().resolve()
    target_root = Path(target).expanduser().resolve()
    summary = compare_skillsets(source_root, target_root)
    skills_to_copy = [
        row["skill"]
        for row in summary["skills"]
        if row["status"] in {"source-only", "changed"}
    ]
    target_only = [
        row["skill"] for row in summary["skills"] if row["status"] == "target-only"
    ]
    result: dict[str, Any] = {
        "action": "publish",
        "source": str(source_root),
        "target": str(target_root),
        "apply": apply,
        "copied": skills_to_copy,
        "target_only": target_only,
        "archived": [],
        "backups": [],
    }
    if not apply:
        return result
    target_root.mkdir(parents=True, exist_ok=True)
    for skill in skills_to_copy:
        source_skill = source_root / skill
        target_skill = target_root / skill
        if target_skill.exists() and backup:
            backup_path = _copy_backup(target_skill, target_root, skill)
            if backup_path:
                result["backups"].append(str(backup_path))
        _copy_skill(source_skill, target_skill)
    if archive_extra:
        for skill in target_only:
            target_skill = target_root / skill
            archive_path = _backup_path(target_root, skill)
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target_skill), str(archive_path))
            result["archived"].append(str(archive_path))
    result["action"] = "published"
    return result
