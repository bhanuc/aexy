"""GitHub Intelligence API endpoints.

Exposes enhanced developer intelligence features:
- Semantic commit analysis
- Review quality metrics
- Burnout risk indicators
- Expertise confidence scoring
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.core.database import get_db
from aexy.api.developers import get_current_developer_id
from aexy.models.developer import Developer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/intelligence", tags=["intelligence"])


# =============================================================================
# Request/Response Models
# =============================================================================


class AnalyzeCommitsRequest(BaseModel):
    """Request to analyze commits."""
    limit: int = 100
    use_llm: bool = False


class AnalyzeCommitsResponse(BaseModel):
    """Response from commit analysis."""
    commits_analyzed: int
    type_distribution: dict
    top_tags: list
    average_quality_score: float
    breaking_changes_count: int


class BurnoutRiskResponse(BaseModel):
    """Burnout risk assessment response."""
    risk_score: float
    risk_level: str
    indicators: dict
    alerts: list[str]
    trend: str


class ExpertiseResponse(BaseModel):
    """Expertise profile response."""
    skills: list[dict]
    overall_confidence: float


class ReviewQualityResponse(BaseModel):
    """Review quality statistics response."""
    total_reviews: int
    average_depth_score: float
    thoroughness_distribution: dict
    review_rate: str
    reviews_per_week: float
    top_mentoring_behaviors: list
    mentoring_score: float


class CommitTypeDistributionResponse(BaseModel):
    """Commit type distribution response."""
    total_commits: int
    distribution: dict
    percentages: dict


class TeamBurnoutResponse(BaseModel):
    """Team burnout overview response."""
    total_developers: int
    risk_distribution: dict
    risk_percentages: dict
    high_risk_developers: list
    team_health_score: float


class CollaboratorResponse(BaseModel):
    """Collaborator profile response."""
    developer_id: str
    total_collaborators: int
    top_collaborators: list[dict]
    collaboration_diversity: float
    is_knowledge_silo: bool
    silo_indicators: list[str]


class TeamCohesionResponse(BaseModel):
    """Team cohesion analysis response."""
    team_size: int
    total_edges: int
    density: float
    avg_collaborations_per_developer: float
    cohesion_score: float
    knowledge_silos: list[dict]
    central_connectors: list[dict]
    isolated_developers: list[dict]


class ComplexityProfileResponse(BaseModel):
    """Developer complexity profile response."""
    developer_id: str
    total_prs_analyzed: int
    complexity_distribution: dict
    primary_categories: list[str]
    common_components: list[str]
    common_layers: list[str]
    avg_files_per_pr: float
    avg_complexity_score: float
    cross_cutting_ratio: float
    infrastructure_ratio: float
    handles_critical_changes: bool
    avg_review_effort: str


class TeamComplexityResponse(BaseModel):
    """Team complexity summary response."""
    total_developers: int
    analyzed_developers: int
    avg_complexity_score: float
    avg_cross_cutting_ratio: float
    avg_infrastructure_ratio: float
    critical_change_handlers: int
    team_complexity_distribution: dict


class TechnologyProfileResponse(BaseModel):
    """Developer technology profile response."""
    developer_id: str
    technologies: list[dict]
    current_count: int
    outdated_count: int
    deprecated_count: int
    adoption_score: float
    upgrade_suggestions: list[dict]


class TeamTechnologyResponse(BaseModel):
    """Team technology overview response."""
    total_developers: int
    technologies_tracked: int
    team_health_score: float
    status_distribution: dict
    technologies: list[dict]
    critical_upgrades: list[dict]


# =============================================================================
# Developer Intelligence Endpoints
# =============================================================================


@router.post("/commits/analyze", response_model=AnalyzeCommitsResponse)
async def analyze_developer_commits(
    request: AnalyzeCommitsRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    developer_id: Annotated[str, Depends(get_current_developer_id)],
):
    """Analyze recent commits for the current developer.

    Performs semantic analysis on commit messages to extract:
    - Commit type (feat, fix, refactor, etc.)
    - Scope/component affected
    - Breaking change detection
    - Quality scoring
    - Semantic tags
    """
    from aexy.services.commit_analyzer import CommitAnalyzer

    analyzer = CommitAnalyzer(db)
    result = await analyzer.analyze_commits_batch(
        developer_id=developer_id,
        limit=request.limit,
        use_llm=request.use_llm,
    )

    await db.commit()

    return AnalyzeCommitsResponse(
        commits_analyzed=result["commits_analyzed"],
        type_distribution=result["type_distribution"],
        top_tags=result["top_tags"],
        average_quality_score=result["average_quality_score"],
        breaking_changes_count=result["breaking_changes_count"],
    )


@router.get("/commits/distribution", response_model=CommitTypeDistributionResponse)
async def get_commit_type_distribution(
    db: Annotated[AsyncSession, Depends(get_db)],
    developer_id: Annotated[str, Depends(get_current_developer_id)],
    days: int = Query(default=90, ge=7, le=365),
):
    """Get commit type distribution for the current developer."""
    from aexy.services.commit_analyzer import get_commit_type_distribution

    result = await get_commit_type_distribution(
        db=db,
        developer_id=developer_id,
        days=days,
    )

    return CommitTypeDistributionResponse(**result)


@router.get("/burnout", response_model=BurnoutRiskResponse)
async def get_burnout_risk(
    db: Annotated[AsyncSession, Depends(get_db)],
    developer_id: Annotated[str, Depends(get_current_developer_id)],
    days: int = Query(default=30, ge=7, le=90),
):
    """Get burnout risk assessment for the current developer.

    Analyzes work patterns to identify:
    - After-hours work percentage
    - Weekend work frequency
    - Consecutive high-activity days
    - Days since last break
    - Review quality trends
    """
    from aexy.services.burnout_detector import BurnoutDetector

    detector = BurnoutDetector(db)
    result = await detector.analyze_developer(
        developer_id=developer_id,
        days=days,
    )

    return BurnoutRiskResponse(
        risk_score=result.risk_score,
        risk_level=result.risk_level.value,
        indicators=result.indicators,
        alerts=result.alerts,
        trend=result.trend,
    )


@router.post("/burnout/update", response_model=BurnoutRiskResponse)
async def update_burnout_indicators(
    db: Annotated[AsyncSession, Depends(get_db)],
    developer_id: Annotated[str, Depends(get_current_developer_id)],
    days: int = Query(default=30, ge=7, le=90),
):
    """Update and store burnout indicators for the current developer."""
    from aexy.services.burnout_detector import BurnoutDetector

    detector = BurnoutDetector(db)
    result = await detector.update_developer_burnout_indicators(
        developer_id=developer_id,
        days=days,
    )

    await db.commit()

    return BurnoutRiskResponse(
        risk_score=result.risk_score,
        risk_level=result.risk_level.value,
        indicators=result.indicators,
        alerts=result.alerts,
        trend=result.trend,
    )


@router.get("/expertise", response_model=ExpertiseResponse)
async def get_expertise_profile(
    db: Annotated[AsyncSession, Depends(get_db)],
    developer_id: Annotated[str, Depends(get_current_developer_id)],
    days: int = Query(default=365, ge=30, le=730),
):
    """Get expertise profile with confidence scoring.

    Returns skills with:
    - Proficiency score (0-100)
    - Confidence interval (0-1)
    - Recency factor (decay over time)
    - Depth level (novice/intermediate/advanced/expert)
    - Context (production/personal/learning)
    """
    from aexy.services.expertise_confidence import ExpertiseConfidenceAnalyzer

    analyzer = ExpertiseConfidenceAnalyzer(db)
    result = await analyzer.analyze_developer(
        developer_id=developer_id,
        days=days,
    )

    return ExpertiseResponse(
        skills=[s.to_dict() for s in result.skills],
        overall_confidence=result.overall_confidence,
    )


@router.post("/expertise/update", response_model=ExpertiseResponse)
async def update_expertise_profile(
    db: Annotated[AsyncSession, Depends(get_db)],
    developer_id: Annotated[str, Depends(get_current_developer_id)],
    days: int = Query(default=365, ge=30, le=730),
):
    """Update and store expertise profile for the current developer."""
    from aexy.services.expertise_confidence import ExpertiseConfidenceAnalyzer

    analyzer = ExpertiseConfidenceAnalyzer(db)
    result = await analyzer.update_developer_expertise(
        developer_id=developer_id,
        days=days,
    )

    await db.commit()

    return ExpertiseResponse(
        skills=[s.to_dict() for s in result.skills],
        overall_confidence=result.overall_confidence,
    )


@router.get("/reviews/quality", response_model=ReviewQualityResponse)
async def get_review_quality(
    db: Annotated[AsyncSession, Depends(get_db)],
    developer_id: Annotated[str, Depends(get_current_developer_id)],
    days: int = Query(default=90, ge=7, le=365),
):
    """Get review quality statistics for the current developer.

    Returns:
    - Average depth score (1-5)
    - Thoroughness distribution
    - Review rate classification
    - Mentoring indicators
    """
    from aexy.services.review_quality_analyzer import ReviewQualityAnalyzer

    analyzer = ReviewQualityAnalyzer(db)
    result = await analyzer.get_developer_review_stats(
        developer_id=developer_id,
        days=days,
    )

    await db.commit()

    return ReviewQualityResponse(**result)


@router.post("/reviews/analyze")
async def analyze_reviews(
    db: Annotated[AsyncSession, Depends(get_db)],
    developer_id: Annotated[str, Depends(get_current_developer_id)],
    limit: int = Query(default=50, ge=1, le=200),
):
    """Analyze recent code reviews for the current developer.

    Performs quality analysis on reviews that haven't been analyzed yet.
    """
    from aexy.services.review_quality_analyzer import ReviewQualityAnalyzer

    analyzer = ReviewQualityAnalyzer(db)
    result = await analyzer.analyze_reviews_batch(
        developer_id=developer_id,
        limit=limit,
    )

    await db.commit()

    return result


@router.get("/reviews/response-time")
async def get_review_response_time(
    db: Annotated[AsyncSession, Depends(get_db)],
    developer_id: Annotated[str, Depends(get_current_developer_id)],
    days: int = Query(default=90, ge=7, le=365),
):
    """Get review response time statistics for the current developer."""
    from aexy.services.review_quality_analyzer import calculate_review_response_time

    result = await calculate_review_response_time(
        db=db,
        developer_id=developer_id,
        days=days,
    )

    return result


# =============================================================================
# Full Intelligence Analysis
# =============================================================================


@router.post("/analyze-all")
async def run_full_analysis(
    db: Annotated[AsyncSession, Depends(get_db)],
    developer_id: Annotated[str, Depends(get_current_developer_id)],
    commit_limit: int = Query(default=100, ge=10, le=500),
    review_limit: int = Query(default=50, ge=10, le=200),
    use_llm: bool = False,
):
    """Run full intelligence analysis for the current developer.

    This endpoint runs all analysis types:
    - Semantic commit analysis
    - Review quality analysis
    - Expertise profiling
    - Burnout risk assessment

    Results are stored in the developer's profile.
    """
    from aexy.services.commit_analyzer import CommitAnalyzer
    from aexy.services.review_quality_analyzer import ReviewQualityAnalyzer
    from aexy.services.expertise_confidence import ExpertiseConfidenceAnalyzer
    from aexy.services.burnout_detector import BurnoutDetector

    developer_id = developer_id
    results = {}

    # Commit analysis
    commit_analyzer = CommitAnalyzer(db)
    results["commits"] = await commit_analyzer.analyze_commits_batch(
        developer_id=developer_id,
        limit=commit_limit,
        use_llm=use_llm,
    )

    # Review analysis
    review_analyzer = ReviewQualityAnalyzer(db)
    results["reviews"] = await review_analyzer.analyze_reviews_batch(
        developer_id=developer_id,
        limit=review_limit,
    )

    # Expertise profiling
    expertise_analyzer = ExpertiseConfidenceAnalyzer(db)
    expertise = await expertise_analyzer.update_developer_expertise(developer_id)
    results["expertise"] = expertise.to_dict()

    # Burnout assessment
    burnout_detector = BurnoutDetector(db)
    burnout = await burnout_detector.update_developer_burnout_indicators(developer_id)
    results["burnout"] = burnout.to_dict()

    await db.commit()

    return {
        "developer_id": developer_id,
        "analysis_complete": True,
        "results": results,
    }


# =============================================================================
# Team Intelligence Endpoints (requires workspace context)
# =============================================================================


@router.get("/team/{workspace_id}/burnout", response_model=TeamBurnoutResponse)
async def get_team_burnout_overview(
    workspace_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    developer_id: Annotated[str, Depends(get_current_developer_id)],
):
    """Get burnout risk overview for a team/workspace.

    Requires the current developer to have access to the workspace.
    """
    from aexy.services.burnout_detector import get_team_burnout_overview

    # TODO: Add workspace access check
    # For now, get all developers in the workspace
    from sqlalchemy import select
    from aexy.models.workspace import WorkspaceMember

    member_stmt = (
        select(WorkspaceMember.developer_id)
        .where(WorkspaceMember.workspace_id == workspace_id)
    )
    result = await db.execute(member_stmt)
    developer_ids = [row[0] for row in result.all()]

    if not developer_ids:
        raise HTTPException(status_code=404, detail="Workspace not found or empty")

    overview = await get_team_burnout_overview(db, developer_ids)

    return TeamBurnoutResponse(**overview)


@router.get("/team/{workspace_id}/expertise/{skill_name}")
async def compare_team_expertise(
    workspace_id: str,
    skill_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    developer_id: Annotated[str, Depends(get_current_developer_id)],
):
    """Compare expertise in a skill across team members."""
    from aexy.services.expertise_confidence import compare_developer_expertise

    # Get team members
    from sqlalchemy import select
    from aexy.models.workspace import WorkspaceMember

    member_stmt = (
        select(WorkspaceMember.developer_id)
        .where(WorkspaceMember.workspace_id == workspace_id)
    )
    result = await db.execute(member_stmt)
    developer_ids = [row[0] for row in result.all()]

    if not developer_ids:
        raise HTTPException(status_code=404, detail="Workspace not found or empty")

    comparisons = await compare_developer_expertise(db, developer_ids, skill_name)

    return {
        "skill": skill_name,
        "developers": comparisons,
    }


# =============================================================================
# Collaboration Network Endpoints
# =============================================================================


@router.get("/collaborators", response_model=CollaboratorResponse)
async def get_my_collaborators(
    db: Annotated[AsyncSession, Depends(get_db)],
    developer_id: Annotated[str, Depends(get_current_developer_id)],
    days: int = Query(default=180, ge=30, le=365),
    limit: int = Query(default=10, ge=1, le=50),
):
    """Get collaboration profile for the current developer.

    Returns:
    - Top collaborators by interaction strength
    - Collaboration diversity score
    - Average collaboration strength
    """
    from aexy.services.collaboration_network import CollaborationNetworkAnalyzer

    analyzer = CollaborationNetworkAnalyzer(db)
    result = await analyzer.get_developer_collaborators(
        developer_id=developer_id,
        days=days,
        limit=limit,
    )

    return CollaboratorResponse(
        developer_id=result.developer_id,
        total_collaborators=result.total_collaborators,
        top_collaborators=result.top_collaborators,
        collaboration_diversity=result.collaboration_diversity,
        is_knowledge_silo=result.is_knowledge_silo,
        silo_indicators=result.silo_indicators,
    )


@router.get("/team/{workspace_id}/collaboration", response_model=TeamCohesionResponse)
async def get_team_collaboration(
    workspace_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    developer_id: Annotated[str, Depends(get_current_developer_id)],
    days: int = Query(default=180, ge=30, le=365),
):
    """Get collaboration network analysis for a team/workspace.

    Returns:
    - Graph density and cohesion
    - Isolated developers who need more collaboration
    - Top connectors in the team
    """
    from aexy.services.collaboration_network import CollaborationNetworkAnalyzer
    from sqlalchemy import select
    from aexy.models.workspace import WorkspaceMember

    # Get team members
    member_stmt = (
        select(WorkspaceMember.developer_id)
        .where(WorkspaceMember.workspace_id == workspace_id)
    )
    result = await db.execute(member_stmt)
    developer_ids = [row[0] for row in result.all()]

    if not developer_ids:
        raise HTTPException(status_code=404, detail="Workspace not found or empty")

    analyzer = CollaborationNetworkAnalyzer(db)
    cohesion = await analyzer.analyze_team_cohesion(developer_ids, days)

    return TeamCohesionResponse(
        team_size=cohesion.team_size,
        total_edges=cohesion.total_edges,
        density=cohesion.density,
        avg_collaborations_per_developer=cohesion.avg_collaborations_per_developer,
        cohesion_score=cohesion.cohesion_score,
        knowledge_silos=cohesion.knowledge_silos,
        central_connectors=cohesion.central_connectors,
        isolated_developers=cohesion.isolated_developers,
    )


@router.get("/team/{workspace_id}/collaboration/graph")
async def get_collaboration_graph(
    workspace_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    developer_id: Annotated[str, Depends(get_current_developer_id)],
    days: int = Query(default=180, ge=30, le=365),
):
    """Get full collaboration graph for visualization.

    Returns edges with:
    - Source and target developer IDs
    - Collaboration strength and frequency
    - Last interaction timestamp
    """
    from aexy.services.collaboration_network import CollaborationNetworkAnalyzer
    from sqlalchemy import select
    from aexy.models.workspace import WorkspaceMember

    # Get team members
    member_stmt = (
        select(WorkspaceMember.developer_id)
        .where(WorkspaceMember.workspace_id == workspace_id)
    )
    result = await db.execute(member_stmt)
    developer_ids = [row[0] for row in result.all()]

    if not developer_ids:
        raise HTTPException(status_code=404, detail="Workspace not found or empty")

    analyzer = CollaborationNetworkAnalyzer(db)
    edges = await analyzer.build_collaboration_graph(developer_ids, days)

    return {
        "workspace_id": workspace_id,
        "developer_count": len(developer_ids),
        "edge_count": len(edges),
        "edges": [e.to_dict() for e in edges],
    }


# =============================================================================
# Project Complexity Endpoints
# =============================================================================


@router.get("/complexity", response_model=ComplexityProfileResponse)
async def get_my_complexity_profile(
    db: Annotated[AsyncSession, Depends(get_db)],
    developer_id: Annotated[str, Depends(get_current_developer_id)],
    days: int = Query(default=180, ge=30, le=365),
):
    """Get PR complexity profile for the current developer.

    Returns:
    - Complexity distribution across PRs
    - Primary change categories
    - Common components and layers touched
    - Cross-cutting and infrastructure ratios
    """
    from aexy.services.complexity_classifier import ComplexityClassifier

    classifier = ComplexityClassifier(db)
    profile = await classifier.get_developer_complexity_profile(
        developer_id=developer_id,
        days=days,
    )

    return ComplexityProfileResponse(**profile.to_dict())


@router.post("/complexity/update", response_model=ComplexityProfileResponse)
async def update_complexity_profile(
    db: Annotated[AsyncSession, Depends(get_db)],
    developer_id: Annotated[str, Depends(get_current_developer_id)],
    days: int = Query(default=180, ge=30, le=365),
):
    """Update and store complexity profile for the current developer."""
    from aexy.services.complexity_classifier import ComplexityClassifier

    classifier = ComplexityClassifier(db)
    profile = await classifier.update_developer_complexity_profile(
        developer_id=developer_id,
        days=days,
    )

    await db.commit()

    return ComplexityProfileResponse(**profile.to_dict())


@router.post("/complexity/analyze")
async def analyze_prs_complexity(
    db: Annotated[AsyncSession, Depends(get_db)],
    developer_id: Annotated[str, Depends(get_current_developer_id)],
    limit: int = Query(default=50, ge=1, le=200),
):
    """Analyze recent PRs for complexity classification.

    Returns aggregated complexity metrics and distribution.
    """
    from aexy.services.complexity_classifier import ComplexityClassifier

    classifier = ComplexityClassifier(db)
    result = await classifier.analyze_prs_batch(
        developer_id=developer_id,
        limit=limit,
    )

    await db.commit()

    return result


@router.get("/team/{workspace_id}/complexity", response_model=TeamComplexityResponse)
async def get_team_complexity(
    workspace_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    developer_id: Annotated[str, Depends(get_current_developer_id)],
    days: int = Query(default=90, ge=30, le=365),
):
    """Get complexity summary for a team/workspace.

    Returns:
    - Team-wide complexity distribution
    - Average complexity scores
    - Critical change handlers
    """
    from aexy.services.complexity_classifier import get_complexity_summary
    from sqlalchemy import select
    from aexy.models.workspace import WorkspaceMember

    # Get team members
    member_stmt = (
        select(WorkspaceMember.developer_id)
        .where(WorkspaceMember.workspace_id == workspace_id)
    )
    result = await db.execute(member_stmt)
    developer_ids = [row[0] for row in result.all()]

    if not developer_ids:
        raise HTTPException(status_code=404, detail="Workspace not found or empty")

    summary = await get_complexity_summary(db, developer_ids, days)

    return TeamComplexityResponse(**summary)


# =============================================================================
# Technology Evolution Endpoints
# =============================================================================


@router.get("/technology", response_model=TechnologyProfileResponse)
async def get_my_technology_profile(
    db: Annotated[AsyncSession, Depends(get_db)],
    developer_id: Annotated[str, Depends(get_current_developer_id)],
    days: int = Query(default=365, ge=30, le=730),
):
    """Get technology profile for the current developer.

    Returns:
    - Technologies and versions detected
    - Current vs outdated vs deprecated counts
    - Adoption score (how up-to-date they stay)
    - Upgrade suggestions for outdated technologies
    """
    from aexy.services.technology_tracker import TechnologyTracker

    tracker = TechnologyTracker(db)
    profile = await tracker.get_developer_technology_profile(
        developer_id=developer_id,
        days=days,
    )

    return TechnologyProfileResponse(**profile.to_dict())


@router.post("/technology/update", response_model=TechnologyProfileResponse)
async def update_technology_profile(
    db: Annotated[AsyncSession, Depends(get_db)],
    developer_id: Annotated[str, Depends(get_current_developer_id)],
    days: int = Query(default=365, ge=30, le=730),
):
    """Update and store technology profile for the current developer."""
    from aexy.services.technology_tracker import TechnologyTracker

    tracker = TechnologyTracker(db)
    profile = await tracker.update_developer_technology_profile(
        developer_id=developer_id,
        days=days,
    )

    await db.commit()

    return TechnologyProfileResponse(**profile.to_dict())


@router.get("/team/{workspace_id}/technology", response_model=TeamTechnologyResponse)
async def get_team_technology(
    workspace_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    developer_id: Annotated[str, Depends(get_current_developer_id)],
    days: int = Query(default=180, ge=30, le=365),
):
    """Get technology overview for a team/workspace.

    Returns:
    - All technologies in use across the team
    - Version distribution per technology
    - Team health score
    - Critical upgrades needed
    """
    from aexy.services.technology_tracker import get_team_technology_overview
    from sqlalchemy import select
    from aexy.models.workspace import WorkspaceMember

    # Get team members
    member_stmt = (
        select(WorkspaceMember.developer_id)
        .where(WorkspaceMember.workspace_id == workspace_id)
    )
    result = await db.execute(member_stmt)
    developer_ids = [row[0] for row in result.all()]

    if not developer_ids:
        raise HTTPException(status_code=404, detail="Workspace not found or empty")

    overview = await get_team_technology_overview(db, developer_ids, days)

    return TeamTechnologyResponse(**overview)
