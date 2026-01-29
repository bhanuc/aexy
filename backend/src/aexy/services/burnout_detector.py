"""Burnout risk detection service.

Analyzes developer work patterns to identify burnout risk indicators:
- After-hours commit patterns
- Weekend work frequency
- PR review fatigue (declining quality)
- Sustained high activity
- Work-life balance indicators
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.activity import CodeReview, Commit, PullRequest
from aexy.models.developer import Developer

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    """Burnout risk levels."""
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


# Business hours configuration (can be made configurable per user)
BUSINESS_HOURS_START = 9   # 9 AM
BUSINESS_HOURS_END = 18    # 6 PM
WEEKEND_DAYS = {5, 6}      # Saturday=5, Sunday=6


# Risk thresholds
THRESHOLDS = {
    "after_hours_percentage_moderate": 25,
    "after_hours_percentage_high": 40,
    "weekend_commits_moderate": 15,
    "weekend_commits_high": 30,
    "consecutive_high_days_moderate": 5,
    "consecutive_high_days_high": 10,
    "days_since_break_moderate": 30,
    "days_since_break_high": 60,
    "daily_commits_high": 15,
    "review_decline_percentage": 20,
}


@dataclass
class WorkPatternMetrics:
    """Calculated work pattern metrics."""
    total_commits: int = 0
    after_hours_commits: int = 0
    weekend_commits: int = 0
    avg_daily_commits: float = 0.0
    peak_hours: list[int] = field(default_factory=list)
    consecutive_high_activity_days: int = 0
    days_since_break: int = 0
    review_quality_trend: str = "stable"
    avg_pr_size: int = 0
    review_turnaround_hours: float = 0.0


@dataclass
class BurnoutIndicators:
    """Burnout risk assessment result."""
    risk_score: float  # 0.0 - 1.0
    risk_level: RiskLevel
    indicators: dict
    alerts: list[str]
    trend: Literal["improving", "stable", "worsening"]
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """Convert to dictionary for JSONB storage."""
        return {
            "risk_score": round(self.risk_score, 2),
            "risk_level": self.risk_level.value,
            "indicators": self.indicators,
            "alerts": self.alerts,
            "trend": self.trend,
            "updated_at": self.updated_at.isoformat(),
        }


class BurnoutDetector:
    """Detects burnout risk from developer work patterns."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def analyze_developer(
        self,
        developer_id: str,
        days: int = 30,
    ) -> BurnoutIndicators:
        """Analyze burnout risk for a developer.

        Args:
            developer_id: Developer UUID.
            days: Number of days to analyze.

        Returns:
            BurnoutIndicators with risk assessment.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # Calculate work pattern metrics
        metrics = await self._calculate_work_patterns(developer_id, cutoff)

        # Calculate risk score and generate alerts
        risk_score, alerts = self._calculate_risk_score(metrics)

        # Determine risk level
        risk_level = self._get_risk_level(risk_score)

        # Determine trend (compare to previous period)
        trend = await self._calculate_trend(developer_id, days)

        return BurnoutIndicators(
            risk_score=risk_score,
            risk_level=risk_level,
            indicators={
                "after_hours_percentage": round(
                    metrics.after_hours_commits / max(metrics.total_commits, 1) * 100, 1
                ),
                "weekend_commits_percentage": round(
                    metrics.weekend_commits / max(metrics.total_commits, 1) * 100, 1
                ),
                "avg_daily_commits": round(metrics.avg_daily_commits, 1),
                "review_quality_trend": metrics.review_quality_trend,
                "consecutive_high_activity_days": metrics.consecutive_high_activity_days,
                "days_since_break": metrics.days_since_break,
                "peak_hours": metrics.peak_hours,
            },
            alerts=alerts,
            trend=trend,
        )

    async def _calculate_work_patterns(
        self,
        developer_id: str,
        cutoff: datetime,
    ) -> WorkPatternMetrics:
        """Calculate work pattern metrics from commit history."""
        # Fetch commits
        commit_stmt = (
            select(Commit)
            .where(
                Commit.developer_id == developer_id,
                Commit.committed_at >= cutoff,
            )
            .order_by(Commit.committed_at)
        )
        result = await self.db.execute(commit_stmt)
        commits = result.scalars().all()

        if not commits:
            return WorkPatternMetrics()

        # Calculate basic metrics
        total_commits = len(commits)
        after_hours = 0
        weekend = 0
        hour_counts: dict[int, int] = {}
        daily_commits: dict[str, int] = {}

        for commit in commits:
            committed_at = commit.committed_at
            if committed_at.tzinfo is None:
                committed_at = committed_at.replace(tzinfo=timezone.utc)

            hour = committed_at.hour
            day = committed_at.strftime("%Y-%m-%d")

            # Count hour distribution
            hour_counts[hour] = hour_counts.get(hour, 0) + 1

            # Count daily commits
            daily_commits[day] = daily_commits.get(day, 0) + 1

            # Check if after hours
            if hour < BUSINESS_HOURS_START or hour >= BUSINESS_HOURS_END:
                after_hours += 1

            # Check if weekend
            if committed_at.weekday() in WEEKEND_DAYS:
                weekend += 1

        # Peak hours (top 3)
        peak_hours = sorted(hour_counts.keys(), key=lambda h: -hour_counts[h])[:3]

        # Average daily commits
        days_active = len(daily_commits)
        avg_daily = total_commits / max(days_active, 1)

        # Consecutive high activity days
        consecutive_high = self._count_consecutive_high_days(
            daily_commits, threshold=THRESHOLDS["daily_commits_high"]
        )

        # Days since break (no commits)
        days_since_break = self._calculate_days_since_break(daily_commits)

        # Review quality trend
        review_trend = await self._analyze_review_quality_trend(developer_id, cutoff)

        return WorkPatternMetrics(
            total_commits=total_commits,
            after_hours_commits=after_hours,
            weekend_commits=weekend,
            avg_daily_commits=avg_daily,
            peak_hours=peak_hours,
            consecutive_high_activity_days=consecutive_high,
            days_since_break=days_since_break,
            review_quality_trend=review_trend,
        )

    def _count_consecutive_high_days(
        self,
        daily_commits: dict[str, int],
        threshold: int,
    ) -> int:
        """Count maximum consecutive days with high activity."""
        if not daily_commits:
            return 0

        sorted_days = sorted(daily_commits.keys())
        max_consecutive = 0
        current_consecutive = 0

        prev_date = None
        for day_str in sorted_days:
            current_date = datetime.strptime(day_str, "%Y-%m-%d").date()
            is_high = daily_commits[day_str] >= threshold

            if is_high:
                if prev_date and (current_date - prev_date).days == 1:
                    current_consecutive += 1
                else:
                    current_consecutive = 1
                max_consecutive = max(max_consecutive, current_consecutive)
            else:
                current_consecutive = 0

            prev_date = current_date

        return max_consecutive

    def _calculate_days_since_break(self, daily_commits: dict[str, int]) -> int:
        """Calculate days since last break (2+ consecutive days off)."""
        if not daily_commits:
            return 0

        sorted_days = sorted(daily_commits.keys())
        today = datetime.now(timezone.utc).date()

        # Find the last 2+ day break
        last_break_end = None
        gap_count = 0

        for i in range(len(sorted_days) - 1, 0, -1):
            current = datetime.strptime(sorted_days[i], "%Y-%m-%d").date()
            prev = datetime.strptime(sorted_days[i - 1], "%Y-%m-%d").date()
            gap = (current - prev).days - 1  # Days between commits

            if gap >= 2:  # 2+ days off in a row
                last_break_end = prev
                break

        if last_break_end:
            return (today - last_break_end).days
        else:
            # No break found, use first commit date
            first_day = datetime.strptime(sorted_days[0], "%Y-%m-%d").date()
            return (today - first_day).days

    async def _analyze_review_quality_trend(
        self,
        developer_id: str,
        cutoff: datetime,
    ) -> str:
        """Analyze if review quality is declining."""
        # Fetch reviews with quality metrics
        stmt = (
            select(CodeReview)
            .where(
                CodeReview.developer_id == developer_id,
                CodeReview.submitted_at >= cutoff,
            )
            .order_by(CodeReview.submitted_at)
        )
        result = await self.db.execute(stmt)
        reviews = result.scalars().all()

        if len(reviews) < 5:
            return "stable"

        # Compare first half vs second half
        mid = len(reviews) // 2
        first_half = reviews[:mid]
        second_half = reviews[mid:]

        def avg_comments(review_list):
            return sum(r.comments_count for r in review_list) / len(review_list) if review_list else 0

        first_avg = avg_comments(first_half)
        second_avg = avg_comments(second_half)

        if first_avg == 0:
            return "stable"

        change_pct = (second_avg - first_avg) / first_avg * 100

        if change_pct < -THRESHOLDS["review_decline_percentage"]:
            return "declining"
        elif change_pct > THRESHOLDS["review_decline_percentage"]:
            return "improving"
        else:
            return "stable"

    def _calculate_risk_score(self, metrics: WorkPatternMetrics) -> tuple[float, list[str]]:
        """Calculate overall risk score and generate alerts."""
        score = 0.0
        alerts = []

        if metrics.total_commits == 0:
            return 0.0, []

        # After-hours percentage (weight: 25%)
        after_hours_pct = metrics.after_hours_commits / metrics.total_commits * 100
        if after_hours_pct >= THRESHOLDS["after_hours_percentage_high"]:
            score += 0.25
            alerts.append(f"{after_hours_pct:.0f}% commits outside business hours (high)")
        elif after_hours_pct >= THRESHOLDS["after_hours_percentage_moderate"]:
            score += 0.15
            alerts.append(f"{after_hours_pct:.0f}% commits outside business hours")

        # Weekend commits (weight: 20%)
        weekend_pct = metrics.weekend_commits / metrics.total_commits * 100
        if weekend_pct >= THRESHOLDS["weekend_commits_high"]:
            score += 0.20
            alerts.append(f"{weekend_pct:.0f}% commits on weekends (high)")
        elif weekend_pct >= THRESHOLDS["weekend_commits_moderate"]:
            score += 0.10
            alerts.append(f"{weekend_pct:.0f}% commits on weekends")

        # Consecutive high activity days (weight: 20%)
        if metrics.consecutive_high_activity_days >= THRESHOLDS["consecutive_high_days_high"]:
            score += 0.20
            alerts.append(
                f"{metrics.consecutive_high_activity_days} consecutive high-activity days"
            )
        elif metrics.consecutive_high_activity_days >= THRESHOLDS["consecutive_high_days_moderate"]:
            score += 0.10

        # Days since break (weight: 20%)
        if metrics.days_since_break >= THRESHOLDS["days_since_break_high"]:
            score += 0.20
            alerts.append(
                f"No break detected in {metrics.days_since_break} days"
            )
        elif metrics.days_since_break >= THRESHOLDS["days_since_break_moderate"]:
            score += 0.10

        # Review quality decline (weight: 15%)
        if metrics.review_quality_trend == "declining":
            score += 0.15
            alerts.append("Review quality appears to be declining")

        return min(1.0, score), alerts

    def _get_risk_level(self, score: float) -> RiskLevel:
        """Map score to risk level."""
        if score >= 0.75:
            return RiskLevel.CRITICAL
        elif score >= 0.5:
            return RiskLevel.HIGH
        elif score >= 0.25:
            return RiskLevel.MODERATE
        else:
            return RiskLevel.LOW

    async def _calculate_trend(
        self,
        developer_id: str,
        days: int,
    ) -> Literal["improving", "stable", "worsening"]:
        """Compare current period to previous period to determine trend."""
        # Get developer's current burnout indicators
        dev_stmt = select(Developer).where(Developer.id == developer_id)
        result = await self.db.execute(dev_stmt)
        developer = result.scalar_one_or_none()

        if not developer or not developer.burnout_indicators:
            return "stable"

        previous_score = developer.burnout_indicators.get("risk_score", 0)

        # Calculate current score
        current_cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        current_metrics = await self._calculate_work_patterns(developer_id, current_cutoff)
        current_score, _ = self._calculate_risk_score(current_metrics)

        # Determine trend
        diff = current_score - previous_score
        if diff > 0.1:
            return "worsening"
        elif diff < -0.1:
            return "improving"
        else:
            return "stable"

    async def update_developer_burnout_indicators(
        self,
        developer_id: str,
        days: int = 30,
    ) -> BurnoutIndicators:
        """Update and store burnout indicators for a developer.

        Args:
            developer_id: Developer UUID.
            days: Days to analyze.

        Returns:
            Updated burnout indicators.
        """
        indicators = await self.analyze_developer(developer_id, days)

        # Update developer record
        dev_stmt = select(Developer).where(Developer.id == developer_id)
        result = await self.db.execute(dev_stmt)
        developer = result.scalar_one_or_none()

        if developer:
            developer.burnout_indicators = indicators.to_dict()
            developer.last_intelligence_analysis_at = datetime.now(timezone.utc)
            await self.db.flush()

        return indicators


async def get_team_burnout_overview(
    db: AsyncSession,
    developer_ids: list[str],
) -> dict:
    """Get burnout risk overview for a team.

    Args:
        db: Database session.
        developer_ids: List of developer UUIDs.

    Returns:
        Team-level burnout statistics.
    """
    stmt = (
        select(Developer)
        .where(Developer.id.in_(developer_ids))
    )
    result = await db.execute(stmt)
    developers = result.scalars().all()

    risk_levels = {"low": 0, "moderate": 0, "high": 0, "critical": 0}
    high_risk_developers = []

    for dev in developers:
        if dev.burnout_indicators:
            level = dev.burnout_indicators.get("risk_level", "low")
            risk_levels[level] = risk_levels.get(level, 0) + 1

            if level in ("high", "critical"):
                high_risk_developers.append({
                    "id": dev.id,
                    "name": dev.name,
                    "email": dev.email,
                    "risk_score": dev.burnout_indicators.get("risk_score"),
                    "risk_level": level,
                    "alerts": dev.burnout_indicators.get("alerts", []),
                })

    total = len(developers)
    return {
        "total_developers": total,
        "risk_distribution": risk_levels,
        "risk_percentages": {
            k: round(v / max(total, 1) * 100, 1)
            for k, v in risk_levels.items()
        },
        "high_risk_developers": high_risk_developers,
        "team_health_score": round(
            (risk_levels["low"] * 100 + risk_levels["moderate"] * 70 +
             risk_levels["high"] * 30 + risk_levels["critical"] * 0) / max(total, 1), 1
        ),
    }
