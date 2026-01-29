"""Project models - sits between Workspace and Teams in the hierarchy."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4
import re
import secrets
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aexy.core.database import Base

if TYPE_CHECKING:
    from aexy.models.developer import Developer
    from aexy.models.workspace import Workspace
    from aexy.models.team import Team
    from aexy.models.role import CustomRole


def generate_slug(name: str) -> str:
    """Generate a URL-safe slug from a name."""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[-\s]+", "-", slug)
    return slug[:100]

def generate_public_slug(name: str) -> str:
    """
    Generate a globally-unique public slug.
    Example: aexy-roadmap-k3f9x2
    """
    base = generate_slug(name)
    suffix = secrets.token_urlsafe(4).lower().replace("_", "").replace("-", "")
    return f"{base}-{suffix}"



class Project(Base):
    """
    Project model - groups teams and work within a workspace.

    Hierarchy: Workspace > Projects > Teams
    Projects allow for project-specific role assignments that can
    override workspace-level roles.
    """

    __tablename__ = "projects"

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

    # Project metadata
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_public: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )

    public_slug: Mapped[str | None] = mapped_column(
        String(120),
        unique=True,
        nullable=True,
        index=True,
    )


    # Visual customization
    color: Mapped[str] = mapped_column(String(50), default="#3b82f6", nullable=False)
    icon: Mapped[str] = mapped_column(String(50), default="FolderGit2", nullable=False)

    # Project settings (JSONB for flexibility)
    # Can include: default_role_id, feature_flags, notification_settings, etc.
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Status: "active" | "archived" | "on_hold"
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active"
    )

    # Active status (soft delete)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

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
    members: Mapped[list["ProjectMember"]] = relationship(
        "ProjectMember",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    project_teams: Mapped[list["ProjectTeam"]] = relationship(
        "ProjectTeam",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_workspace_project_slug"),
    )

    def make_public(self):
        """Mark project as public and assign public_slug if needed."""
        if not self.public_slug:
            self.public_slug = generate_public_slug(self.name)
        self.is_public = True

    def make_private(self):
        """Mark project as private (keeps public_slug for reuse)."""
        self.is_public = False

    @property
    def member_count(self) -> int:
        """Get the number of active members in this project."""
        return len([m for m in self.members if m.status == "active"])

    @property
    def team_count(self) -> int:
        """Get the number of teams associated with this project."""
        return len(self.project_teams)

    def __repr__(self) -> str:
        return f"<Project {self.name} ({self.slug}) in workspace {self.workspace_id}>"


class ProjectMember(Base):
    """
    Project membership with project-specific role assignment.

    When a user is added to a project, they can be assigned a role that
    overrides their workspace-level role for that specific project.
    """

    __tablename__ = "project_members"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    project_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    developer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("developers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Role reference (nullable - if null, falls back to workspace-level role)
    role_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("custom_roles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Permission overrides at project level
    # Positive: {"can_manage_crm": true} - ADD permission
    # Negative: {"can_manage_crm": false} - RESTRICT permission
    # These are applied AFTER role permissions are resolved
    permission_overrides: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Status: "active" | "pending" | "removed"
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active"
    )

    # Invitation tracking
    invited_by_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("developers.id", ondelete="SET NULL"),
        nullable=True,
    )
    invited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    joined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
    project: Mapped["Project"] = relationship(
        "Project", back_populates="members", lazy="selectin"
    )
    developer: Mapped["Developer"] = relationship(
        "Developer", foreign_keys=[developer_id], lazy="selectin"
    )
    role: Mapped["CustomRole | None"] = relationship("CustomRole", lazy="selectin")
    invited_by: Mapped["Developer | None"] = relationship(
        "Developer", foreign_keys=[invited_by_id], lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint("project_id", "developer_id", name="uq_project_member"),
    )

    def __repr__(self) -> str:
        return f"<ProjectMember developer={self.developer_id} project={self.project_id}>"


class ProjectTeam(Base):
    """
    Association between projects and teams (many-to-many).

    Teams can belong to multiple projects, and projects can have multiple teams.
    """

    __tablename__ = "project_teams"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    project_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    team_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("teams.id", ondelete="CASCADE"),
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
    project: Mapped["Project"] = relationship(
        "Project", back_populates="project_teams", lazy="selectin"
    )
    team: Mapped["Team"] = relationship("Team", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("project_id", "team_id", name="uq_project_team"),
    )

    def __repr__(self) -> str:
        return f"<ProjectTeam project={self.project_id} team={self.team_id}>"
