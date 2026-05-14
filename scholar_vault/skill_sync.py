from __future__ import annotations

import hashlib
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

IGNORED_NAMES = {".DS_Store", ".sync-backups"}
AGENTS_GUIDE_ITEM = "AGENTS.md"
VAULT_AGENT_SKILLS_DIR = "vault-agent-skills"


@dataclass(frozen=True)
class SkillSyncPaths:
    source: Path
    target: Path


def default_source_skills_path() -> Path:
    return Path(__file__).resolve().parents[1] / VAULT_AGENT_SKILLS_DIR


def default_source_agents_path() -> Path:
    return Path(__file__).resolve().parents[1] / "VAULT_AGENTS_TEMPLATE.md"


def vault_skills_path(vault: Path | str) -> Path:
    return Path(vault).expanduser().resolve() / ".agents" / "skills"


def vault_agents_path(vault: Path | str) -> Path:
    return Path(vault).expanduser().resolve() / AGENTS_GUIDE_ITEM


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


def _mtime(path: Path | None) -> float | None:
    if path is None:
        return None
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _format_mtime(value: float | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value).astimezone().isoformat(timespec="seconds")


def _newer_side(source_mtime: float | None, target_mtime: float | None) -> str:
    if source_mtime is None and target_mtime is None:
        return "unknown"
    if source_mtime is None:
        return "target"
    if target_mtime is None:
        return "source"
    if abs(source_mtime - target_mtime) < 1:
        return "same-time"
    return "source" if source_mtime > target_mtime else "target"


def _timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")


def _backup_path(root: Path, skill: str) -> Path:
    return root / ".sync-backups" / _timestamp() / skill


def _copy_skill(source_skill: Path, target_skill: Path) -> None:
    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in IGNORED_NAMES}

    target_skill.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_skill, target_skill, dirs_exist_ok=True, ignore=ignore)


def _copy_file(source_file: Path, target_file: Path) -> None:
    target_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, target_file)


def _copy_backup(existing: Path, backup_root: Path, skill: str) -> Path | None:
    if not existing.exists():
        return None
    backup = _backup_path(backup_root, skill)
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(existing, backup, dirs_exist_ok=True)
    return backup


def _copy_file_backup(existing: Path, backup_root: Path, name: str) -> Path | None:
    if not existing.exists():
        return None
    backup = _backup_path(backup_root, name)
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(existing, backup)
    return backup


def _skill_status(summary: dict[str, Any], skill: str) -> str:
    agent_guide = summary.get("agent_guide")
    if skill == AGENTS_GUIDE_ITEM and agent_guide:
        return str(agent_guide["status"])
    for row in summary["skills"]:
        if row["skill"] == skill:
            return str(row["status"])
    return "missing"


def _sync_row(
    *,
    item: str,
    kind: str,
    path_label: str,
    source_path: Path,
    target_path: Path,
) -> dict[str, Any] | None:
    source_exists = source_path.is_file()
    target_exists = target_path.is_file()
    if not source_exists and not target_exists:
        return None
    source_mtime = _mtime(source_path if source_exists else None)
    target_mtime = _mtime(target_path if target_exists else None)
    if not source_exists:
        status = "target-only"
    elif not target_exists:
        status = "source-only"
    else:
        status = "identical" if _sha256(source_path) == _sha256(target_path) else "changed"
    files: list[dict[str, Any]] = []
    if status != "identical":
        files.append(
            {
                "path": path_label,
                "skill": item,
                "status": status,
                "source_mtime": source_mtime,
                "target_mtime": target_mtime,
                "source_modified": _format_mtime(source_mtime),
                "target_modified": _format_mtime(target_mtime),
                "newer": _newer_side(source_mtime, target_mtime),
            }
        )
    newer = _newer_side(source_mtime, target_mtime) if files else "same-time"
    if status == "source-only":
        recommendation = "publish"
    elif status == "target-only":
        recommendation = "adopt"
    elif status == "changed" and newer == "source":
        recommendation = "publish"
    elif status == "changed" and newer == "target":
        recommendation = "adopt"
    elif status == "changed":
        recommendation = "review"
    else:
        recommendation = "none"
    return {
        "skill": item,
        "kind": kind,
        "status": status,
        "changed_files": len(files),
        "files": files,
        "source": str(source_path),
        "target": str(target_path),
        "source_modified": _format_mtime(source_mtime),
        "target_modified": _format_mtime(target_mtime),
        "newer": newer,
        "recommendation": recommendation,
    }


def compare_skillsets(
    source: Path | str,
    target: Path | str,
    *,
    source_agent_guide: Path | str | None = None,
    target_agent_guide: Path | str | None = None,
) -> dict[str, Any]:
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
        source_mtime = _mtime(source_path)
        target_mtime = _mtime(target_path)
        if source_path is None:
            status = "target-only"
        elif target_path is None:
            status = "source-only"
        else:
            status = "identical" if _sha256(source_path) == _sha256(target_path) else "changed"
        if status != "identical":
            file_rows.append(
                {
                    "path": relative,
                    "skill": relative.split("/", 1)[0],
                    "status": status,
                    "source_mtime": source_mtime,
                    "target_mtime": target_mtime,
                    "source_modified": _format_mtime(source_mtime),
                    "target_modified": _format_mtime(target_mtime),
                    "newer": _newer_side(source_mtime, target_mtime),
                }
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
        source_mtimes = [
            row["source_mtime"] for row in changed_files if row.get("source_mtime") is not None
        ]
        target_mtimes = [
            row["target_mtime"] for row in changed_files if row.get("target_mtime") is not None
        ]
        source_mtime = max(source_mtimes) if source_mtimes else None
        target_mtime = max(target_mtimes) if target_mtimes else None
        newer = _newer_side(source_mtime, target_mtime) if changed_files else "same-time"
        if status == "source-only":
            recommendation = "publish"
        elif status == "target-only":
            recommendation = "adopt"
        elif status == "changed" and newer == "source":
            recommendation = "publish"
        elif status == "changed" and newer == "target":
            recommendation = "adopt"
        elif status == "changed":
            recommendation = "review"
        else:
            recommendation = "none"
        skills.append(
            {
                "skill": skill,
                "status": status,
                "changed_files": len(changed_files),
                "files": changed_files,
                "source_modified": _format_mtime(source_mtime),
                "target_modified": _format_mtime(target_mtime),
                "newer": newer,
                "recommendation": recommendation,
            }
        )

    counts = {
        "identical": sum(1 for row in skills if row["status"] == "identical"),
        "changed": sum(1 for row in skills if row["status"] == "changed"),
        "source_only": sum(1 for row in skills if row["status"] == "source-only"),
        "target_only": sum(1 for row in skills if row["status"] == "target-only"),
    }
    agent_guide = None
    if source_agent_guide is not None and target_agent_guide is not None:
        agent_guide = _sync_row(
            item=AGENTS_GUIDE_ITEM,
            kind="agent-guide",
            path_label=AGENTS_GUIDE_ITEM,
            source_path=Path(source_agent_guide).expanduser().resolve(),
            target_path=Path(target_agent_guide).expanduser().resolve(),
        )

    return {
        "source": str(source_root),
        "target": str(target_root),
        "source_agent_guide": str(Path(source_agent_guide).expanduser().resolve())
        if source_agent_guide is not None
        else None,
        "target_agent_guide": str(Path(target_agent_guide).expanduser().resolve())
        if target_agent_guide is not None
        else None,
        "agent_guide": agent_guide,
        "counts": counts,
        "skills": skills,
        "files": file_rows,
    }


def format_skillset_summary(summary: dict[str, Any]) -> str:
    source_newer = sum(
        1 for row in summary["skills"] if row["status"] == "changed" and row["newer"] == "source"
    )
    target_newer = sum(
        1 for row in summary["skills"] if row["status"] == "changed" and row["newer"] == "target"
    )
    unclear_newer = sum(
        1
        for row in summary["skills"]
        if row["status"] == "changed" and row["newer"] not in {"source", "target"}
    )
    lines = [
        "Roles:",
        f"- Repository source (canonical vault-agent skills): {summary['source']}",
        f"- Vault target (installed skills): {summary['target']}",
        "Actions:",
        "- Update vault from repository: publish source -> target.",
        "- Keep vault-side edits: adopt selected target skill -> source.",
        (
            "- Newer-side hints use file modification times; they are guidance, not proof "
            "of intent."
        ),
        (
            "Counts: "
            f"identical={summary['counts']['identical']}, "
            f"changed={summary['counts']['changed']}, "
            f"source-only={summary['counts']['source_only']}, "
            f"target-only={summary['counts']['target_only']}"
        ),
        (
            "Changed mtimes: "
            f"source-newer={source_newer}, "
            f"target-newer={target_newer}, "
            f"unclear={unclear_newer}"
        ),
    ]
    agent_guide = summary.get("agent_guide")
    if agent_guide:
        lines.extend(
            [
                f"- Repository source agent guide: {agent_guide['source']}",
                f"- Vault target agent guide: {agent_guide['target']}",
            ]
        )
    difference_count = 0
    for row in summary["skills"]:
        if row["status"] == "identical":
            continue
        difference_count += 1
        status = str(row["status"])
        if status == "changed":
            newer = row.get("newer")
            if newer == "source":
                hint = "repository source appears newer; publish updates vault target"
            elif newer == "target":
                hint = "vault target appears newer; adopt pulls vault copy into repo"
            else:
                hint = "mtime unclear; inspect before choosing a direction"
            description = f"changed; {hint}"
        elif status == "source-only":
            description = "source-only; publish adds it to the vault target"
        elif status == "target-only":
            description = "target-only; adopt pulls it into the repo source"
        else:
            description = status
        lines.append(f"- {row['skill']}: {description}")
        for file_row in row["files"][:8]:
            lines.append(f"  - {file_row['status']}: {file_row['path']}")
        if len(row["files"]) > 8:
            lines.append(f"  - ... {len(row['files']) - 8} more file(s)")
    if agent_guide and agent_guide["status"] != "identical":
        difference_count += 1
        status = str(agent_guide["status"])
        if status == "changed":
            newer = agent_guide.get("newer")
            if newer == "source":
                hint = "repository template appears newer; publish updates vault AGENTS.md"
            elif newer == "target":
                hint = "vault AGENTS.md appears newer; adopt pulls it into the template"
            else:
                hint = "mtime unclear; inspect before choosing a direction"
            description = f"changed; {hint}"
        elif status == "source-only":
            description = "source-only; publish creates vault AGENTS.md"
        elif status == "target-only":
            description = "target-only; adopt pulls it into VAULT_AGENTS_TEMPLATE.md"
        else:
            description = status
        lines.append(f"- {agent_guide['skill']}: {description}")
        for file_row in agent_guide["files"][:8]:
            lines.append(f"  - {file_row['status']}: {file_row['path']}")
    if difference_count == 0:
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
    source_agent_guide: Path | str | None = None,
    target_agent_guide: Path | str | None = None,
) -> dict[str, Any]:
    source_root = Path(source).expanduser().resolve()
    target_root = Path(target).expanduser().resolve()
    if skill == AGENTS_GUIDE_ITEM:
        if source_agent_guide is None or target_agent_guide is None:
            raise ValueError("AGENTS.md sync requires source_agent_guide and target_agent_guide")
        source_file = Path(source_agent_guide).expanduser().resolve()
        target_file = Path(target_agent_guide).expanduser().resolve()
        if not target_file.is_file():
            raise FileNotFoundError(f"Target agent guide does not exist: {target_file}")
        summary = compare_skillsets(
            source_root,
            target_root,
            source_agent_guide=source_file,
            target_agent_guide=target_file,
        )
        status = _skill_status(summary, skill)
        if source_file.exists() and status != "identical" and not force:
            return {
                "action": "blocked",
                "reason": (
                    "source agent guide already exists and differs; "
                    "pass --force to overwrite"
                ),
                "skill": skill,
                "source": str(source_file),
                "target": str(target_file),
                "apply": apply,
                "agent_guide": {"copied": False},
            }
        result: dict[str, Any] = {
            "action": "adopt",
            "skill": skill,
            "from": str(target_file),
            "to": str(source_file),
            "apply": apply,
            "backup": None,
            "agent_guide": {"copied": False},
        }
        if not apply:
            return result
        if source_file.exists() and backup:
            backup_path = _copy_file_backup(source_file, source_root, skill)
            result["backup"] = str(backup_path) if backup_path else None
        _copy_file(target_file, source_file)
        result["action"] = "adopted"
        result["agent_guide"] = {"copied": True}
        return result

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
    skills: Iterable[str] | None = None,
    source_agent_guide: Path | str | None = None,
    target_agent_guide: Path | str | None = None,
) -> dict[str, Any]:
    source_root = Path(source).expanduser().resolve()
    target_root = Path(target).expanduser().resolve()
    summary = compare_skillsets(
        source_root,
        target_root,
        source_agent_guide=source_agent_guide,
        target_agent_guide=target_agent_guide,
    )
    selected = set(skills) if skills is not None else None
    skills_to_copy = [
        row["skill"]
        for row in summary["skills"]
        if row["status"] in {"source-only", "changed"}
        and (selected is None or row["skill"] in selected)
    ]
    target_only = [
        row["skill"]
        for row in summary["skills"]
        if row["status"] == "target-only" and (selected is None or row["skill"] in selected)
    ]
    agent_guide = summary.get("agent_guide")
    copy_agent_guide = (
        bool(agent_guide)
        and agent_guide["status"] in {"source-only", "changed"}
        and (selected is None or AGENTS_GUIDE_ITEM in selected)
    )
    result: dict[str, Any] = {
        "action": "publish",
        "source": str(source_root),
        "target": str(target_root),
        "apply": apply,
        "copied": skills_to_copy,
        "target_only": target_only,
        "agent_guide": {
            "copied": copy_agent_guide,
            "status": agent_guide["status"] if agent_guide else None,
            "source": agent_guide["source"] if agent_guide else None,
            "target": agent_guide["target"] if agent_guide else None,
        },
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
    if copy_agent_guide and agent_guide:
        source_file = Path(agent_guide["source"])
        target_file = Path(agent_guide["target"])
        if target_file.exists() and backup:
            backup_path = _copy_file_backup(target_file, target_root, AGENTS_GUIDE_ITEM)
            if backup_path:
                result["backups"].append(str(backup_path))
        _copy_file(source_file, target_file)
    if archive_extra:
        for skill in target_only:
            target_skill = target_root / skill
            archive_path = _backup_path(target_root, skill)
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target_skill), str(archive_path))
            result["archived"].append(str(archive_path))
    result["action"] = "published"
    return result
