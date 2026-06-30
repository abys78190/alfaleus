"""
Notion CRM sync client.
Syncs enriched leads to a Notion database with deduplication by domain.
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Dict

from app.config import settings

logger = logging.getLogger(__name__)


def _get_client():
    """Return Notion AsyncClient."""
    from notion_client import AsyncClient
    return AsyncClient(auth=settings.NOTION_API_KEY)


def _build_properties(lead_data: dict, enrichment: dict, drafts: list) -> dict:
    """Build Notion page properties from lead data."""
    props = {}

    # Title (Name)
    name = lead_data.get("name") or lead_data.get("company") or lead_data.get("domain") or "Unknown Lead"
    props["Name"] = {"title": [{"text": {"content": str(name)[:200]}}]}

    # Text fields
    if lead_data.get("company"):
        props["Company"] = {"rich_text": [{"text": {"content": str(lead_data["company"])[:200]}}]}
    if lead_data.get("domain"):
        props["Domain"] = {"rich_text": [{"text": {"content": str(lead_data["domain"])[:200]}}]}
    if lead_data.get("email"):
        props["Email"] = {"email": str(lead_data["email"])[:200]}

    # Scores
    if lead_data.get("icp_score") is not None:
        props["ICP Score"] = {"number": round(float(lead_data["icp_score"]), 1)}
    if lead_data.get("total_score") is not None:
        props["Total Score"] = {"number": round(float(lead_data["total_score"]), 1)}

    # Status
    status = lead_data.get("status", "enriched")
    props["Status"] = {"select": {"name": status.title()}}

    # Enrichment fields
    if enrichment:
        if enrichment.get("industry"):
            props["Industry"] = {"select": {"name": str(enrichment["industry"])[:100]}}
        if enrichment.get("funding_status"):
            props["Funding"] = {"rich_text": [{"text": {"content": str(enrichment["funding_status"])[:200]}}]}
        if enrichment.get("company_size"):
            props["Company Size"] = {"rich_text": [{"text": {"content": str(enrichment["company_size"])[:100]}}]}
        if enrichment.get("tech_stack"):
            tech_list = enrichment["tech_stack"][:10]
            props["Tech Stack"] = {"multi_select": [{"name": t[:100]} for t in tech_list]}

        # Top buying signal
        signals = enrichment.get("buying_signals") or []
        if signals:
            top_signal = signals[0].get("signal", "")[:200]
            props["Top Signal"] = {"rich_text": [{"text": {"content": top_signal}}]}

    # First outreach draft
    if drafts:
        first_draft = drafts[0]
        draft_text = f"Subject: {first_draft.get('subject', '')}\n\n{first_draft.get('body', '')}"
        props["Outreach Draft"] = {"rich_text": [{"text": {"content": draft_text[:2000]}}]}

    # Sync date
    props["Sync Date"] = {"date": {"start": datetime.now(timezone.utc).isoformat()}}

    # LinkedIn URL
    if lead_data.get("linkedin_url"):
        props["LinkedIn"] = {"url": str(lead_data["linkedin_url"])[:200]}

    return props


async def find_existing_record(domain: str) -> Optional[str]:
    """
    Query Notion DB to find existing record by domain.
    Returns page_id if found, None otherwise.
    """
    if not domain or not settings.NOTION_API_KEY or not settings.NOTION_DATABASE_ID:
        return None
    try:
        client = _get_client()
        result = await client.databases.query(
            database_id=settings.NOTION_DATABASE_ID,
            filter={
                "property": "Domain",
                "rich_text": {"equals": domain},
            },
        )
        pages = result.get("results", [])
        if pages:
            return pages[0]["id"]
        return None
    except Exception as e:
        logger.debug(f"Notion query error: {e}")
        return None


async def sync_lead_to_notion(
    lead_data: dict,
    enrichment: dict,
    drafts: list,
) -> Dict:
    """
    Sync a lead to Notion. Creates new page or updates existing (by domain).
    Returns {status, record_id, error}
    """
    if not settings.NOTION_API_KEY:
        return {"status": "failed", "record_id": None, "error": "NOTION_API_KEY not configured"}
    if not settings.NOTION_DATABASE_ID:
        return {"status": "failed", "record_id": None, "error": "NOTION_DATABASE_ID not configured"}

    domain = lead_data.get("domain") or lead_data.get("email", "").split("@")[-1]

    try:
        client = _get_client()
        properties = _build_properties(lead_data, enrichment, drafts)

        # Check for existing record
        existing_id = await find_existing_record(domain) if domain else None

        if existing_id:
            # Update existing page
            await client.pages.update(page_id=existing_id, properties=properties)
            return {"status": "updated", "record_id": existing_id, "error": None}
        else:
            # Create new page
            page = await client.pages.create(
                parent={"database_id": settings.NOTION_DATABASE_ID},
                properties=properties,
            )
            return {"status": "synced", "record_id": page["id"], "error": None}

    except Exception as e:
        logger.error(f"Notion sync failed: {e}")
        return {"status": "failed", "record_id": None, "error": str(e)[:500]}
