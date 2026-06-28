from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.lead import Lead, LeadStatus

router = APIRouter()


@router.get("/{lead_id}/status")
async def get_status(lead_id: UUID, db: AsyncSession = Depends(get_db)):
    lead = (await db.execute(select(Lead).where(Lead.id == lead_id))).scalar_one_or_none()
    if not lead:
        raise HTTPException(404, "Lead not found")
    return {
        "lead_id": str(lead_id),
        "enrichment_status": lead.status,
        "stage": None,  # Overridden by SSE in real-time; this is the DB snapshot
    }


@router.post("/{lead_id}/retry")
async def retry_enrichment(lead_id: UUID, db: AsyncSession = Depends(get_db)):
    lead = (await db.execute(select(Lead).where(Lead.id == lead_id))).scalar_one_or_none()
    if not lead:
        raise HTTPException(404, "Lead not found")

    lead.status = LeadStatus.pending
    await db.commit()

    from app.pipeline.orchestrator import enrich_lead_task
    enrich_lead_task.apply_async(args=[str(lead_id)], ignore_result=True)
    return {"queued": True, "lead_id": str(lead_id)}
