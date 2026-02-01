"""CRM tools for AI agents."""

from typing import Any, Type
from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool


class SearchContactsInput(BaseModel):
    """Input for searching contacts."""
    query: str = Field(description="Search query for contact name or email")
    object_type: str = Field(default="person", description="Object type to search: person, company, or deal")
    limit: int = Field(default=10, description="Maximum number of results to return")


class SearchContactsTool(BaseTool):
    """Search for contacts in the CRM."""

    name: str = "search_contacts"
    description: str = "Search for contacts (people, companies, or deals) in the CRM by name or email"
    args_schema: Type[BaseModel] = SearchContactsInput
    workspace_id: str = ""
    db: Any = None

    def _run(self, query: str, object_type: str = "person", limit: int = 10) -> str:
        # Synchronous fallback - not used in async context
        return f"Found contacts matching '{query}'"

    async def _arun(self, query: str, object_type: str = "person", limit: int = 10) -> str:
        """Search for contacts in the CRM.

        Searches records in the workspace, filtering by object type (slug) and query.
        Only returns data the user has access to (workspace-scoped).
        """
        from sqlalchemy import select, or_
        from aexy.models.crm import CRMRecord, CRMObject

        if not self.db or not self.workspace_id:
            return "Error: Database connection not available"

        try:
            # Find the object ID by slug (person, company, deal) or object_type for system objects
            obj_stmt = select(CRMObject).where(
                CRMObject.workspace_id == self.workspace_id,
                or_(
                    CRMObject.slug == object_type,
                    CRMObject.object_type == object_type,
                ),
            )
            result = await self.db.execute(obj_stmt)
            obj = result.scalar_one_or_none()

            if not obj:
                # Try to find any object if specific type not found
                obj_stmt = select(CRMObject).where(
                    CRMObject.workspace_id == self.workspace_id,
                    CRMObject.is_active == True,
                ).limit(1)
                result = await self.db.execute(obj_stmt)
                obj = result.scalar_one_or_none()

            if not obj:
                return f"No CRM objects found in workspace"

            # Search records - scoped to workspace for security
            stmt = (
                select(CRMRecord)
                .where(
                    CRMRecord.workspace_id == self.workspace_id,
                    CRMRecord.object_id == obj.id,
                    CRMRecord.is_archived == False,
                )
                .limit(limit * 2)  # Fetch more to filter
            )
            result = await self.db.execute(stmt)
            records = result.scalars().all()

            if not records:
                return f"No {obj.name} records found in the CRM"

            # Filter by query in values (case-insensitive)
            # Values are stored as JSONB: {attribute_slug: value}
            matching = []
            query_lower = query.lower().strip()

            for record in records:
                # Combine display_name and all values from JSONB for search
                values = record.values or {}
                searchable = f"{record.display_name or ''} {' '.join(str(v) for v in values.values())}".lower()

                # If query is empty, return all records
                if not query_lower or query_lower in searchable:
                    matching.append({
                        "id": record.id,
                        "display_name": record.display_name,
                        "values": values,
                    })

                    if len(matching) >= limit:
                        break

            if not matching:
                return f"No {obj.name} records found matching '{query}'"

            # Format output
            output_lines = [f"Found {len(matching)} {obj.name} record(s):"]
            for r in matching:
                name = r.get("display_name") or r.get("id", "Unknown")
                values = r.get("values", {})
                # Get readable values
                details = [f"{k}: {v}" for k, v in values.items() if v]
                if details:
                    output_lines.append(f"- {name} ({', '.join(details[:5])})")
                else:
                    output_lines.append(f"- {name}")

            return "\n".join(output_lines)
        except Exception as e:
            return f"Error searching contacts: {str(e)}"


class GetRecordInput(BaseModel):
    """Input for getting a record."""
    record_id: str = Field(description="The ID of the record to retrieve")


class GetRecordTool(BaseTool):
    """Get a specific record from the CRM."""

    name: str = "get_record"
    description: str = "Get a specific record from the CRM by its ID"
    args_schema: Type[BaseModel] = GetRecordInput
    db: Any = None

    def _run(self, record_id: str) -> str:
        return f"Retrieved record {record_id}"

    async def _arun(self, record_id: str) -> str:
        """Get a record by ID."""
        from sqlalchemy import select
        from aexy.models.crm import CRMRecord

        if not self.db:
            return "Error: Database connection not available"

        try:
            stmt = select(CRMRecord).where(CRMRecord.id == record_id)
            result = await self.db.execute(stmt)
            record = result.scalar_one_or_none()

            if not record:
                return f"Record {record_id} not found"

            return f"""Record: {record.display_name or record.id}
Values: {record.values}
Created: {record.created_at}
Owner: {record.owner_id or 'Unassigned'}"""
        except Exception as e:
            return f"Error getting record: {str(e)}"


class UpdateRecordInput(BaseModel):
    """Input for updating a record."""
    record_id: str = Field(description="The ID of the record to update")
    field_updates: dict = Field(description="Dictionary of field names and their new values")


class UpdateRecordTool(BaseTool):
    """Update a record in the CRM."""

    name: str = "update_record"
    description: str = "Update fields on a CRM record"
    args_schema: Type[BaseModel] = UpdateRecordInput
    db: Any = None

    def _run(self, record_id: str, field_updates: dict) -> str:
        return f"Updated record {record_id}"

    async def _arun(self, record_id: str, field_updates: dict) -> str:
        """Update a record."""
        from sqlalchemy import select
        from aexy.models.crm import CRMRecord

        if not self.db:
            return "Error: Database connection not available"

        try:
            stmt = select(CRMRecord).where(CRMRecord.id == record_id)
            result = await self.db.execute(stmt)
            record = result.scalar_one_or_none()

            if not record:
                return f"Record {record_id} not found"

            # Update values
            new_values = {**record.values, **field_updates}
            record.values = new_values
            await self.db.flush()

            return f"Successfully updated record {record_id} with: {field_updates}"
        except Exception as e:
            return f"Error updating record: {str(e)}"


class CreateRecordInput(BaseModel):
    """Input for creating a record."""
    object_type: str = Field(description="The type of object to create: person, company, or deal")
    values: dict = Field(description="The field values for the new record")


class CreateRecordTool(BaseTool):
    """Create a new record in the CRM."""

    name: str = "create_record"
    description: str = "Create a new record in the CRM"
    args_schema: Type[BaseModel] = CreateRecordInput
    workspace_id: str = ""
    db: Any = None

    def _run(self, object_type: str, values: dict) -> str:
        return f"Created {object_type} record"

    async def _arun(self, object_type: str, values: dict) -> str:
        """Create a new record."""
        from uuid import uuid4
        from sqlalchemy import select
        from aexy.models.crm import CRMRecord, CRMObject

        if not self.db or not self.workspace_id:
            return "Error: Database connection not available"

        try:
            # Find the object ID
            obj_stmt = select(CRMObject).where(
                CRMObject.workspace_id == self.workspace_id,
                CRMObject.object_type == object_type,
            )
            result = await self.db.execute(obj_stmt)
            obj = result.scalar_one_or_none()

            if not obj:
                return f"No {object_type} object found in workspace"

            # Create record
            record = CRMRecord(
                id=str(uuid4()),
                workspace_id=self.workspace_id,
                object_id=obj.id,
                values=values,
            )
            self.db.add(record)
            await self.db.flush()

            return f"Successfully created {object_type} record with ID: {record.id}"
        except Exception as e:
            return f"Error creating record: {str(e)}"


class GetActivitiesInput(BaseModel):
    """Input for getting activities."""
    record_id: str = Field(description="The ID of the record to get activities for")
    limit: int = Field(default=20, description="Maximum number of activities to return")


class GetActivitiesTool(BaseTool):
    """Get activities for a CRM record."""

    name: str = "get_activities"
    description: str = "Get recent activities (emails, calls, meetings, etc.) for a CRM record"
    args_schema: Type[BaseModel] = GetActivitiesInput
    db: Any = None

    def _run(self, record_id: str, limit: int = 20) -> str:
        return f"Retrieved activities for {record_id}"

    async def _arun(self, record_id: str, limit: int = 20) -> str:
        """Get activities for a record."""
        from sqlalchemy import select
        from aexy.models.crm import CRMActivity

        if not self.db:
            return "Error: Database connection not available"

        try:
            stmt = (
                select(CRMActivity)
                .where(CRMActivity.record_id == record_id)
                .order_by(CRMActivity.occurred_at.desc())
                .limit(limit)
            )
            result = await self.db.execute(stmt)
            activities = result.scalars().all()

            if not activities:
                return f"No activities found for record {record_id}"

            activity_list = []
            for a in activities:
                activity_list.append(
                    f"- {a.activity_type}: {a.title or 'No title'} ({a.occurred_at.strftime('%Y-%m-%d %H:%M')})"
                )

            return f"Activities for record {record_id}:\n" + "\n".join(activity_list)
        except Exception as e:
            return f"Error getting activities: {str(e)}"
