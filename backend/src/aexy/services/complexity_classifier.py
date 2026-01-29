"""Project Complexity Classification Service.

Analyzes pull requests for:
- File distribution (single file vs cross-cutting)
- Architectural changes detection
- Infrastructure vs application changes
- Services/systems touched
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


class ComplexityLevel(Enum):
    """PR complexity classification levels."""
    TRIVIAL = "trivial"  # Single file, minor change
    SIMPLE = "simple"  # Few files, single component
    MODERATE = "moderate"  # Multiple files, may span components
    COMPLEX = "complex"  # Many files, cross-cutting
    CRITICAL = "critical"  # Architectural, infrastructure changes


class ChangeCategory(Enum):
    """Categories of changes in a PR."""
    FEATURE = "feature"
    BUGFIX = "bugfix"
    REFACTOR = "refactor"
    DOCUMENTATION = "documentation"
    INFRASTRUCTURE = "infrastructure"
    CONFIGURATION = "configuration"
    DEPENDENCY = "dependency"
    TEST = "test"
    SECURITY = "security"
    PERFORMANCE = "performance"


@dataclass
class FileChangeInfo:
    """Information about file changes."""
    path: str
    additions: int = 0
    deletions: int = 0
    component: str = ""
    layer: str = ""  # e.g., "api", "service", "model", "ui"
    is_test: bool = False
    is_config: bool = False
    is_infra: bool = False
    is_migration: bool = False


@dataclass
class ComplexityAnalysis:
    """Full complexity analysis for a PR."""
    pr_id: str
    complexity_level: ComplexityLevel
    complexity_score: float  # 0-100

    # File analysis
    total_files: int = 0
    files_by_layer: dict = field(default_factory=dict)
    files_by_component: dict = field(default_factory=dict)

    # Change characteristics
    categories: list[ChangeCategory] = field(default_factory=list)
    is_cross_cutting: bool = False
    touches_infrastructure: bool = False
    touches_architecture: bool = False
    touches_security: bool = False
    has_migration: bool = False

    # Impact assessment
    components_affected: list[str] = field(default_factory=list)
    layers_affected: list[str] = field(default_factory=list)
    estimated_review_effort: str = "low"  # low/medium/high/very_high
    risk_indicators: list[str] = field(default_factory=list)

    # Metrics
    total_additions: int = 0
    total_deletions: int = 0
    test_coverage_change: float = 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "pr_id": self.pr_id,
            "complexity_level": self.complexity_level.value,
            "complexity_score": self.complexity_score,
            "total_files": self.total_files,
            "files_by_layer": self.files_by_layer,
            "files_by_component": self.files_by_component,
            "categories": [c.value for c in self.categories],
            "is_cross_cutting": self.is_cross_cutting,
            "touches_infrastructure": self.touches_infrastructure,
            "touches_architecture": self.touches_architecture,
            "touches_security": self.touches_security,
            "has_migration": self.has_migration,
            "components_affected": self.components_affected,
            "layers_affected": self.layers_affected,
            "estimated_review_effort": self.estimated_review_effort,
            "risk_indicators": self.risk_indicators,
            "total_additions": self.total_additions,
            "total_deletions": self.total_deletions,
            "test_coverage_change": self.test_coverage_change,
        }


@dataclass
class DeveloperComplexityProfile:
    """Aggregated complexity profile for a developer."""
    developer_id: str
    total_prs_analyzed: int = 0

    # Distribution of PR complexities
    complexity_distribution: dict = field(default_factory=dict)

    # Specializations
    primary_categories: list[str] = field(default_factory=list)
    common_components: list[str] = field(default_factory=list)
    common_layers: list[str] = field(default_factory=list)

    # Metrics
    avg_files_per_pr: float = 0.0
    avg_complexity_score: float = 0.0
    cross_cutting_ratio: float = 0.0
    infrastructure_ratio: float = 0.0

    # Risk handling
    handles_critical_changes: bool = False
    avg_review_effort: str = "low"

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "developer_id": self.developer_id,
            "total_prs_analyzed": self.total_prs_analyzed,
            "complexity_distribution": self.complexity_distribution,
            "primary_categories": self.primary_categories,
            "common_components": self.common_components,
            "common_layers": self.common_layers,
            "avg_files_per_pr": self.avg_files_per_pr,
            "avg_complexity_score": self.avg_complexity_score,
            "cross_cutting_ratio": self.cross_cutting_ratio,
            "infrastructure_ratio": self.infrastructure_ratio,
            "handles_critical_changes": self.handles_critical_changes,
            "avg_review_effort": self.avg_review_effort,
        }


class ComplexityClassifier:
    """Classifies PR complexity based on changes."""

    # File patterns for layer detection
    LAYER_PATTERNS = {
        "api": [r"/api/", r"/routes/", r"/endpoints/", r"/controllers/"],
        "service": [r"/services/", r"/business/", r"/logic/", r"/handlers/"],
        "model": [r"/models/", r"/entities/", r"/schemas/", r"/types/"],
        "repository": [r"/repositories/", r"/dao/", r"/data/"],
        "ui": [r"/components/", r"/pages/", r"/views/", r"/ui/", r"\.tsx$", r"\.jsx$"],
        "infrastructure": [r"/infrastructure/", r"/infra/", r"docker", r"kubernetes", r"terraform"],
        "config": [r"/config/", r"\.env", r"\.yaml$", r"\.yml$", r"\.toml$", r"\.json$"],
        "test": [r"/tests?/", r"_test\.", r"\.test\.", r"\.spec\."],
    }

    # Component extraction patterns
    COMPONENT_PATTERNS = [
        r"src/([^/]+)/",
        r"packages/([^/]+)/",
        r"apps/([^/]+)/",
        r"modules/([^/]+)/",
        r"services/([^/]+)/",
        r"lib/([^/]+)/",
    ]

    # Infrastructure file patterns
    INFRA_PATTERNS = [
        r"Dockerfile",
        r"docker-compose",
        r"\.tf$",
        r"kubernetes/",
        r"k8s/",
        r"\.github/",
        r"Makefile",
        r"Jenkinsfile",
        r"\.gitlab-ci",
        r"azure-pipelines",
    ]

    # Security-sensitive patterns
    SECURITY_PATTERNS = [
        r"/auth",
        r"/security",
        r"password",
        r"token",
        r"secret",
        r"credential",
        r"encrypt",
        r"decrypt",
        r"\.pem$",
        r"\.key$",
    ]

    # Migration patterns
    MIGRATION_PATTERNS = [
        r"/migrations?/",
        r"migrate",
        r"alembic",
        r"flyway",
        r"liquibase",
        r"\.sql$",
    ]

    def __init__(self, db: AsyncSession):
        self.db = db

    def _detect_layer(self, file_path: str) -> str:
        """Detect which architectural layer a file belongs to."""
        file_lower = file_path.lower()

        for layer, patterns in self.LAYER_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, file_lower):
                    return layer

        return "other"

    def _extract_component(self, file_path: str) -> str:
        """Extract component name from file path."""
        for pattern in self.COMPONENT_PATTERNS:
            match = re.search(pattern, file_path)
            if match:
                return match.group(1)

        # Fallback: use top-level directory
        parts = file_path.split("/")
        if len(parts) > 1:
            return parts[0]

        return "root"

    def _is_infrastructure(self, file_path: str) -> bool:
        """Check if file is infrastructure-related."""
        file_lower = file_path.lower()
        return any(re.search(p, file_lower) for p in self.INFRA_PATTERNS)

    def _is_security_sensitive(self, file_path: str) -> bool:
        """Check if file is security-sensitive."""
        file_lower = file_path.lower()
        return any(re.search(p, file_lower) for p in self.SECURITY_PATTERNS)

    def _is_migration(self, file_path: str) -> bool:
        """Check if file is a database migration."""
        file_lower = file_path.lower()
        return any(re.search(p, file_lower) for p in self.MIGRATION_PATTERNS)

    def _is_test_file(self, file_path: str) -> bool:
        """Check if file is a test file."""
        file_lower = file_path.lower()
        test_patterns = self.LAYER_PATTERNS.get("test", [])
        return any(re.search(p, file_lower) for p in test_patterns)

    def _is_config_file(self, file_path: str) -> bool:
        """Check if file is a configuration file."""
        file_lower = file_path.lower()
        config_patterns = self.LAYER_PATTERNS.get("config", [])
        return any(re.search(p, file_lower) for p in config_patterns)

    def _analyze_file(self, file_path: str, additions: int = 0, deletions: int = 0) -> FileChangeInfo:
        """Analyze a single file change."""
        return FileChangeInfo(
            path=file_path,
            additions=additions,
            deletions=deletions,
            component=self._extract_component(file_path),
            layer=self._detect_layer(file_path),
            is_test=self._is_test_file(file_path),
            is_config=self._is_config_file(file_path),
            is_infra=self._is_infrastructure(file_path),
            is_migration=self._is_migration(file_path),
        )

    def _detect_categories(self, pr: PullRequest, file_changes: list[FileChangeInfo]) -> list[ChangeCategory]:
        """Detect change categories from PR and files."""
        categories = set()

        # From PR title/body
        title = (pr.title or "").lower()
        body = (pr.body or "").lower()
        combined = f"{title} {body}"

        if any(kw in combined for kw in ["feat", "feature", "add", "new"]):
            categories.add(ChangeCategory.FEATURE)
        if any(kw in combined for kw in ["fix", "bug", "issue", "resolve"]):
            categories.add(ChangeCategory.BUGFIX)
        if any(kw in combined for kw in ["refactor", "cleanup", "reorganize"]):
            categories.add(ChangeCategory.REFACTOR)
        if any(kw in combined for kw in ["doc", "readme", "documentation"]):
            categories.add(ChangeCategory.DOCUMENTATION)
        if any(kw in combined for kw in ["infra", "deploy", "ci", "cd", "pipeline"]):
            categories.add(ChangeCategory.INFRASTRUCTURE)
        if any(kw in combined for kw in ["config", "setting", "environment"]):
            categories.add(ChangeCategory.CONFIGURATION)
        if any(kw in combined for kw in ["depend", "upgrade", "bump", "update"]):
            categories.add(ChangeCategory.DEPENDENCY)
        if any(kw in combined for kw in ["test", "spec", "coverage"]):
            categories.add(ChangeCategory.TEST)
        if any(kw in combined for kw in ["security", "auth", "permission", "vuln"]):
            categories.add(ChangeCategory.SECURITY)
        if any(kw in combined for kw in ["perf", "optim", "speed", "fast"]):
            categories.add(ChangeCategory.PERFORMANCE)

        # From file changes
        for fc in file_changes:
            if fc.is_test:
                categories.add(ChangeCategory.TEST)
            if fc.is_infra:
                categories.add(ChangeCategory.INFRASTRUCTURE)
            if fc.is_config:
                categories.add(ChangeCategory.CONFIGURATION)
            if fc.is_migration:
                categories.add(ChangeCategory.INFRASTRUCTURE)

        return list(categories) if categories else [ChangeCategory.FEATURE]

    def _calculate_complexity_score(
        self,
        file_changes: list[FileChangeInfo],
        categories: list[ChangeCategory],
    ) -> tuple[float, ComplexityLevel]:
        """Calculate complexity score (0-100) and level."""
        score = 0.0

        # File count factor (0-30 points)
        file_count = len(file_changes)
        if file_count <= 1:
            score += 0
        elif file_count <= 3:
            score += 10
        elif file_count <= 7:
            score += 20
        elif file_count <= 15:
            score += 25
        else:
            score += 30

        # Unique components factor (0-20 points)
        components = set(fc.component for fc in file_changes)
        if len(components) <= 1:
            score += 0
        elif len(components) <= 2:
            score += 10
        elif len(components) <= 4:
            score += 15
        else:
            score += 20

        # Unique layers factor (0-20 points)
        layers = set(fc.layer for fc in file_changes if fc.layer != "other")
        if len(layers) <= 1:
            score += 0
        elif len(layers) <= 2:
            score += 10
        elif len(layers) <= 3:
            score += 15
        else:
            score += 20

        # Category complexity factor (0-15 points)
        high_complexity_categories = {
            ChangeCategory.INFRASTRUCTURE,
            ChangeCategory.SECURITY,
            ChangeCategory.PERFORMANCE,
        }
        if any(c in high_complexity_categories for c in categories):
            score += 15
        elif len(categories) > 2:
            score += 10
        elif len(categories) > 1:
            score += 5

        # Infrastructure/migration factor (0-15 points)
        infra_files = sum(1 for fc in file_changes if fc.is_infra)
        migration_files = sum(1 for fc in file_changes if fc.is_migration)

        if migration_files > 0:
            score += 10
        if infra_files > 0:
            score += min(infra_files * 2, 10)

        # Determine level from score
        if score < 15:
            level = ComplexityLevel.TRIVIAL
        elif score < 30:
            level = ComplexityLevel.SIMPLE
        elif score < 50:
            level = ComplexityLevel.MODERATE
        elif score < 70:
            level = ComplexityLevel.COMPLEX
        else:
            level = ComplexityLevel.CRITICAL

        return min(score, 100), level

    def _estimate_review_effort(self, complexity_level: ComplexityLevel, total_changes: int) -> str:
        """Estimate review effort based on complexity and change size."""
        if complexity_level in [ComplexityLevel.TRIVIAL, ComplexityLevel.SIMPLE]:
            if total_changes < 100:
                return "low"
            elif total_changes < 300:
                return "medium"
            else:
                return "high"
        elif complexity_level == ComplexityLevel.MODERATE:
            if total_changes < 200:
                return "medium"
            else:
                return "high"
        elif complexity_level == ComplexityLevel.COMPLEX:
            if total_changes < 300:
                return "high"
            else:
                return "very_high"
        else:  # CRITICAL
            return "very_high"

    def _identify_risk_indicators(
        self,
        file_changes: list[FileChangeInfo],
        categories: list[ChangeCategory],
    ) -> list[str]:
        """Identify risk indicators for the PR."""
        risks = []

        # Security risks
        security_files = [fc for fc in file_changes if self._is_security_sensitive(fc.path)]
        if security_files:
            risks.append(f"Security-sensitive files modified ({len(security_files)})")

        if ChangeCategory.SECURITY in categories:
            risks.append("Security-related changes")

        # Infrastructure risks
        infra_count = sum(1 for fc in file_changes if fc.is_infra)
        if infra_count > 0:
            risks.append(f"Infrastructure changes ({infra_count} files)")

        # Migration risks
        migration_count = sum(1 for fc in file_changes if fc.is_migration)
        if migration_count > 0:
            risks.append(f"Database migrations ({migration_count})")

        # Cross-cutting risks
        components = set(fc.component for fc in file_changes)
        if len(components) > 3:
            risks.append(f"Cross-cutting changes ({len(components)} components)")

        # Large change risks
        total_changes = sum(fc.additions + fc.deletions for fc in file_changes)
        if total_changes > 500:
            risks.append(f"Large change volume ({total_changes} lines)")

        # Low test coverage risk
        test_files = sum(1 for fc in file_changes if fc.is_test)
        non_test_files = len(file_changes) - test_files
        if non_test_files > 3 and test_files == 0:
            risks.append("No test file changes detected")

        return risks

    async def analyze_pr(self, pr: PullRequest) -> ComplexityAnalysis:
        """Analyze a single PR for complexity."""
        # Parse file changes from PR data
        file_changes: list[FileChangeInfo] = []

        # Get files from commits if available
        changed_files = pr.changed_files or []
        additions = pr.additions or 0
        deletions = pr.deletions or 0

        # If we have detailed file info
        if changed_files:
            for file_path in changed_files:
                fc = self._analyze_file(file_path)
                file_changes.append(fc)
        else:
            # Create synthetic entry based on PR metadata
            file_changes = [FileChangeInfo(
                path="unknown",
                additions=additions,
                deletions=deletions,
            )]

        # Detect categories
        categories = self._detect_categories(pr, file_changes)

        # Calculate complexity
        complexity_score, complexity_level = self._calculate_complexity_score(
            file_changes, categories
        )

        # Aggregate metrics
        files_by_layer: dict[str, int] = {}
        files_by_component: dict[str, int] = {}

        for fc in file_changes:
            files_by_layer[fc.layer] = files_by_layer.get(fc.layer, 0) + 1
            files_by_component[fc.component] = files_by_component.get(fc.component, 0) + 1

        # Build analysis
        total_additions = sum(fc.additions for fc in file_changes) or additions
        total_deletions = sum(fc.deletions for fc in file_changes) or deletions

        analysis = ComplexityAnalysis(
            pr_id=pr.id,
            complexity_level=complexity_level,
            complexity_score=complexity_score,
            total_files=len(file_changes),
            files_by_layer=files_by_layer,
            files_by_component=files_by_component,
            categories=categories,
            is_cross_cutting=len(files_by_component) > 2,
            touches_infrastructure=any(fc.is_infra for fc in file_changes),
            touches_architecture=len(files_by_layer) > 2,
            touches_security=any(self._is_security_sensitive(fc.path) for fc in file_changes),
            has_migration=any(fc.is_migration for fc in file_changes),
            components_affected=list(files_by_component.keys()),
            layers_affected=list(files_by_layer.keys()),
            estimated_review_effort=self._estimate_review_effort(
                complexity_level, total_additions + total_deletions
            ),
            risk_indicators=self._identify_risk_indicators(file_changes, categories),
            total_additions=total_additions,
            total_deletions=total_deletions,
        )

        return analysis

    async def analyze_prs_batch(
        self,
        developer_id: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Analyze a batch of PRs for a developer."""
        # Get developer's PRs
        stmt = (
            select(PullRequest)
            .where(PullRequest.developer_id == developer_id)
            .order_by(PullRequest.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        prs = result.scalars().all()

        if not prs:
            return {
                "prs_analyzed": 0,
                "complexity_distribution": {},
                "avg_complexity_score": 0,
            }

        # Analyze each PR
        analyses: list[ComplexityAnalysis] = []
        complexity_counts: dict[str, int] = {}

        for pr in prs:
            analysis = await self.analyze_pr(pr)
            analyses.append(analysis)

            level = analysis.complexity_level.value
            complexity_counts[level] = complexity_counts.get(level, 0) + 1

            # Store analysis in PR
            if hasattr(pr, "complexity_analysis"):
                pr.complexity_analysis = analysis.to_dict()

        # Calculate averages
        avg_score = sum(a.complexity_score for a in analyses) / len(analyses)
        avg_files = sum(a.total_files for a in analyses) / len(analyses)

        # Category distribution
        category_counts: dict[str, int] = {}
        for analysis in analyses:
            for cat in analysis.categories:
                category_counts[cat.value] = category_counts.get(cat.value, 0) + 1

        return {
            "prs_analyzed": len(analyses),
            "complexity_distribution": complexity_counts,
            "avg_complexity_score": round(avg_score, 2),
            "avg_files_per_pr": round(avg_files, 2),
            "category_distribution": category_counts,
            "cross_cutting_count": sum(1 for a in analyses if a.is_cross_cutting),
            "infrastructure_count": sum(1 for a in analyses if a.touches_infrastructure),
            "security_count": sum(1 for a in analyses if a.touches_security),
            "migration_count": sum(1 for a in analyses if a.has_migration),
        }

    async def get_developer_complexity_profile(
        self,
        developer_id: str,
        days: int = 180,
    ) -> DeveloperComplexityProfile:
        """Build complexity profile for a developer."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # Get PRs in timeframe
        stmt = (
            select(PullRequest)
            .where(
                PullRequest.developer_id == developer_id,
                PullRequest.created_at >= cutoff,
            )
            .order_by(PullRequest.created_at.desc())
        )
        result = await self.db.execute(stmt)
        prs = result.scalars().all()

        if not prs:
            return DeveloperComplexityProfile(developer_id=developer_id)

        # Analyze all PRs
        analyses: list[ComplexityAnalysis] = []
        complexity_counts: dict[str, int] = {}
        category_counts: dict[str, int] = {}
        component_counts: dict[str, int] = {}
        layer_counts: dict[str, int] = {}

        for pr in prs:
            analysis = await self.analyze_pr(pr)
            analyses.append(analysis)

            # Aggregate complexity
            level = analysis.complexity_level.value
            complexity_counts[level] = complexity_counts.get(level, 0) + 1

            # Aggregate categories
            for cat in analysis.categories:
                category_counts[cat.value] = category_counts.get(cat.value, 0) + 1

            # Aggregate components
            for comp in analysis.components_affected:
                component_counts[comp] = component_counts.get(comp, 0) + 1

            # Aggregate layers
            for layer in analysis.layers_affected:
                layer_counts[layer] = layer_counts.get(layer, 0) + 1

        # Build profile
        avg_score = sum(a.complexity_score for a in analyses) / len(analyses)
        avg_files = sum(a.total_files for a in analyses) / len(analyses)
        cross_cutting = sum(1 for a in analyses if a.is_cross_cutting)
        infra_count = sum(1 for a in analyses if a.touches_infrastructure)

        # Determine average review effort
        effort_map = {"low": 1, "medium": 2, "high": 3, "very_high": 4}
        effort_reverse = {1: "low", 2: "medium", 3: "high", 4: "very_high"}
        avg_effort_score = sum(
            effort_map.get(a.estimated_review_effort, 1) for a in analyses
        ) / len(analyses)
        avg_effort = effort_reverse.get(round(avg_effort_score), "medium")

        # Sort by frequency for top items
        sorted_categories = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)
        sorted_components = sorted(component_counts.items(), key=lambda x: x[1], reverse=True)
        sorted_layers = sorted(layer_counts.items(), key=lambda x: x[1], reverse=True)

        return DeveloperComplexityProfile(
            developer_id=developer_id,
            total_prs_analyzed=len(analyses),
            complexity_distribution=complexity_counts,
            primary_categories=[c[0] for c in sorted_categories[:3]],
            common_components=[c[0] for c in sorted_components[:5]],
            common_layers=[l[0] for l in sorted_layers[:3]],
            avg_files_per_pr=round(avg_files, 2),
            avg_complexity_score=round(avg_score, 2),
            cross_cutting_ratio=round(cross_cutting / len(analyses), 2),
            infrastructure_ratio=round(infra_count / len(analyses), 2),
            handles_critical_changes=complexity_counts.get("critical", 0) > 0,
            avg_review_effort=avg_effort,
        )

    async def update_developer_complexity_profile(
        self,
        developer_id: str,
        days: int = 180,
    ) -> DeveloperComplexityProfile:
        """Update and store complexity profile for a developer."""
        profile = await self.get_developer_complexity_profile(developer_id, days)

        # Store in developer model
        stmt = select(Developer).where(Developer.id == developer_id)
        result = await self.db.execute(stmt)
        developer = result.scalar_one_or_none()

        if developer:
            # Store in skill_fingerprint or a dedicated field
            fingerprint = developer.skill_fingerprint or {}
            fingerprint["complexity_profile"] = profile.to_dict()
            developer.skill_fingerprint = fingerprint

        return profile


async def get_complexity_summary(
    db: AsyncSession,
    developer_ids: list[str],
    days: int = 90,
) -> dict[str, Any]:
    """Get complexity summary for multiple developers (team view)."""
    classifier = ComplexityClassifier(db)

    profiles = []
    for dev_id in developer_ids:
        profile = await classifier.get_developer_complexity_profile(dev_id, days)
        if profile.total_prs_analyzed > 0:
            profiles.append(profile)

    if not profiles:
        return {
            "total_developers": len(developer_ids),
            "analyzed_developers": 0,
            "avg_complexity_score": 0,
        }

    # Aggregate team metrics
    avg_score = sum(p.avg_complexity_score for p in profiles) / len(profiles)
    avg_cross_cutting = sum(p.cross_cutting_ratio for p in profiles) / len(profiles)
    avg_infra = sum(p.infrastructure_ratio for p in profiles) / len(profiles)

    # Count developers handling critical changes
    critical_handlers = sum(1 for p in profiles if p.handles_critical_changes)

    # Aggregate complexity distribution
    team_distribution: dict[str, int] = {}
    for profile in profiles:
        for level, count in profile.complexity_distribution.items():
            team_distribution[level] = team_distribution.get(level, 0) + count

    return {
        "total_developers": len(developer_ids),
        "analyzed_developers": len(profiles),
        "avg_complexity_score": round(avg_score, 2),
        "avg_cross_cutting_ratio": round(avg_cross_cutting, 2),
        "avg_infrastructure_ratio": round(avg_infra, 2),
        "critical_change_handlers": critical_handlers,
        "team_complexity_distribution": team_distribution,
    }
