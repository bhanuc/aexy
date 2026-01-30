"""Roadmap voting models for public feature requests and voting."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aexy.core.database import Base

if TYPE_CHECKING:
    from aexy.models.developer import Developer
    from aexy.models.workspace import Workspace
    from aexy.models.project import Project


class RoadmapRequest(Base):
    """Feature request for public roadmap voting.

    Users can submit feature requests that others can vote on
    and comment to help prioritize development.
    """

    __tablename__ = "roadmap_requests"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    workspace_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Request info
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Category/type of request
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, default="feature"
    )  # "feature" | "improvement" | "integration" | "bug_fix" | "other"

    # Status managed by project owners
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="under_review"
    )  # "under_review" | "planned" | "in_progress" | "completed" | "declined"

    # Vote count (denormalized for performance)
    vote_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Submitter - required (user must be logged in)
    submitted_by_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("developers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Admin response/notes
    admin_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    responded_by_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("developers.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace", lazy="selectin")
    project: Mapped["Project"] = relationship("Project", lazy="selectin")
    submitted_by: Mapped["Developer"] = relationship(
        "Developer", foreign_keys=[submitted_by_id], lazy="selectin"
    )
    responded_by: Mapped["Developer | None"] = relationship(
        "Developer", foreign_keys=[responded_by_id], lazy="selectin"
    )
    votes: Mapped[list["RoadmapVote"]] = relationship(
        "RoadmapVote", back_populates="request", lazy="selectin", cascade="all, delete-orphan"
    )
    comments: Mapped[list["RoadmapComment"]] = relationship(
        "RoadmapComment", back_populates="request", lazy="selectin", cascade="all, delete-orphan"
    )


class RoadmapVote(Base):
    """Vote on a roadmap request."""

    __tablename__ = "roadmap_votes"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    request_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("roadmap_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Voter - required (user must be logged in)
    voter_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("developers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    request: Mapped["RoadmapRequest"] = relationship(
        "RoadmapRequest", back_populates="votes"
    )
    voter: Mapped["Developer"] = relationship("Developer", lazy="selectin")

    __table_args__ = (
        # One vote per user per request
        UniqueConstraint("request_id", "voter_id", name="uq_roadmap_vote_user"),
    )


class RoadmapComment(Base):
    """Comment on a roadmap request."""

    __tablename__ = "roadmap_comments"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    request_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("roadmap_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Comment content
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Author - required (user must be logged in)
    author_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("developers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Admin/official comment flag
    is_admin_response: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    request: Mapped["RoadmapRequest"] = relationship(
        "RoadmapRequest", back_populates="comments"
    )
    author: Mapped["Developer"] = relationship("Developer", lazy="selectin")
