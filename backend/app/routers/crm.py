from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.lead import Lead, LeadStatus
from app.models.crm_sync import CRMSync

router = APIRouter()


@router.post("/sync/{lead_id}")
async def sync_lead(lead_id: UUID, db: AsyncSession = Depends(get_db)):
    lead = (await db.execute(select(Lead).where(Lead.id == lead_id))).scalar_one_or_none()
    if not lead:
        raise HTTPException(404, "Lead not found")
    if lead.status != LeadStatus.enriched:
        raise HTTPException(400, "Lead must be enriched before syncing to CRM.")

    from app.pipeline.orchestrator import sync_to_crm_task
    sync_to_crm_task.apply_async(args=[str(lead_id)], ignore_result=True)
    return {"queued": True, "lead_id": str(lead_id)}


@router.post("/sync/all")
async def sync_all(db: AsyncSession = Depends(get_db)):
    enriched = (await db.execute(
        select(Lead.id).where(Lead.status == LeadStatus.enriched)
    )).scalars().all()

    from app.pipeline.orchestrator import sync_to_crm_task
    for lid in enriched:
        sync_to_crm_task.apply_async(args=[str(lid)], ignore_result=True)

    return {"queued": len(enriched)}


@router.get("/status/{lead_id}")
async def get_sync_status(lead_id: UUID, db: AsyncSession = Depends(get_db)):
    crm = (await db.execute(
        select(CRMSync).where(CRMSync.lead_id == lead_id)
    )).scalar_one_or_none()
    if not crm:
        return {"status": "not_synced", "lead_id": str(lead_id)}
    return {
        "status": crm.status,
        "crm_record_id": crm.crm_record_id,
        "synced_at": crm.synced_at.isoformat() if crm.synced_at else None,
        "error_message": crm.error_message,
    }
