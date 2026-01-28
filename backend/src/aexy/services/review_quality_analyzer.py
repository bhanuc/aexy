"""Code review quality analyzer.

Analyzes code review comments for quality metrics:
- Depth scoring (1-5 scale)
- Thoroughness classification
- Mentoring indicators
- Response time tracking
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.activity import CodeReview, PullRequest

logger = logging.getLogger(__name__)


# Patterns indicating thorough reviews
THOROUGH_PATTERNS = [
    r"\bwhy\b",           # Explains reasoning
    r"\bbecause\b",       # Provides explanation
    r"\bsuggestion\b",    # Offers alternatives
    r"\balternative\b",   # Offers alternatives
    r"\bconsider\b",      # Thoughtful suggestion
    r"\binstead\b",       # Offers alternative
    r"\bexample\b",       # Provides examples
    r"```",               # Code blocks
    r"\bsecurity\b",      # Security awareness
    r"\bperformance\b",   # Performance awareness
    r"\bedge case\b",     # Edge case consideration
    r"\bwhat if\b",       # Scenario thinking
]

# Patterns indicating mentoring
MENTORING_PATTERNS = [
    (r"\bexplains?\s+why\b", "explains_why"),
    (r"\bfor example\b", "provides_examples"),
    (r"\blearn\b", "teaching_moment"),
    (r"\btip\b", "gives_tips"),
    (r"\bbest practice\b", "shares_best_practices"),
    (r"\bi'd recommend\b", "gives_recommendations"),
    (r"\bone approach\b", "offers_alternatives"),
    (r"\bsee\s+(?:the\s+)?docs?\b", "references_docs"),
    (r"https?://", "shares_resources"),
    (r"\btry\b.*\binstead\b", "suggests_improvements"),
]

# Superficial review patterns (negative indicators)
SUPERFICIAL_PATTERNS = [
    r"^lgtm$",
    r"^\+1$",
    r"^nice$",
    r"^looks good$",
    r"^approved?$",
    r"^ok$",
    r"^👍$",
    r"^shipit$",
]


@dataclass
class ReviewQualityMetrics:
    """Quality metrics for a code review."""
    depth_score: float  # 1-5 scale
    thoroughness: Literal["cursory", "standard", "detailed", "exhaustive"]
    has_suggestions: bool
    has_code_examples: bool
    mentoring_indicators: list[str]
    word_count: int
    code_block_count: int
    question_count: int
    analyzed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """Convert to dictionary for JSONB storage."""
        return {
            "depth_score": round(self.depth_score, 1),
            "thoroughness": self.thoroughness,
            "has_suggestions": self.has_suggestions,
            "has_code_examples": self.has_code_examples,
            "mentoring_indicators": self.mentoring_indicators,
            "word_count": self.word_count,
            "code_block_count": self.code_block_count,
            "question_count": self.question_count,
            "analyzed_at": self.analyzed_at.isoformat(),
        }


class ReviewQualityAnalyzer:
    """Analyzes code review quality."""

    def __init__(self, db: AsyncSession):
        self.db = db

    def analyze_review(self, review: CodeReview) -> ReviewQualityMetrics:
        """Analyze a single code review.

        Args:
            review: CodeReview model instance.

        Returns:
            ReviewQualityMetrics with quality assessment.
        """
        body = review.body or ""
        comments_count = review.comments_count or 0

        # Basic text analysis
        word_count = len(body.split())
        code_blocks = len(re.findall(r"```", body)) // 2  # Pairs of backticks
        questions = len(re.findall(r"\?", body))

        # Check for superficial review
        body_lower = body.strip().lower()
        is_superficial = any(
            re.match(pattern, body_lower, re.IGNORECASE)
            for pattern in SUPERFICIAL_PATTERNS
        )

        if is_superficial:
            return ReviewQualityMetrics(
                depth_score=1.0,
                thoroughness="cursory",
                has_suggestions=False,
                has_code_examples=False,
                mentoring_indicators=[],
                word_count=word_count,
                code_block_count=code_blocks,
                question_count=questions,
            )

        # Calculate depth score
        depth_score = self._calculate_depth_score(
            body, word_count, code_blocks, questions, comments_count
        )

        # Determine thoroughness
        thoroughness = self._classify_thoroughness(depth_score)

        # Check for suggestions
        has_suggestions = bool(
            re.search(r"\bsuggestion\b|\brecommend\b|\bconsider\b|\binstead\b", body_lower)
        )

        # Check for code examples
        has_code_examples = code_blocks > 0

        # Extract mentoring indicators
        mentoring_indicators = self._extract_mentoring_indicators(body)

        return ReviewQualityMetrics(
            depth_score=depth_score,
            thoroughness=thoroughness,
            has_suggestions=has_suggestions,
            has_code_examples=has_code_examples,
            mentoring_indicators=mentoring_indicators,
            word_count=word_count,
            code_block_count=code_blocks,
            question_count=questions,
        )

    def _calculate_depth_score(
        self,
        body: str,
        word_count: int,
        code_blocks: int,
        questions: int,
        comments_count: int,
    ) -> float:
        """Calculate review depth score (1-5 scale)."""
        score = 1.0  # Base score

        # Word count contribution (max +1.5)
        if word_count >= 200:
            score += 1.5
        elif word_count >= 100:
            score += 1.0
        elif word_count >= 50:
            score += 0.5
        elif word_count >= 20:
            score += 0.25

        # Code examples contribution (max +0.5)
        if code_blocks >= 2:
            score += 0.5
        elif code_blocks >= 1:
            score += 0.25

        # Questions/engagement (max +0.5)
        if questions >= 3:
            score += 0.5
        elif questions >= 1:
            score += 0.25

        # Comments count (max +0.5)
        if comments_count >= 10:
            score += 0.5
        elif comments_count >= 5:
            score += 0.25
        elif comments_count >= 2:
            score += 0.1

        # Pattern matching for thoroughness (max +1.0)
        body_lower = body.lower()
        pattern_matches = sum(
            1 for pattern in THOROUGH_PATTERNS
            if re.search(pattern, body_lower)
        )
        score += min(1.0, pattern_matches * 0.15)

        return min(5.0, score)

    def _classify_thoroughness(
        self,
        depth_score: float,
    ) -> Literal["cursory", "standard", "detailed", "exhaustive"]:
        """Classify thoroughness based on depth score."""
        if depth_score >= 4.0:
            return "exhaustive"
        elif depth_score >= 3.0:
            return "detailed"
        elif depth_score >= 2.0:
            return "standard"
        else:
            return "cursory"

    def _extract_mentoring_indicators(self, body: str) -> list[str]:
        """Extract mentoring pattern indicators from review text."""
        indicators = []
        body_lower = body.lower()

        for pattern, indicator in MENTORING_PATTERNS:
            if re.search(pattern, body_lower):
                if indicator not in indicators:
                    indicators.append(indicator)

        return indicators

    async def analyze_reviews_batch(
        self,
        developer_id: str,
        limit: int = 50,
    ) -> dict:
        """Analyze recent code reviews for a developer.

        Args:
            developer_id: Developer UUID.
            limit: Maximum reviews to analyze.

        Returns:
            Summary statistics and list of analyses.
        """
        # Fetch reviews that haven't been analyzed
        stmt = (
            select(CodeReview)
            .where(
                CodeReview.developer_id == developer_id,
                CodeReview.quality_metrics.is_(None),
            )
            .order_by(CodeReview.submitted_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        reviews = result.scalars().all()

        analyses = []
        thoroughness_counts: dict[str, int] = {}
        total_depth = 0.0
        mentoring_counts: dict[str, int] = {}

        for review in reviews:
            metrics = self.analyze_review(review)

            # Store metrics in the review
            review.quality_metrics = metrics.to_dict()
            analyses.append(metrics)

            # Aggregate stats
            thoroughness = metrics.thoroughness
            thoroughness_counts[thoroughness] = thoroughness_counts.get(thoroughness, 0) + 1
            total_depth += metrics.depth_score

            for indicator in metrics.mentoring_indicators:
                mentoring_counts[indicator] = mentoring_counts.get(indicator, 0) + 1

        # Flush changes
        if reviews:
            await self.db.flush()

        count = len(analyses)
        return {
            "reviews_analyzed": count,
            "average_depth_score": round(total_depth / count, 2) if count else 0,
            "thoroughness_distribution": thoroughness_counts,
            "top_mentoring_indicators": sorted(
                mentoring_counts.items(), key=lambda x: -x[1]
            )[:5],
            "reviews_with_suggestions": sum(1 for a in analyses if a.has_suggestions),
            "reviews_with_code_examples": sum(1 for a in analyses if a.has_code_examples),
        }

    async def get_developer_review_stats(
        self,
        developer_id: str,
        days: int = 90,
    ) -> dict:
        """Get review quality statistics for a developer.

        Args:
            developer_id: Developer UUID.
            days: Number of days to analyze.

        Returns:
            Review quality statistics.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        stmt = (
            select(CodeReview)
            .where(
                CodeReview.developer_id == developer_id,
                CodeReview.submitted_at >= cutoff,
            )
        )
        result = await self.db.execute(stmt)
        reviews = result.scalars().all()

        if not reviews:
            return {
                "total_reviews": 0,
                "average_depth_score": 0,
                "review_rate": "none",
            }

        # Analyze all reviews
        depth_scores = []
        thoroughness_counts: dict[str, int] = {}
        mentoring_all: list[str] = []

        for review in reviews:
            if review.quality_metrics:
                metrics = review.quality_metrics
            else:
                m = self.analyze_review(review)
                review.quality_metrics = m.to_dict()
                metrics = m.to_dict()

            depth_scores.append(metrics.get("depth_score", 2.0))
            th = metrics.get("thoroughness", "standard")
            thoroughness_counts[th] = thoroughness_counts.get(th, 0) + 1
            mentoring_all.extend(metrics.get("mentoring_indicators", []))

        await self.db.flush()

        avg_depth = sum(depth_scores) / len(depth_scores) if depth_scores else 0

        # Classify review rate
        reviews_per_week = len(reviews) / max(days / 7, 1)
        if reviews_per_week >= 10:
            review_rate = "very_active"
        elif reviews_per_week >= 5:
            review_rate = "active"
        elif reviews_per_week >= 2:
            review_rate = "moderate"
        elif reviews_per_week >= 0.5:
            review_rate = "occasional"
        else:
            review_rate = "rare"

        # Count mentoring indicators
        mentoring_counts: dict[str, int] = {}
        for ind in mentoring_all:
            mentoring_counts[ind] = mentoring_counts.get(ind, 0) + 1

        return {
            "total_reviews": len(reviews),
            "average_depth_score": round(avg_depth, 2),
            "thoroughness_distribution": thoroughness_counts,
            "review_rate": review_rate,
            "reviews_per_week": round(reviews_per_week, 1),
            "top_mentoring_behaviors": sorted(
                mentoring_counts.items(), key=lambda x: -x[1]
            )[:5],
            "mentoring_score": min(1.0, len(mentoring_counts) / 5),  # Normalize to 0-1
        }


async def calculate_review_response_time(
    db: AsyncSession,
    developer_id: str,
    days: int = 90,
) -> dict:
    """Calculate average review response time for a developer.

    Args:
        db: Database session.
        developer_id: Developer UUID.
        days: Days to analyze.

    Returns:
        Response time statistics.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Get reviews
    review_stmt = (
        select(CodeReview)
        .where(
            CodeReview.developer_id == developer_id,
            CodeReview.submitted_at >= cutoff,
        )
    )
    result = await db.execute(review_stmt)
    reviews = result.scalars().all()

    if not reviews:
        return {
            "average_response_time_hours": None,
            "reviews_analyzed": 0,
        }

    # Get PRs that were reviewed
    pr_ids = [r.pull_request_github_id for r in reviews]
    pr_stmt = (
        select(PullRequest)
        .where(PullRequest.github_id.in_(pr_ids))
    )
    pr_result = await db.execute(pr_stmt)
    prs = {pr.github_id: pr for pr in pr_result.scalars().all()}

    response_times = []
    for review in reviews:
        pr = prs.get(review.pull_request_github_id)
        if pr and pr.created_at_github and review.submitted_at:
            delta = review.submitted_at - pr.created_at_github
            hours = delta.total_seconds() / 3600
            # Only count reasonable response times (< 7 days)
            if 0 < hours < 168:
                response_times.append(hours)

    if not response_times:
        return {
            "average_response_time_hours": None,
            "reviews_analyzed": len(reviews),
        }

    avg_hours = sum(response_times) / len(response_times)
    median_hours = sorted(response_times)[len(response_times) // 2]

    return {
        "average_response_time_hours": round(avg_hours, 1),
        "median_response_time_hours": round(median_hours, 1),
        "fastest_response_hours": round(min(response_times), 1),
        "slowest_response_hours": round(max(response_times), 1),
        "reviews_analyzed": len(response_times),
    }
