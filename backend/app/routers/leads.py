import csv
import io
import math
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from sse_starlette.sse import EventSourceResponse
import json
import asyncio
import redis.asyncio as aioredis

from app.database import get_db
from app.models.lead import Lead, LeadStatus, LeadSource
from app.models.enrichment import Enrichment
from app.models.draft import Draft
from app.models.crm_sync import CRMSync
from app.models.score_history import ScoreHistory
from app.config import settings

router = APIRouter()


def _get_redis():
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


def _extract_domain(email_or_url: str) -> Optional[str]:
    if not email_or_url:
        return None
    if "@" in email_or_url:
        return email_or_url.split("@")[-1].lower().strip()
    for prefix in ["https://", "http://", "www."]:
        email_or_url = email_or_url.replace(prefix, "")
    return email_or_url.split("/")[0].lower().strip() or None


@router.post("/upload")
async def upload_csv(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """Accept CSV, validate, create Lead rows, enqueue enrichment."""
    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "File must be a CSV.")
    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
    except Exception as e:
        raise HTTPException(400, f"Could not parse CSV: {e}")

    if not rows:
        raise HTTPException(400, "CSV is empty.")

    headers = {h.lower().strip() for h in rows[0].keys()}
    has_name_company = "name" in headers and "company" in headers
    has_email = "email" in headers
    has_domain = "domain" in headers
    if not (has_name_company or has_email or has_domain):
        raise HTTPException(
            400,
            "CSV must have 'name'+'company', or 'email', or 'domain' columns.",
        )

    created, skipped = 0, 0
    lead_ids = []
    for row in rows:
        norm = {k.lower().strip(): v.strip() for k, v in row.items()}
        name = norm.get("name") or norm.get("full_name") or None
        company = norm.get("company") or norm.get("company_name") or None
        email = norm.get("email") or None
        domain = norm.get("domain") or None
        linkedin = norm.get("linkedin_url") or norm.get("linkedin") or None

        if not domain and email:
            domain = _extract_domain(email)
        if not domain and linkedin:
            pass  # will be enriched from linkedin

        if not name and not company and not domain and not email:
            skipped += 1
            continue

        lead = Lead(
            name=name,
            email=email,
            company=company,
            domain=domain,
            linkedin_url=linkedin,
            raw_csv_row=norm,
            status=LeadStatus.pending,
            source=LeadSource.csv,
        )
        db.add(lead)
        await db.flush()
        lead_ids.append(str(lead.id))
        created += 1

    await db.commit()

    # Enqueue enrichment for all leads (fire-and-forget, do not wait for result)
    from app.pipeline.orchestrator import enrich_lead_task
    for lid in lead_ids:
        enrich_lead_task.apply_async(args=[lid], ignore_result=True)

    return {"queued": created, "skipped": skipped, "lead_ids": lead_ids}


@router.get("")
async def list_leads(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = None,
    min_score: Optional[float] = None,
    industry: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = Query("created_at", regex="^(created_at|total_score|company|name)$"),
    db: AsyncSession = Depends(get_db),
):
    """Paginated lead list with filters."""
    query = select(Lead)

    if status:
        query = query.where(Lead.status == status)
    if min_score is not None:
        query = query.where(Lead.total_score >= min_score)
    if search:
        q = f"%{search}%"
        query = query.where(or_(Lead.name.ilike(q), Lead.company.ilike(q), Lead.domain.ilike(q)))

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    sort_col = {
        "created_at": Lead.created_at.desc(),
        "total_score": Lead.total_score.desc(),
        "company": Lead.company.asc(),
        "name": Lead.name.asc(),
    }[sort_by]

    query = query.order_by(sort_col).offset((page - 1) * limit).limit(limit)
    leads = (await db.execute(query)).scalars().all()

    # Get enrichment/crm data for each lead efficiently
    lead_ids = [l.id for l in leads]
    enrichments = {}
    crm_syncs = {}
    if lead_ids:
        enr_rows = (await db.execute(
            select(Enrichment).where(Enrichment.lead_id.in_(lead_ids))
        )).scalars().all()
        for e in enr_rows:
            enrichments[e.lead_id] = e

        crm_rows = (await db.execute(
            select(CRMSync).where(CRMSync.lead_id.in_(lead_ids))
        )).scalars().all()
        for c in crm_rows:
            crm_syncs[c.lead_id] = c

    items = []
    for lead in leads:
        enr = enrichments.get(lead.id)
        crm = crm_syncs.get(lead.id)
        top_signal = None
        lead_industry = None
        if enr:
            signals = enr.buying_signals or []
            if signals:
                top_signal = signals[0].get("signal")
            lead_industry = enr.industry

        if industry and lead_industry and industry.lower() not in lead_industry.lower():
            continue

        items.append({
            "id": str(lead.id),
            "name": lead.name,
            "email": lead.email,
            "company": lead.company,
            "domain": lead.domain,
            "status": lead.status,
            "icp_score": lead.icp_score,
            "total_score": lead.total_score,
            "top_buying_signal": top_signal,
            "industry": lead_industry,
            "crm_sync_status": crm.status if crm else None,
            "source": lead.source,
            "created_at": lead.created_at.isoformat(),
            "updated_at": lead.updated_at.isoformat(),
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": math.ceil(total / limit) if total else 1,
    }


@router.get("/sse/pipeline")
async def pipeline_sse(db: AsyncSession = Depends(get_db)):
    """Stream all active pipeline events via SSE."""
    redis_client = _get_redis()

    async def event_generator():
        pubsub = redis_client.pubsub()
        await pubsub.subscribe("pipeline:events")
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield {"data": message["data"]}
                await asyncio.sleep(0.1)
        finally:
            await pubsub.unsubscribe("pipeline:events")
            await redis_client.aclose()

    return EventSourceResponse(event_generator())


@router.get("/sse/{lead_id}")
async def lead_sse(lead_id: UUID):
    """Stream enrichment status for a single lead via SSE."""
    redis_client = _get_redis()
    channel = f"lead:{lead_id}:events"

    async def event_generator():
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield {"data": message["data"]}
                    data = json.loads(message["data"])
                    if data.get("stage") in ("complete", "failed"):
                        break
                await asyncio.sleep(0.1)
        finally:
            await pubsub.unsubscribe(channel)
            await redis_client.aclose()

    return EventSourceResponse(event_generator())


@router.post("/extension")
async def create_extension_lead(payload: dict, db: AsyncSession = Depends(get_db)):
    """Accept lead from Chrome extension."""
    domain = None
    if payload.get("url"):
        domain = _extract_domain(payload["url"])
    if not domain and payload.get("linkedin_url"):
        pass

    lead = Lead(
        name=payload.get("name"),
        email=payload.get("email"),
        company=payload.get("company"),
        domain=domain,
        linkedin_url=payload.get("linkedin_url"),
        raw_csv_row=payload,
        status=LeadStatus.pending,
        source=LeadSource.extension,
    )
    db.add(lead)
    await db.commit()
    await db.refresh(lead)

    from app.pipeline.orchestrator import enrich_lead_task
    enrich_lead_task.apply_async(args=[str(lead.id)], ignore_result=True)

    return {"id": str(lead.id), "status": lead.status}


@router.post("/domain")
async def domain_enrichment(payload: dict, db: AsyncSession = Depends(get_db)):
    """Discover leads from a company domain (bonus feature)."""
    domain = payload.get("domain", "").strip().lower()
    if not domain:
        raise HTTPException(400, "domain is required")

    from app.pipeline.domain_enricher import discover_leads_from_domain
    discovered = await discover_leads_from_domain(domain)

    created_ids = []
    for person in discovered:
        lead = Lead(
            name=person.get("name"),
            company=person.get("company"),
            domain=domain,
            linkedin_url=person.get("linkedin_url_guess"),
            raw_csv_row=person,
            status=LeadStatus.pending,
            source=LeadSource.domain,
        )
        db.add(lead)
        await db.flush()
        created_ids.append(str(lead.id))

    await db.commit()

    from app.pipeline.orchestrator import enrich_lead_task
    for lid in created_ids:
        enrich_lead_task.apply_async(args=[lid], ignore_result=True)

    return {"discovered": len(created_ids), "lead_ids": created_ids, "domain": domain}


@router.get("/{lead_id}")
async def get_lead(lead_id: UUID, db: AsyncSession = Depends(get_db)):
    """Full lead detail with enrichment, drafts, CRM sync, score history."""
    lead = (await db.execute(select(Lead).where(Lead.id == lead_id))).scalar_one_or_none()
    if not lead:
        raise HTTPException(404, "Lead not found")

    enr = (await db.execute(
        select(Enrichment).where(Enrichment.lead_id == lead_id)
    )).scalar_one_or_none()

    drafts = (await db.execute(
        select(Draft).where(Draft.lead_id == lead_id)
    )).scalars().all()

    crm = (await db.execute(
        select(CRMSync).where(CRMSync.lead_id == lead_id)
    )).scalar_one_or_none()

    history = (await db.execute(
        select(ScoreHistory).where(ScoreHistory.lead_id == lead_id).order_by(ScoreHistory.recorded_at)
    )).scalars().all()

    return {
        "id": str(lead.id),
        "name": lead.name,
        "email": lead.email,
        "company": lead.company,
        "domain": lead.domain,
        "linkedin_url": lead.linkedin_url,
        "status": lead.status,
        "icp_score": lead.icp_score,
        "total_score": lead.total_score,
        "icp_score_breakdown": lead.icp_score_breakdown,
        "source": lead.source,
        "created_at": lead.created_at.isoformat(),
        "updated_at": lead.updated_at.isoformat(),
        "enrichment": {
            "company_size": enr.company_size if enr else None,
            "company_size_confidence": enr.company_size_confidence if enr else None,
            "tech_stack": enr.tech_stack if enr else None,
            "tech_stack_confidence": enr.tech_stack_confidence if enr else None,
            "funding_status": enr.funding_status if enr else None,
            "funding_confidence": enr.funding_confidence if enr else None,
            "industry": enr.industry if enr else None,
            "sub_industry": enr.sub_industry if enr else None,
            "contact_role": enr.contact_role if enr else None,
            "contact_seniority": enr.contact_seniority if enr else None,
            "recent_news": enr.recent_news if enr else [],
            "buying_signals": enr.buying_signals if enr else [],
            "enriched_sources": enr.enriched_sources if enr else {},
            "email_candidates": enr.email_candidates if enr else [],
        } if enr else None,
        "drafts": [
            {
                "id": str(d.id), "tone": d.tone, "subject": d.subject,
                "body": d.body, "call_to_action": d.call_to_action,
                "generated_at": d.generated_at.isoformat(),
            }
            for d in drafts
        ],
        "crm_sync": {
            "status": crm.status if crm else None,
            "crm_record_id": crm.crm_record_id if crm else None,
            "synced_at": crm.synced_at.isoformat() if crm and crm.synced_at else None,
            "error_message": crm.error_message if crm else None,
        } if crm else None,
        "score_history": [
            {
                "id": str(h.id), "icp_score": h.icp_score,
                "total_score": h.total_score,
                "buying_signal_count": h.buying_signal_count,
                "recorded_at": h.recorded_at.isoformat(),
            }
            for h in history
        ],
    }


@router.delete("/{lead_id}")
async def delete_lead(lead_id: UUID, db: AsyncSession = Depends(get_db)):
    lead = (await db.execute(select(Lead).where(Lead.id == lead_id))).scalar_one_or_none()
    if not lead:
        raise HTTPException(404, "Lead not found")
    await db.delete(lead)
    await db.commit()
    return {"deleted": str(lead_id)}
