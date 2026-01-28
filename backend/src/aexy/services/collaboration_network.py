"""Collaboration network analysis service.

Analyzes developer collaboration patterns from:
- PR reviews (who reviews whose code)
- Co-authorship patterns
- Cross-team interactions

Builds a collaboration graph to identify:
- Key collaborators per developer
- Knowledge silos (single points of failure)
- Team cohesion scores
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.activity import CodeReview, PullRequest
from aexy.models.developer import Developer

logger = logging.getLogger(__name__)


@dataclass
class CollaborationEdge:
    """Represents a collaboration relationship between two developers."""
    developer_a_id: str
    developer_b_id: str
    developer_a_name: str | None
    developer_b_name: str | None
    interaction_count: int
    review_count: int
    co_author_count: int
    strength_score: float
    interaction_types: list[str]
    last_interaction_at: datetime | None

    def to_dict(self) -> dict:
        return {
            "developer_a_id": self.developer_a_id,
            "developer_b_id": self.developer_b_id,
            "developer_a_name": self.developer_a_name,
            "developer_b_name": self.developer_b_name,
            "interaction_count": self.interaction_count,
            "review_count": self.review_count,
            "co_author_count": self.co_author_count,
            "strength_score": round(self.strength_score, 2),
            "interaction_types": self.interaction_types,
            "last_interaction_at": self.last_interaction_at.isoformat() if self.last_interaction_at else None,
        }


@dataclass
class CollaboratorProfile:
    """Profile of a developer's top collaborators."""
    developer_id: str
    developer_name: str | None
    total_collaborators: int
    top_collaborators: list[dict]
    collaboration_diversity: float  # 0-1, higher = more diverse
    is_knowledge_silo: bool
    silo_indicators: list[str]

    def to_dict(self) -> dict:
        return {
            "developer_id": self.developer_id,
            "developer_name": self.developer_name,
            "total_collaborators": self.total_collaborators,
            "top_collaborators": self.top_collaborators,
            "collaboration_diversity": round(self.collaboration_diversity, 2),
            "is_knowledge_silo": self.is_knowledge_silo,
            "silo_indicators": self.silo_indicators,
        }


@dataclass
class TeamCohesion:
    """Team-level collaboration metrics."""
    team_size: int
    total_edges: int
    avg_collaborations_per_developer: float
    cohesion_score: float  # 0-1
    density: float  # actual edges / possible edges
    knowledge_silos: list[dict]
    central_connectors: list[dict]
    isolated_developers: list[dict]

    def to_dict(self) -> dict:
        return {
            "team_size": self.team_size,
            "total_edges": self.total_edges,
            "avg_collaborations_per_developer": round(self.avg_collaborations_per_developer, 2),
            "cohesion_score": round(self.cohesion_score, 2),
            "density": round(self.density, 3),
            "knowledge_silos": self.knowledge_silos,
            "central_connectors": self.central_connectors,
            "isolated_developers": self.isolated_developers,
        }


class CollaborationNetworkAnalyzer:
    """Analyzes collaboration patterns between developers."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def build_collaboration_graph(
        self,
        developer_ids: list[str],
        days: int = 180,
    ) -> list[CollaborationEdge]:
        """Build collaboration graph for a set of developers.

        Args:
            developer_ids: List of developer UUIDs to analyze.
            days: Days of history to consider.

        Returns:
            List of collaboration edges.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # Get all code reviews where reviewer is in our set
        # and the PR author is also in our set
        review_stmt = (
            select(CodeReview)
            .where(
                CodeReview.developer_id.in_(developer_ids),
                CodeReview.submitted_at >= cutoff,
            )
        )
        review_result = await self.db.execute(review_stmt)
        reviews = review_result.scalars().all()

        # Get PRs to find authors
        pr_github_ids = list(set(r.pull_request_github_id for r in reviews))
        pr_stmt = (
            select(PullRequest)
            .where(PullRequest.github_id.in_(pr_github_ids))
        )
        pr_result = await self.db.execute(pr_stmt)
        prs = {pr.github_id: pr for pr in pr_result.scalars().all()}

        # Get developer names
        dev_stmt = select(Developer).where(Developer.id.in_(developer_ids))
        dev_result = await self.db.execute(dev_stmt)
        developers = {d.id: d for d in dev_result.scalars().all()}

        # Build edge map
        edge_map: dict[tuple[str, str], dict] = {}

        for review in reviews:
            pr = prs.get(review.pull_request_github_id)
            if not pr or pr.developer_id not in developer_ids:
                continue

            reviewer_id = review.developer_id
            author_id = pr.developer_id

            # Skip self-reviews
            if reviewer_id == author_id:
                continue

            # Normalize edge key (smaller ID first)
            key = tuple(sorted([reviewer_id, author_id]))

            if key not in edge_map:
                edge_map[key] = {
                    "review_count": 0,
                    "co_author_count": 0,
                    "last_interaction": None,
                    "types": set(),
                }

            edge_map[key]["review_count"] += 1
            edge_map[key]["types"].add("reviewed")
            if edge_map[key]["last_interaction"] is None or review.submitted_at > edge_map[key]["last_interaction"]:
                edge_map[key]["last_interaction"] = review.submitted_at

        # Convert to CollaborationEdge objects
        edges = []
        for (dev_a, dev_b), data in edge_map.items():
            interaction_count = data["review_count"] + data["co_author_count"]
            strength = self._calculate_strength(
                interaction_count,
                data["review_count"],
                data["co_author_count"],
                data["last_interaction"],
            )

            edges.append(CollaborationEdge(
                developer_a_id=dev_a,
                developer_b_id=dev_b,
                developer_a_name=developers.get(dev_a, {}).name if dev_a in developers else None,
                developer_b_name=developers.get(dev_b, {}).name if dev_b in developers else None,
                interaction_count=interaction_count,
                review_count=data["review_count"],
                co_author_count=data["co_author_count"],
                strength_score=strength,
                interaction_types=list(data["types"]),
                last_interaction_at=data["last_interaction"],
            ))

        # Sort by strength
        edges.sort(key=lambda e: -e.strength_score)

        return edges

    def _calculate_strength(
        self,
        total_interactions: int,
        reviews: int,
        co_authors: int,
        last_interaction: datetime | None,
    ) -> float:
        """Calculate collaboration strength score (0-1)."""
        # Base score from interaction count (log scale)
        import math
        base_score = min(1.0, math.log10(total_interactions + 1) / 2)

        # Boost for co-authorship (stronger signal)
        co_author_boost = min(0.2, co_authors * 0.05)

        # Recency factor
        recency = 1.0
        if last_interaction:
            days_ago = (datetime.now(timezone.utc) - last_interaction).days
            recency = max(0.5, 1.0 - (days_ago / 365))

        return min(1.0, (base_score + co_author_boost) * recency)

    async def get_developer_collaborators(
        self,
        developer_id: str,
        days: int = 180,
        limit: int = 10,
    ) -> CollaboratorProfile:
        """Get top collaborators for a specific developer.

        Args:
            developer_id: Developer UUID.
            days: Days of history.
            limit: Max collaborators to return.

        Returns:
            CollaboratorProfile with top collaborators.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # Get developer info
        dev_stmt = select(Developer).where(Developer.id == developer_id)
        dev_result = await self.db.execute(dev_stmt)
        developer = dev_result.scalar_one_or_none()

        # Get reviews this developer made
        reviews_given_stmt = (
            select(CodeReview)
            .where(
                CodeReview.developer_id == developer_id,
                CodeReview.submitted_at >= cutoff,
            )
        )
        reviews_given_result = await self.db.execute(reviews_given_stmt)
        reviews_given = reviews_given_result.scalars().all()

        # Get PRs this developer authored that were reviewed
        prs_authored_stmt = (
            select(PullRequest)
            .where(
                PullRequest.developer_id == developer_id,
                PullRequest.created_at_github >= cutoff,
            )
        )
        prs_authored_result = await self.db.execute(prs_authored_stmt)
        prs_authored = prs_authored_result.scalars().all()

        # Get reviews on this developer's PRs
        pr_github_ids = [pr.github_id for pr in prs_authored]
        reviews_received_stmt = (
            select(CodeReview)
            .where(
                CodeReview.pull_request_github_id.in_(pr_github_ids),
                CodeReview.developer_id != developer_id,
            )
        )
        reviews_received_result = await self.db.execute(reviews_received_stmt)
        reviews_received = reviews_received_result.scalars().all()

        # Build collaborator map
        collaborator_counts: dict[str, dict] = {}

        # From reviews given
        pr_ids = [r.pull_request_github_id for r in reviews_given]
        if pr_ids:
            pr_stmt = select(PullRequest).where(PullRequest.github_id.in_(pr_ids))
            pr_result = await self.db.execute(pr_stmt)
            pr_map = {pr.github_id: pr for pr in pr_result.scalars().all()}

            for review in reviews_given:
                pr = pr_map.get(review.pull_request_github_id)
                if pr and pr.developer_id != developer_id:
                    author_id = pr.developer_id
                    if author_id not in collaborator_counts:
                        collaborator_counts[author_id] = {"reviews_given": 0, "reviews_received": 0}
                    collaborator_counts[author_id]["reviews_given"] += 1

        # From reviews received
        for review in reviews_received:
            reviewer_id = review.developer_id
            if reviewer_id not in collaborator_counts:
                collaborator_counts[reviewer_id] = {"reviews_given": 0, "reviews_received": 0}
            collaborator_counts[reviewer_id]["reviews_received"] += 1

        # Get collaborator names
        collab_ids = list(collaborator_counts.keys())
        if collab_ids:
            collab_dev_stmt = select(Developer).where(Developer.id.in_(collab_ids))
            collab_dev_result = await self.db.execute(collab_dev_stmt)
            collab_devs = {d.id: d for d in collab_dev_result.scalars().all()}
        else:
            collab_devs = {}

        # Build top collaborators list
        top_collaborators = []
        for collab_id, counts in sorted(
            collaborator_counts.items(),
            key=lambda x: -(x[1]["reviews_given"] + x[1]["reviews_received"]),
        )[:limit]:
            collab_dev = collab_devs.get(collab_id)
            total = counts["reviews_given"] + counts["reviews_received"]
            top_collaborators.append({
                "developer_id": collab_id,
                "name": collab_dev.name if collab_dev else None,
                "email": collab_dev.email if collab_dev else None,
                "reviews_given": counts["reviews_given"],
                "reviews_received": counts["reviews_received"],
                "total_interactions": total,
            })

        # Calculate collaboration diversity
        total_collaborators = len(collaborator_counts)
        if total_collaborators == 0:
            diversity = 0.0
        else:
            # Higher diversity = interactions spread across many people
            interaction_counts = [
                c["reviews_given"] + c["reviews_received"]
                for c in collaborator_counts.values()
            ]
            total_interactions = sum(interaction_counts)
            if total_interactions > 0:
                # Entropy-based diversity
                import math
                entropy = 0
                for count in interaction_counts:
                    if count > 0:
                        p = count / total_interactions
                        entropy -= p * math.log2(p)
                max_entropy = math.log2(total_collaborators) if total_collaborators > 1 else 1
                diversity = entropy / max_entropy if max_entropy > 0 else 0
            else:
                diversity = 0.0

        # Detect knowledge silo indicators
        silo_indicators = []
        is_silo = False

        if total_collaborators <= 2 and len(reviews_given) + len(reviews_received) > 10:
            is_silo = True
            silo_indicators.append("Limited collaborator diversity despite high activity")

        if top_collaborators and len(top_collaborators) >= 2:
            top_interaction = top_collaborators[0]["total_interactions"]
            second_interaction = top_collaborators[1]["total_interactions"]
            if top_interaction > second_interaction * 5:
                is_silo = True
                silo_indicators.append(f"Heavy dependency on single collaborator ({top_collaborators[0]['name']})")

        return CollaboratorProfile(
            developer_id=developer_id,
            developer_name=developer.name if developer else None,
            total_collaborators=total_collaborators,
            top_collaborators=top_collaborators,
            collaboration_diversity=diversity,
            is_knowledge_silo=is_silo,
            silo_indicators=silo_indicators,
        )

    async def analyze_team_cohesion(
        self,
        developer_ids: list[str],
        days: int = 180,
    ) -> TeamCohesion:
        """Analyze team-level collaboration cohesion.

        Args:
            developer_ids: List of developer UUIDs in the team.
            days: Days of history.

        Returns:
            TeamCohesion metrics.
        """
        edges = await self.build_collaboration_graph(developer_ids, days)

        team_size = len(developer_ids)
        total_edges = len(edges)

        # Calculate density (actual edges / possible edges)
        possible_edges = team_size * (team_size - 1) / 2 if team_size > 1 else 1
        density = total_edges / possible_edges if possible_edges > 0 else 0

        # Count collaborations per developer
        collab_counts: dict[str, int] = {dev_id: 0 for dev_id in developer_ids}
        for edge in edges:
            if edge.developer_a_id in collab_counts:
                collab_counts[edge.developer_a_id] += 1
            if edge.developer_b_id in collab_counts:
                collab_counts[edge.developer_b_id] += 1

        avg_collaborations = sum(collab_counts.values()) / team_size if team_size > 0 else 0

        # Identify isolated developers (no collaborations)
        isolated = [{"developer_id": dev_id, "collaborations": 0}
                    for dev_id, count in collab_counts.items() if count == 0]

        # Identify central connectors (high collaboration count)
        sorted_by_collab = sorted(collab_counts.items(), key=lambda x: -x[1])
        central = [{"developer_id": dev_id, "collaborations": count}
                   for dev_id, count in sorted_by_collab[:3] if count > 0]

        # Identify knowledge silos
        knowledge_silos = []
        for dev_id in developer_ids:
            profile = await self.get_developer_collaborators(dev_id, days, limit=5)
            if profile.is_knowledge_silo:
                knowledge_silos.append({
                    "developer_id": dev_id,
                    "developer_name": profile.developer_name,
                    "indicators": profile.silo_indicators,
                })

        # Calculate cohesion score (combination of density and diversity)
        # Higher is better
        cohesion_score = (density * 0.5 + (1 - len(isolated) / max(team_size, 1)) * 0.3 +
                         (1 - len(knowledge_silos) / max(team_size, 1)) * 0.2)

        return TeamCohesion(
            team_size=team_size,
            total_edges=total_edges,
            avg_collaborations_per_developer=avg_collaborations,
            cohesion_score=cohesion_score,
            density=density,
            knowledge_silos=knowledge_silos,
            central_connectors=central,
            isolated_developers=isolated,
        )


async def get_collaboration_recommendations(
    db: AsyncSession,
    developer_id: str,
    team_developer_ids: list[str],
    days: int = 180,
) -> list[dict]:
    """Get collaboration recommendations for a developer.

    Suggests team members they should collaborate more with based on
    skill complementarity and current low interaction.

    Args:
        db: Database session.
        developer_id: Developer to get recommendations for.
        team_developer_ids: List of team member IDs.
        days: Days of history to analyze.

    Returns:
        List of recommended collaborators.
    """
    analyzer = CollaborationNetworkAnalyzer(db)
    profile = await analyzer.get_developer_collaborators(developer_id, days)

    # Find team members not in top collaborators
    current_collabs = {c["developer_id"] for c in profile.top_collaborators}
    potential = [dev_id for dev_id in team_developer_ids
                 if dev_id != developer_id and dev_id not in current_collabs]

    if not potential:
        return []

    # Get developer skills for matching
    dev_stmt = select(Developer).where(Developer.id.in_(potential + [developer_id]))
    result = await db.execute(dev_stmt)
    devs = {d.id: d for d in result.scalars().all()}

    current_dev = devs.get(developer_id)
    current_skills = set()
    if current_dev and current_dev.skill_fingerprint:
        languages = current_dev.skill_fingerprint.get("languages", [])
        current_skills = {l.get("name", "").lower() for l in languages}

    recommendations = []
    for pot_id in potential:
        pot_dev = devs.get(pot_id)
        if not pot_dev:
            continue

        pot_skills = set()
        if pot_dev.skill_fingerprint:
            languages = pot_dev.skill_fingerprint.get("languages", [])
            pot_skills = {l.get("name", "").lower() for l in languages}

        # Calculate complementarity (different skills = good for learning)
        unique_skills = pot_skills - current_skills
        shared_skills = pot_skills & current_skills

        recommendations.append({
            "developer_id": pot_id,
            "name": pot_dev.name,
            "email": pot_dev.email,
            "reason": "skill_complementarity" if unique_skills else "same_tech_stack",
            "complementary_skills": list(unique_skills)[:5],
            "shared_skills": list(shared_skills)[:5],
        })

    # Sort by complementarity
    recommendations.sort(key=lambda x: -len(x["complementary_skills"]))

    return recommendations[:5]
