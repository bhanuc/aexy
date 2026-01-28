"""Expertise confidence scoring service.

Enhances skill scores with:
- Confidence intervals (0-1)
- Recency factor (decay over time)
- Depth levels (novice/intermediate/advanced/expert)
- Context classification (production/personal/learning)
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.activity import Commit, PullRequest
from aexy.models.developer import Developer

logger = logging.getLogger(__name__)


# Depth level thresholds based on proficiency score
DEPTH_THRESHOLDS = {
    "expert": 80,
    "advanced": 60,
    "intermediate": 40,
    "novice": 0,
}

# Recency decay parameters
RECENCY_HALF_LIFE_DAYS = 180  # Skills decay by half confidence every 6 months


@dataclass
class SkillWithConfidence:
    """Enhanced skill with confidence metrics."""
    name: str
    proficiency: float  # 0-100
    confidence: float  # 0-1, how sure we are about the proficiency
    recency_factor: float  # 0-1, based on last activity
    depth: Literal["novice", "intermediate", "advanced", "expert"]
    context: Literal["production", "personal", "learning", "unknown"]
    commit_count: int
    lines_of_code: int
    last_activity_at: datetime | None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSONB storage."""
        return {
            "name": self.name,
            "proficiency": round(self.proficiency, 1),
            "confidence": round(self.confidence, 2),
            "recency_factor": round(self.recency_factor, 2),
            "depth": self.depth,
            "context": self.context,
            "commit_count": self.commit_count,
            "lines_of_code": self.lines_of_code,
            "last_activity_at": self.last_activity_at.isoformat() if self.last_activity_at else None,
        }


@dataclass
class ExpertiseProfile:
    """Complete expertise profile with confidence."""
    skills: list[SkillWithConfidence]
    overall_confidence: float
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """Convert to dictionary for JSONB storage."""
        return {
            "skills": [s.to_dict() for s in self.skills],
            "overall_confidence": round(self.overall_confidence, 2),
            "updated_at": self.updated_at.isoformat(),
        }


class ExpertiseConfidenceAnalyzer:
    """Analyzes skills with confidence scoring."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def analyze_developer(
        self,
        developer_id: str,
        days: int = 365,
    ) -> ExpertiseProfile:
        """Analyze expertise with confidence for a developer.

        Args:
            developer_id: Developer UUID.
            days: Days of history to consider.

        Returns:
            ExpertiseProfile with confidence-enhanced skills.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # Get commit statistics by language
        language_stats = await self._get_language_stats(developer_id, cutoff)

        # Get the developer's current skill fingerprint for context
        dev_stmt = select(Developer).where(Developer.id == developer_id)
        result = await self.db.execute(dev_stmt)
        developer = result.scalar_one_or_none()

        existing_fingerprint = developer.skill_fingerprint if developer else {}

        # Build enhanced skills
        skills = []
        for lang, stats in language_stats.items():
            skill = self._build_skill_with_confidence(
                language=lang,
                stats=stats,
                existing_fingerprint=existing_fingerprint,
            )
            skills.append(skill)

        # Sort by proficiency * confidence (effective skill level)
        skills.sort(key=lambda s: s.proficiency * s.confidence, reverse=True)

        # Calculate overall confidence
        if skills:
            overall_confidence = sum(s.confidence for s in skills) / len(skills)
        else:
            overall_confidence = 0.0

        return ExpertiseProfile(
            skills=skills,
            overall_confidence=overall_confidence,
        )

    async def _get_language_stats(
        self,
        developer_id: str,
        cutoff: datetime,
    ) -> dict:
        """Get language statistics from commits.

        Returns dict mapping language -> {
            commit_count, total_additions, last_commit_at, repos
        }
        """
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

        stats: dict[str, dict] = {}

        for commit in commits:
            languages = commit.languages or []
            additions = commit.additions or 0
            committed_at = commit.committed_at
            repo = commit.repository

            # Distribute additions across languages (simplified)
            per_lang = additions // max(len(languages), 1)

            for lang in languages:
                if lang not in stats:
                    stats[lang] = {
                        "commit_count": 0,
                        "total_additions": 0,
                        "last_commit_at": None,
                        "repos": set(),
                    }

                stats[lang]["commit_count"] += 1
                stats[lang]["total_additions"] += per_lang

                if stats[lang]["last_commit_at"] is None:
                    stats[lang]["last_commit_at"] = committed_at
                else:
                    stats[lang]["last_commit_at"] = max(
                        stats[lang]["last_commit_at"], committed_at
                    )

                if repo:
                    stats[lang]["repos"].add(repo)

        return stats

    def _build_skill_with_confidence(
        self,
        language: str,
        stats: dict,
        existing_fingerprint: dict,
    ) -> SkillWithConfidence:
        """Build a skill with confidence metrics."""
        commit_count = stats["commit_count"]
        total_lines = stats["total_additions"]
        last_activity = stats["last_commit_at"]
        repos = stats["repos"] if isinstance(stats["repos"], set) else set()

        # Calculate base proficiency (0-100)
        proficiency = self._calculate_proficiency(commit_count, total_lines)

        # Calculate confidence (0-1)
        confidence = self._calculate_confidence(commit_count, total_lines, len(repos))

        # Calculate recency factor (0-1)
        recency_factor = self._calculate_recency_factor(last_activity)

        # Determine depth level
        depth = self._determine_depth(proficiency)

        # Determine context
        context = self._determine_context(repos, existing_fingerprint, language)

        return SkillWithConfidence(
            name=language,
            proficiency=proficiency,
            confidence=confidence,
            recency_factor=recency_factor,
            depth=depth,
            context=context,
            commit_count=commit_count,
            lines_of_code=total_lines,
            last_activity_at=last_activity,
        )

    def _calculate_proficiency(self, commit_count: int, lines: int) -> float:
        """Calculate proficiency score (0-100).

        Uses logarithmic scaling to prevent runaway scores.
        """
        # Commit component (max ~50 points)
        commit_score = min(50, 10 * math.log10(commit_count + 1))

        # Lines component (max ~50 points)
        lines_score = min(50, 5 * math.log10(lines + 1))

        return min(100, commit_score + lines_score)

    def _calculate_confidence(
        self,
        commit_count: int,
        lines: int,
        repo_count: int,
    ) -> float:
        """Calculate confidence in the proficiency score (0-1).

        Confidence increases with more data points.
        """
        # More commits = higher confidence
        commit_confidence = min(1.0, commit_count / 100)

        # More lines = higher confidence
        lines_confidence = min(1.0, lines / 10000)

        # Multiple repos = higher confidence (not just one project)
        repo_confidence = min(1.0, repo_count / 5)

        # Weighted average
        confidence = (
            commit_confidence * 0.4 +
            lines_confidence * 0.3 +
            repo_confidence * 0.3
        )

        return confidence

    def _calculate_recency_factor(self, last_activity: datetime | None) -> float:
        """Calculate recency factor with exponential decay.

        Returns 1.0 for recent activity, approaching 0 for old activity.
        """
        if not last_activity:
            return 0.5  # Unknown, assume moderate

        now = datetime.now(timezone.utc)
        if last_activity.tzinfo is None:
            last_activity = last_activity.replace(tzinfo=timezone.utc)

        days_since = (now - last_activity).days

        # Exponential decay: recency = 2^(-days/half_life)
        recency = math.pow(2, -days_since / RECENCY_HALF_LIFE_DAYS)

        return max(0.1, recency)  # Minimum 0.1 to not completely forget

    def _determine_depth(
        self,
        proficiency: float,
    ) -> Literal["novice", "intermediate", "advanced", "expert"]:
        """Determine expertise depth level."""
        if proficiency >= DEPTH_THRESHOLDS["expert"]:
            return "expert"
        elif proficiency >= DEPTH_THRESHOLDS["advanced"]:
            return "advanced"
        elif proficiency >= DEPTH_THRESHOLDS["intermediate"]:
            return "intermediate"
        else:
            return "novice"

    def _determine_context(
        self,
        repos: set,
        existing_fingerprint: dict,
        language: str,
    ) -> Literal["production", "personal", "learning", "unknown"]:
        """Determine if skill is production, personal, or learning context.

        Uses heuristics based on repository patterns.
        """
        repo_names = [r.lower() for r in repos if r]

        # Production indicators
        production_patterns = [
            "api", "service", "backend", "frontend", "app",
            "platform", "core", "main", "prod", "enterprise",
        ]

        # Personal/learning indicators
        personal_patterns = [
            "personal", "demo", "example", "tutorial", "learn",
            "practice", "test", "experiment", "playground", "sandbox",
            "homework", "course", "exercise",
        ]

        production_count = sum(
            1 for repo in repo_names
            for pattern in production_patterns
            if pattern in repo
        )

        personal_count = sum(
            1 for repo in repo_names
            for pattern in personal_patterns
            if pattern in repo
        )

        if production_count > personal_count and production_count >= 2:
            return "production"
        elif personal_count > production_count:
            return "personal"
        elif len(repos) >= 3:
            return "production"  # Multiple repos suggests real work
        else:
            return "unknown"

    async def update_developer_expertise(
        self,
        developer_id: str,
        days: int = 365,
    ) -> ExpertiseProfile:
        """Update and store expertise profile for a developer.

        Args:
            developer_id: Developer UUID.
            days: Days of history to analyze.

        Returns:
            Updated expertise profile.
        """
        profile = await self.analyze_developer(developer_id, days)

        # Update developer record
        dev_stmt = select(Developer).where(Developer.id == developer_id)
        result = await self.db.execute(dev_stmt)
        developer = result.scalar_one_or_none()

        if developer:
            developer.expertise_confidence = profile.to_dict()
            developer.last_intelligence_analysis_at = datetime.now(timezone.utc)
            await self.db.flush()

        return profile


async def get_effective_skill_level(
    skill: SkillWithConfidence,
) -> float:
    """Calculate effective skill level accounting for confidence and recency.

    Returns:
        Effective skill level (0-100).
    """
    # Adjust proficiency by confidence and recency
    return skill.proficiency * skill.confidence * skill.recency_factor


async def compare_developer_expertise(
    db: AsyncSession,
    developer_ids: list[str],
    skill_name: str,
) -> list[dict]:
    """Compare expertise in a specific skill across developers.

    Args:
        db: Database session.
        developer_ids: List of developer UUIDs.
        skill_name: Skill to compare.

    Returns:
        List of developers with their skill metrics.
    """
    stmt = (
        select(Developer)
        .where(Developer.id.in_(developer_ids))
    )
    result = await db.execute(stmt)
    developers = result.scalars().all()

    comparisons = []
    skill_lower = skill_name.lower()

    for dev in developers:
        if not dev.expertise_confidence:
            continue

        skills = dev.expertise_confidence.get("skills", [])
        matching_skill = next(
            (s for s in skills if s.get("name", "").lower() == skill_lower),
            None,
        )

        if matching_skill:
            effective_level = (
                matching_skill["proficiency"] *
                matching_skill["confidence"] *
                matching_skill["recency_factor"]
            )
            comparisons.append({
                "developer_id": dev.id,
                "developer_name": dev.name,
                "skill": matching_skill,
                "effective_level": round(effective_level, 1),
            })

    # Sort by effective level
    comparisons.sort(key=lambda x: -x["effective_level"])

    return comparisons
