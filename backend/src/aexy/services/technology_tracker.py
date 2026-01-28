"""Technology Evolution Tracking Service.

Tracks framework/library versions and technology adoption:
- Version detection from dependency files
- Deprecated technology flagging
- Upgrade path suggestions
- Technology adoption trends
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.activity import Commit, PullRequest
from aexy.models.developer import Developer

logger = logging.getLogger(__name__)


class TechnologyStatus(Enum):
    """Status of a technology version."""
    CURRENT = "current"  # Latest stable
    RECENT = "recent"  # Within 1-2 major versions
    OUTDATED = "outdated"  # 2+ major versions behind
    DEPRECATED = "deprecated"  # End of life
    UNKNOWN = "unknown"


class TechnologyCategory(Enum):
    """Categories of technologies."""
    FRAMEWORK = "framework"
    LIBRARY = "library"
    LANGUAGE = "language"
    TOOL = "tool"
    DATABASE = "database"
    RUNTIME = "runtime"


@dataclass
class TechnologyVersion:
    """Information about a detected technology version."""
    name: str
    version: str | None
    category: TechnologyCategory
    status: TechnologyStatus
    latest_version: str | None = None
    detected_from: str = ""  # File where detected
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    usage_count: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "version": self.version,
            "category": self.category.value,
            "status": self.status.value,
            "latest_version": self.latest_version,
            "detected_from": self.detected_from,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "usage_count": self.usage_count,
        }


@dataclass
class TechnologyProfile:
    """Developer's technology profile with version tracking."""
    developer_id: str
    technologies: list[TechnologyVersion] = field(default_factory=list)
    current_count: int = 0
    outdated_count: int = 0
    deprecated_count: int = 0
    adoption_score: float = 0.0  # How up-to-date they stay
    upgrade_suggestions: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "developer_id": self.developer_id,
            "technologies": [t.to_dict() for t in self.technologies],
            "current_count": self.current_count,
            "outdated_count": self.outdated_count,
            "deprecated_count": self.deprecated_count,
            "adoption_score": self.adoption_score,
            "upgrade_suggestions": self.upgrade_suggestions,
        }


# Current/latest versions for popular technologies (as of 2026)
TECHNOLOGY_VERSIONS = {
    # JavaScript Frameworks
    "react": {"latest": "19.0", "deprecated": ["16", "15"], "category": "framework"},
    "vue": {"latest": "3.5", "deprecated": ["2.0", "2.1", "2.2", "2.3", "2.4", "2.5"], "category": "framework"},
    "angular": {"latest": "18.0", "deprecated": ["8", "9", "10", "11", "12"], "category": "framework"},
    "next": {"latest": "15.0", "deprecated": ["11", "12"], "category": "framework"},
    "svelte": {"latest": "5.0", "deprecated": ["3"], "category": "framework"},

    # Backend Frameworks
    "fastapi": {"latest": "0.115", "deprecated": [], "category": "framework"},
    "django": {"latest": "5.1", "deprecated": ["2.2", "3.0", "3.1"], "category": "framework"},
    "flask": {"latest": "3.1", "deprecated": ["1.0", "1.1"], "category": "framework"},
    "express": {"latest": "5.0", "deprecated": ["3", "4.0", "4.1"], "category": "framework"},
    "nestjs": {"latest": "11.0", "deprecated": ["7", "8"], "category": "framework"},
    "spring-boot": {"latest": "3.3", "deprecated": ["2.0", "2.1", "2.2", "2.3"], "category": "framework"},

    # Languages/Runtimes
    "python": {"latest": "3.13", "deprecated": ["2.7", "3.6", "3.7", "3.8"], "category": "runtime"},
    "node": {"latest": "22.0", "deprecated": ["14", "16"], "category": "runtime"},
    "typescript": {"latest": "5.5", "deprecated": ["3", "4.0", "4.1", "4.2"], "category": "language"},
    "rust": {"latest": "1.78", "deprecated": [], "category": "language"},
    "go": {"latest": "1.23", "deprecated": ["1.18", "1.19"], "category": "language"},

    # Databases
    "postgresql": {"latest": "17", "deprecated": ["11", "12"], "category": "database"},
    "mongodb": {"latest": "8.0", "deprecated": ["4.0", "4.2", "4.4"], "category": "database"},
    "redis": {"latest": "7.4", "deprecated": ["5", "6.0"], "category": "database"},

    # Tools
    "docker": {"latest": "26.0", "deprecated": ["19", "20"], "category": "tool"},
    "kubernetes": {"latest": "1.31", "deprecated": ["1.24", "1.25", "1.26"], "category": "tool"},
    "terraform": {"latest": "1.9", "deprecated": ["0.12", "0.13", "0.14"], "category": "tool"},

    # Libraries
    "axios": {"latest": "1.7", "deprecated": ["0.21", "0.22", "0.23"], "category": "library"},
    "lodash": {"latest": "4.17", "deprecated": ["3"], "category": "library"},
    "sqlalchemy": {"latest": "2.0", "deprecated": ["1.3", "1.2"], "category": "library"},
    "pydantic": {"latest": "2.9", "deprecated": ["1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "1.8", "1.9"], "category": "library"},
    "pytest": {"latest": "8.3", "deprecated": ["5", "6"], "category": "library"},
    "jest": {"latest": "30.0", "deprecated": ["26", "27"], "category": "library"},

    # UI Libraries
    "tailwindcss": {"latest": "4.0", "deprecated": ["1", "2"], "category": "library"},
    "material-ui": {"latest": "6.0", "deprecated": ["4"], "category": "library"},
    "chakra-ui": {"latest": "3.0", "deprecated": ["1"], "category": "library"},
}


class TechnologyTracker:
    """Tracks technology versions and evolution."""

    # Dependency file patterns
    DEPENDENCY_FILES = {
        "package.json": "npm",
        "package-lock.json": "npm",
        "yarn.lock": "yarn",
        "requirements.txt": "pip",
        "pyproject.toml": "python",
        "Pipfile": "pipenv",
        "Cargo.toml": "cargo",
        "go.mod": "go",
        "Gemfile": "bundler",
        "composer.json": "composer",
        "build.gradle": "gradle",
        "pom.xml": "maven",
    }

    # Version extraction patterns
    VERSION_PATTERNS = {
        "npm": [
            r'"(\w+)"\s*:\s*"[\^~]?(\d+\.\d+(?:\.\d+)?)"',  # "package": "^1.2.3"
            r'"(\w+[-/]\w+)"\s*:\s*"[\^~]?(\d+\.\d+(?:\.\d+)?)"',  # "@scope/package": "1.2.3"
        ],
        "pip": [
            r'^([a-zA-Z0-9_-]+)==(\d+\.\d+(?:\.\d+)?)',  # package==1.2.3
            r'^([a-zA-Z0-9_-]+)>=(\d+\.\d+(?:\.\d+)?)',  # package>=1.2.3
            r'^([a-zA-Z0-9_-]+)\[.*\]==(\d+\.\d+(?:\.\d+)?)',  # package[extras]==1.2.3
        ],
        "python": [
            r'python\s*=\s*"[\^>=]*(\d+\.\d+)"',  # python = "^3.11"
            r'"([a-zA-Z0-9_-]+)"\s*=\s*"[\^>=]*(\d+\.\d+(?:\.\d+)?)"',  # "package" = "^1.2.3"
        ],
        "cargo": [
            r'(\w+)\s*=\s*"(\d+\.\d+(?:\.\d+)?)"',  # package = "1.2.3"
            r'(\w+)\s*=\s*\{\s*version\s*=\s*"(\d+\.\d+(?:\.\d+)?)"',  # package = { version = "1.2.3" }
        ],
        "go": [
            r'go\s+(\d+\.\d+)',  # go 1.21
            r'(\S+)\s+v(\d+\.\d+(?:\.\d+)?)',  # module v1.2.3
        ],
    }

    def __init__(self, db: AsyncSession):
        self.db = db

    def _parse_version(self, version_str: str) -> tuple[int, int, int]:
        """Parse version string to tuple for comparison."""
        parts = version_str.split(".")
        try:
            major = int(parts[0]) if len(parts) > 0 else 0
            minor = int(parts[1]) if len(parts) > 1 else 0
            patch = int(parts[2]) if len(parts) > 2 else 0
            return (major, minor, patch)
        except (ValueError, IndexError):
            return (0, 0, 0)

    def _compare_versions(self, current: str, latest: str) -> TechnologyStatus:
        """Compare version strings and return status."""
        if not current or not latest:
            return TechnologyStatus.UNKNOWN

        curr_parts = self._parse_version(current)
        latest_parts = self._parse_version(latest)

        major_diff = latest_parts[0] - curr_parts[0]
        minor_diff = latest_parts[1] - curr_parts[1]

        if major_diff == 0 and minor_diff <= 2:
            return TechnologyStatus.CURRENT
        elif major_diff == 0 or (major_diff == 1 and curr_parts[0] > 0):
            return TechnologyStatus.RECENT
        else:
            return TechnologyStatus.OUTDATED

    def _is_deprecated(self, tech_name: str, version: str) -> bool:
        """Check if a specific version is deprecated."""
        tech_info = TECHNOLOGY_VERSIONS.get(tech_name.lower())
        if not tech_info:
            return False

        deprecated_list = tech_info.get("deprecated", [])
        version_prefix = version.split(".")[0]  # Get major version

        return version_prefix in deprecated_list or version in deprecated_list

    def _extract_versions_from_content(
        self,
        content: str,
        file_type: str,
    ) -> list[tuple[str, str]]:
        """Extract technology versions from file content."""
        versions = []
        patterns = self.VERSION_PATTERNS.get(file_type, [])

        for pattern in patterns:
            matches = re.findall(pattern, content, re.MULTILINE)
            versions.extend(matches)

        return versions

    def _normalize_tech_name(self, name: str) -> str:
        """Normalize technology name for lookup."""
        # Remove common prefixes/suffixes
        name = name.lower()
        name = re.sub(r'^@\w+/', '', name)  # Remove npm scope
        name = re.sub(r'-js$', '', name)  # Remove -js suffix
        name = re.sub(r'\.js$', '', name)  # Remove .js suffix

        # Common aliases
        aliases = {
            "nextjs": "next",
            "react-dom": "react",
            "vue-router": "vue",
            "@angular/core": "angular",
            "@nestjs/core": "nestjs",
            "spring-boot-starter": "spring-boot",
            "pg": "postgresql",
            "psycopg2": "postgresql",
            "asyncpg": "postgresql",
            "pymongo": "mongodb",
            "redis-py": "redis",
        }

        return aliases.get(name, name)

    async def analyze_commit_technologies(
        self,
        commit: Commit,
    ) -> list[TechnologyVersion]:
        """Analyze a commit for technology versions."""
        technologies = []

        # Check file types in commit
        file_types = commit.file_types or []

        for file_path in file_types:
            file_name = file_path.split("/")[-1]

            if file_name in self.DEPENDENCY_FILES:
                # We found a dependency file - note it
                # In a real implementation, we'd fetch the file content
                # For now, we mark that this type of project exists
                file_type = self.DEPENDENCY_FILES[file_name]

                # Extract info from commit message if present
                message = commit.message or ""

                # Look for version mentions in commit message
                version_mentions = re.findall(
                    r'(\w+)[\s:@]v?(\d+\.\d+(?:\.\d+)?)',
                    message,
                    re.IGNORECASE,
                )

                for name, version in version_mentions:
                    norm_name = self._normalize_tech_name(name)
                    tech_info = TECHNOLOGY_VERSIONS.get(norm_name)

                    if tech_info:
                        status = (
                            TechnologyStatus.DEPRECATED
                            if self._is_deprecated(norm_name, version)
                            else self._compare_versions(version, tech_info["latest"])
                        )

                        technologies.append(TechnologyVersion(
                            name=norm_name,
                            version=version,
                            category=TechnologyCategory(tech_info["category"]),
                            status=status,
                            latest_version=tech_info["latest"],
                            detected_from=file_name,
                            first_seen=commit.committed_at,
                            last_seen=commit.committed_at,
                            usage_count=1,
                        ))

        return technologies

    async def get_developer_technology_profile(
        self,
        developer_id: str,
        days: int = 365,
    ) -> TechnologyProfile:
        """Build technology profile for a developer."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # Get commits with file changes
        stmt = (
            select(Commit)
            .where(
                Commit.developer_id == developer_id,
                Commit.committed_at >= cutoff,
            )
            .order_by(Commit.committed_at.desc())
        )
        result = await self.db.execute(stmt)
        commits = result.scalars().all()

        # Aggregate technology detections
        tech_map: dict[str, TechnologyVersion] = {}

        for commit in commits:
            technologies = await self.analyze_commit_technologies(commit)

            for tech in technologies:
                key = f"{tech.name}:{tech.version}"

                if key in tech_map:
                    existing = tech_map[key]
                    existing.usage_count += 1
                    if tech.last_seen and (
                        not existing.last_seen or tech.last_seen > existing.last_seen
                    ):
                        existing.last_seen = tech.last_seen
                else:
                    tech_map[key] = tech

        # Count by status
        technologies = list(tech_map.values())
        current_count = sum(
            1 for t in technologies if t.status == TechnologyStatus.CURRENT
        )
        outdated_count = sum(
            1 for t in technologies if t.status == TechnologyStatus.OUTDATED
        )
        deprecated_count = sum(
            1 for t in technologies if t.status == TechnologyStatus.DEPRECATED
        )

        # Calculate adoption score
        total = len(technologies)
        if total > 0:
            adoption_score = (current_count + 0.5 * sum(
                1 for t in technologies if t.status == TechnologyStatus.RECENT
            )) / total
        else:
            adoption_score = 0.5  # Neutral score when no data

        # Generate upgrade suggestions
        upgrade_suggestions = []
        for tech in technologies:
            if tech.status in [TechnologyStatus.OUTDATED, TechnologyStatus.DEPRECATED]:
                upgrade_suggestions.append({
                    "technology": tech.name,
                    "current_version": tech.version,
                    "suggested_version": tech.latest_version,
                    "priority": "high" if tech.status == TechnologyStatus.DEPRECATED else "medium",
                    "reason": (
                        "End of life - security updates no longer provided"
                        if tech.status == TechnologyStatus.DEPRECATED
                        else "Multiple major versions behind latest"
                    ),
                })

        return TechnologyProfile(
            developer_id=developer_id,
            technologies=sorted(technologies, key=lambda t: t.name),
            current_count=current_count,
            outdated_count=outdated_count,
            deprecated_count=deprecated_count,
            adoption_score=round(adoption_score, 2),
            upgrade_suggestions=upgrade_suggestions[:10],  # Top 10 suggestions
        )

    async def update_developer_technology_profile(
        self,
        developer_id: str,
        days: int = 365,
    ) -> TechnologyProfile:
        """Update and store technology profile for a developer."""
        profile = await self.get_developer_technology_profile(developer_id, days)

        # Store in developer model
        stmt = select(Developer).where(Developer.id == developer_id)
        result = await self.db.execute(stmt)
        developer = result.scalar_one_or_none()

        if developer:
            fingerprint = developer.skill_fingerprint or {}
            fingerprint["technology_profile"] = profile.to_dict()
            developer.skill_fingerprint = fingerprint

        return profile


async def get_team_technology_overview(
    db: AsyncSession,
    developer_ids: list[str],
    days: int = 180,
) -> dict[str, Any]:
    """Get technology overview for a team."""
    tracker = TechnologyTracker(db)

    # Aggregate all technologies
    all_techs: dict[str, dict] = {}
    profiles = []

    for dev_id in developer_ids:
        profile = await tracker.get_developer_technology_profile(dev_id, days)
        profiles.append(profile)

        for tech in profile.technologies:
            key = tech.name
            if key not in all_techs:
                all_techs[key] = {
                    "name": tech.name,
                    "category": tech.category.value,
                    "versions_in_use": {},
                    "developer_count": 0,
                    "latest_version": tech.latest_version,
                }

            version_key = tech.version or "unknown"
            if version_key not in all_techs[key]["versions_in_use"]:
                all_techs[key]["versions_in_use"][version_key] = {
                    "count": 0,
                    "status": tech.status.value,
                }
            all_techs[key]["versions_in_use"][version_key]["count"] += 1
            all_techs[key]["developer_count"] += 1

    # Calculate team health
    total_current = sum(p.current_count for p in profiles)
    total_outdated = sum(p.outdated_count for p in profiles)
    total_deprecated = sum(p.deprecated_count for p in profiles)
    total = total_current + total_outdated + total_deprecated

    team_health = (total_current / total * 100) if total > 0 else 50

    # Find critical upgrades needed
    critical_upgrades = []
    for tech_name, tech_data in all_techs.items():
        for version, version_data in tech_data["versions_in_use"].items():
            if version_data["status"] == "deprecated":
                critical_upgrades.append({
                    "technology": tech_name,
                    "deprecated_version": version,
                    "developers_affected": version_data["count"],
                    "latest_version": tech_data["latest_version"],
                })

    return {
        "total_developers": len(developer_ids),
        "technologies_tracked": len(all_techs),
        "team_health_score": round(team_health, 2),
        "status_distribution": {
            "current": total_current,
            "outdated": total_outdated,
            "deprecated": total_deprecated,
        },
        "technologies": list(all_techs.values()),
        "critical_upgrades": sorted(
            critical_upgrades,
            key=lambda x: x["developers_affected"],
            reverse=True,
        )[:5],
    }
