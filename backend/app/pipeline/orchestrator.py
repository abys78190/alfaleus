"""
Celery pipeline orchestrator.
Coordinates all enrichment steps per lead with SSE status broadcasting.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import redis

from app.config import settings

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine in a sync Celery task context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _publish_event(redis_client, lead_id: str, stage: str, status: str, extra: dict = None):
    """Publish SSE event to Redis pub/sub."""
    event = {
        "lead_id": lead_id,
        "stage": stage,
        "status": status,  # "in_progress" | "success" | "failed" | "complete"
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        event.update(extra)
    payload = json.dumps(event)
    try:
        redis_client.publish(f"lead:{lead_id}:events", payload)
        redis_client.publish("pipeline:events", payload)
    except Exception as e:
        logger.debug(f"Redis publish failed: {e}")


def _get_sync_db():
    """Get a synchronous DB session for Celery tasks."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    # Use sync URL for Celery (replace asyncpg with psycopg2)
    sync_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(sync_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    return Session()


try:
    from celery_app import celery_app
except ImportError:
    from app.pipeline._celery_stub import celery_app


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def enrich_lead_task(self, lead_id: str):
    """
    Main enrichment pipeline task.
    Runs all scrapers and enrichers, gracefully handles failures.
    """
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    db = _get_sync_db()

    try:
        from app.models.lead import Lead, LeadStatus
        from app.models.enrichment import Enrichment
        from app.models.score_history import ScoreHistory
        from app.models.icp_config import ICPConfig
        from app.models.draft import Draft

        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            logger.error(f"Lead {lead_id} not found")
            return

        # Mark as enriching
        lead.status = LeadStatus.enriching
        db.commit()
        _publish_event(redis_client, lead_id, "started", "in_progress",
                       {"name": lead.name, "company": lead.company})

        enriched_sources = {}
        website_data = {}
        linkedin_data = {}
        news_articles = []

        # ── Step 1: Website scraping ───────────────────────────────────────────
        domain = lead.domain
        if domain:
            _publish_event(redis_client, lead_id, "website", "in_progress")
            try:
                from app.pipeline.scrapers.website import scrape_company_website
                website_data = _run_async(scrape_company_website(domain))
                if website_data.get("error") and website_data.get("pages_scraped", 0) == 0:
                    enriched_sources["website"] = "failed"
                else:
                    enriched_sources["website"] = "success"
                _publish_event(redis_client, lead_id, "website",
                               "success" if enriched_sources["website"] == "success" else "failed")
            except Exception as e:
                enriched_sources["website"] = "failed"
                logger.warning(f"Website scrape failed for {lead_id}: {e}")
                _publish_event(redis_client, lead_id, "website", "failed")
        else:
            enriched_sources["website"] = "skipped"

        # ── Step 2: LinkedIn scraping ──────────────────────────────────────────
        _publish_event(redis_client, lead_id, "linkedin", "in_progress")
        try:
            from app.pipeline.scrapers.linkedin import scrape_linkedin_company, scrape_linkedin_profile, extract_slug_from_url

            company_slug = None
            profile_slug = None

            if lead.linkedin_url:
                if "/company/" in lead.linkedin_url:
                    company_slug = extract_slug_from_url(lead.linkedin_url, "company")
                elif "/in/" in lead.linkedin_url:
                    profile_slug = extract_slug_from_url(lead.linkedin_url, "in")

            if not company_slug and not profile_slug and lead.name and lead.company:
                # Use Google search to find the profile slug based on name and company
                from app.pipeline.scrapers.linkedin import find_linkedin_profile_slug
                profile_slug = _run_async(find_linkedin_profile_slug(lead.name, lead.company))

            if not company_slug and lead.company and not profile_slug:
                company_slug = lead.company.lower().replace(" ", "-").replace(",", "")

            if profile_slug:
                linkedin_data = _run_async(scrape_linkedin_profile(profile_slug))
            elif company_slug:
                linkedin_data = _run_async(scrape_linkedin_company(company_slug))

            # Save the discovered URL back to the lead so it shows in the frontend UI
            if not lead.linkedin_url and linkedin_data.get("url"):
                lead.linkedin_url = linkedin_data["url"]
                db.flush()

            if linkedin_data.get("blocked"):
                enriched_sources["linkedin"] = "blocked"
                _publish_event(redis_client, lead_id, "linkedin", "failed",
                               {"note": "LinkedIn blocked scrape"})
            else:
                enriched_sources["linkedin"] = "success"
                _publish_event(redis_client, lead_id, "linkedin", "success")
        except Exception as e:
            enriched_sources["linkedin"] = "failed"
            logger.warning(f"LinkedIn scrape failed for {lead_id}: {e}")
            _publish_event(redis_client, lead_id, "linkedin", "failed")

        # ── Step 3: News scraping ──────────────────────────────────────────────
        _publish_event(redis_client, lead_id, "news", "in_progress")
        try:
            from app.pipeline.scrapers.news import scrape_google_news
            company_name = lead.company or (domain.split(".")[0] if domain else None)
            if company_name:
                news_articles = _run_async(scrape_google_news(company_name))
                enriched_sources["news"] = "success" if news_articles else "empty"
            else:
                enriched_sources["news"] = "skipped"
            _publish_event(redis_client, lead_id, "news",
                           "success" if news_articles else "failed")
        except Exception as e:
            enriched_sources["news"] = "failed"
            logger.warning(f"News scrape failed for {lead_id}: {e}")
            _publish_event(redis_client, lead_id, "news", "failed")

        # ── Step 4: Run all enrichers ──────────────────────────────────────────
        _publish_event(redis_client, lead_id, "scoring", "in_progress")

        combined_text = " ".join(filter(None, [
            website_data.get("raw_text", ""),
            str(linkedin_data.get("data", {}).get("about", "")),
            str(linkedin_data.get("data", {}).get("raw_text", "")),
        ]))

        # Company size
        from app.pipeline.enrichers.company_size import infer_company_size
        li_employee_count = linkedin_data.get("data", {}).get("employee_count")
        employee_hints = website_data.get("employee_hints", [])
        if li_employee_count:
            employee_hints.append(li_employee_count)
        company_size, size_conf = infer_company_size(
            combined_text, employee_hints, website_data.get("job_count", 0)
        )

        # Tech stack
        from app.pipeline.enrichers.tech_stack import extract_tech_stack
        tech_stack, tech_conf = extract_tech_stack(
            website_data.get("raw_text", ""),
            " ".join(str(h) for h in website_data.get("tech_hints", [])),
        )
        if website_data.get("tech_hints"):
            tech_stack = list(set(tech_stack) | set(website_data["tech_hints"]))

        # Funding
        from app.pipeline.enrichers.funding import extract_funding_status
        funding_status, funding_conf = extract_funding_status(combined_text, news_articles)

        # Industry
        industry = linkedin_data.get("data", {}).get("industry")
        industry_conf = "high" if industry else "low"
        if not industry and website_data.get("meta_description"):
            # Try to infer from meta description via simple heuristic
            desc = website_data["meta_description"].lower()
            if any(w in desc for w in ["software", "saas", "tech", "platform", "api"]):
                industry = "Software / Technology"
                industry_conf = "medium"
            elif any(w in desc for w in ["fintech", "financial", "banking", "payment"]):
                industry = "Financial Technology"
                industry_conf = "medium"
            elif any(w in desc for w in ["health", "medical", "clinical", "pharma"]):
                industry = "Healthcare / Life Sciences"
                industry_conf = "medium"
            elif any(w in desc for w in ["ecommerce", "retail", "shopping"]):
                industry = "E-Commerce / Retail"
                industry_conf = "medium"

        # Contact role & seniority
        contact_role = lead.raw_csv_row.get("title") if lead.raw_csv_row else None
        if not contact_role:
            contact_role = linkedin_data.get("data", {}).get("title")
        contact_seniority = None
        if contact_role:
            # Determine seniority level from role title
            seniority_map = [
                ("c-level", ["ceo", "cto", "coo", "cfo", "cpo", "cro", "chief", "founder"]),
                ("vp", ["svp", "evp", "vp ", "vice president"]),
                ("director", ["director", "head of"]),
                ("manager", ["manager", "team lead"]),
                ("senior", ["senior", "lead", "staff", "principal"]),
                ("individual contributor", ["engineer", "analyst", "associate", "specialist"]),
            ]
            role_lower = contact_role.lower()
            for seniority, keywords in seniority_map:
                if any(kw in role_lower for kw in keywords):
                    contact_seniority = seniority.title()
                    break

        # Get active ICP config
        icp_config = db.query(ICPConfig).filter(ICPConfig.is_active == True).first()
        icp_dict = None
        if icp_config:
            icp_dict = {
                "company_size_min": icp_config.company_size_min,
                "company_size_max": icp_config.company_size_max,
                "target_industries": icp_config.target_industries,
                "required_tech_stack": icp_config.required_tech_stack,
                "min_seniority": icp_config.min_seniority,
                "disqualifiers": icp_config.disqualifiers,
                "scoring_weights": icp_config.scoring_weights,
                "criterion_weights": icp_config.criterion_weights,
            }

        # Buying signals
        from app.pipeline.enrichers.buying_signals import detect_buying_signals
        enrichment_snapshot = {
            "company_size": company_size,
            "tech_stack": tech_stack,
            "funding_status": funding_status,
            "industry": industry,
            "contact_role": contact_role,
            "recent_news": news_articles,
            "job_count": website_data.get("job_count", 0),
        }
        buying_signals = detect_buying_signals(enrichment_snapshot, icp_dict or {})

        # Email candidates (bonus)
        email_candidates = []
        try:
            from app.pipeline.email_finder import find_email_candidates
            if lead.name and domain:
                email_candidates = _run_async(find_email_candidates(lead.name, domain))
        except Exception as e:
            logger.debug(f"Email finder failed: {e}")

        # ── Step 5: ICP Scoring ────────────────────────────────────────────────
        icp_score = 0.0
        total_score = 0.0
        score_breakdown = {}
        if icp_dict:
            enrichment_snapshot["buying_signals"] = buying_signals
            from app.pipeline.icp_scorer import score_lead
            score_result = score_lead(enrichment_snapshot, icp_dict)
            icp_score = score_result["icp_fit_score"]
            total_score = score_result["total_score"]
            score_breakdown = score_result["breakdown"]

        # ── Step 6: Save enrichment ────────────────────────────────────────────
        existing_enr = db.query(Enrichment).filter(Enrichment.lead_id == lead.id).first()
        if existing_enr:
            db.delete(existing_enr)
            db.flush()

        enr = Enrichment(
            lead_id=lead.id,
            company_size=company_size,
            company_size_confidence=size_conf,
            tech_stack=tech_stack,
            tech_stack_confidence=tech_conf,
            funding_status=funding_status,
            funding_confidence=funding_conf,
            industry=industry,
            industry_confidence=industry_conf,
            contact_role=contact_role,
            contact_seniority=contact_seniority,
            recent_news=news_articles,
            buying_signals=buying_signals,
            enriched_sources=enriched_sources,
            email_candidates=email_candidates,
            raw_data={
                "website": website_data,
                "linkedin": linkedin_data,
            },
        )
        db.add(enr)

        # Update lead scores
        lead.icp_score = icp_score
        lead.total_score = total_score
        lead.icp_score_breakdown = score_breakdown
        db.flush()

        # Score history snapshot (bonus)
        history = ScoreHistory(
            lead_id=lead.id,
            icp_score=icp_score,
            total_score=total_score,
            buying_signal_count=len(buying_signals),
            snapshot_data={"breakdown": score_breakdown},
        )
        db.add(history)
        db.flush()

        # ── Step 7: Generate outreach drafts (if above threshold) ───────────────
        threshold = icp_config.score_threshold if icp_config else settings.SCORE_THRESHOLD
        if total_score >= threshold:
            _publish_event(redis_client, lead_id, "drafts", "in_progress")
            try:
                from app.llm.client import generate_email_draft
                from app.llm.prompts import build_direct_prompt, build_social_proof_prompt, validate_draft_specificity
                from app.routers.drafts import _parse_draft

                profile = {
                    "name": lead.name, "company": lead.company, "domain": lead.domain,
                    "role": contact_role, "industry": industry, "tech_stack": tech_stack,
                    "funding_status": funding_status, "buying_signals": buying_signals,
                    "recent_news": news_articles, "company_size": company_size,
                }
                product_desc = icp_config.product_description if icp_config else "our product"
                value_prop = icp_config.value_proposition if icp_config else ""

                tones = [
                    ("direct", build_direct_prompt(profile, product_desc, value_prop)),
                    ("social_proof", build_social_proof_prompt(profile, product_desc, value_prop)),
                ]

                for tone, prompt in tones:
                    raw = _run_async(generate_email_draft(prompt))
                    subject, body, cta = _parse_draft(raw, profile)
                    if not validate_draft_specificity(body, profile):
                        raw = _run_async(generate_email_draft(
                            prompt + "\nIMPORTANT: You MUST mention specific facts from the lead profile."
                        ))
                        subject, body, cta = _parse_draft(raw, profile)

                    existing_draft = db.query(Draft).filter(
                        Draft.lead_id == lead.id, Draft.tone == tone
                    ).first()
                    if existing_draft:
                        db.delete(existing_draft)
                        db.flush()

                    draft = Draft(lead_id=lead.id, tone=tone, subject=subject, body=body, call_to_action=cta)
                    db.add(draft)

                db.flush()
                _publish_event(redis_client, lead_id, "drafts", "success")
            except Exception as e:
                logger.warning(f"Draft generation failed for {lead_id}: {e}")
                _publish_event(redis_client, lead_id, "drafts", "failed")

        # ── Step 8: Mark complete ──────────────────────────────────────────────
        lead.status = LeadStatus.enriched
        db.commit()
        _publish_event(redis_client, lead_id, "complete", "success", {
            "icp_score": icp_score,
            "total_score": total_score,
            "signal_count": len(buying_signals),
        })

    except Exception as e:
        logger.error(f"Pipeline failed for lead {lead_id}: {e}", exc_info=True)
        try:
            from app.models.lead import Lead, LeadStatus
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
            if lead:
                lead.status = LeadStatus.failed
                db.commit()
        except Exception:
            pass
        _publish_event(redis_client, lead_id, "failed", "failed", {"error": str(e)})
        raise self.retry(exc=e, countdown=60)
    finally:
        db.close()
        redis_client.close()


@celery_app.task(max_retries=2)
def sync_to_crm_task(lead_id: str):
    """Sync an enriched lead to Notion CRM."""
    db = _get_sync_db()
    try:
        from app.models.lead import Lead
        from app.models.enrichment import Enrichment
        from app.models.draft import Draft
        from app.models.crm_sync import CRMSync

        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            return

        enr = db.query(Enrichment).filter(Enrichment.lead_id == lead.id).first()
        drafts = db.query(Draft).filter(Draft.lead_id == lead.id).all()

        lead_data = {
            "name": lead.name, "company": lead.company, "domain": lead.domain,
            "email": lead.email, "linkedin_url": lead.linkedin_url,
            "status": lead.status, "icp_score": lead.icp_score, "total_score": lead.total_score,
        }
        enrichment_data = {}
        if enr:
            enrichment_data = {
                "industry": enr.industry, "funding_status": enr.funding_status,
                "tech_stack": enr.tech_stack, "company_size": enr.company_size,
                "buying_signals": enr.buying_signals,
            }
        draft_data = [{"subject": d.subject, "body": d.body, "tone": d.tone} for d in drafts]

        from app.crm.notion import sync_lead_to_notion
        result = _run_async(sync_lead_to_notion(lead_data, enrichment_data, draft_data))

        # Update or create CRM sync record
        crm = db.query(CRMSync).filter(CRMSync.lead_id == lead.id).first()
        if not crm:
            crm = CRMSync(lead_id=lead.id, crm_type="notion")
            db.add(crm)

        from app.models.crm_sync import CRMSyncStatus
        from datetime import datetime, timezone
        crm.status = result["status"]
        crm.crm_record_id = result.get("record_id")
        crm.error_message = result.get("error")
        crm.synced_at = datetime.now(timezone.utc) if result["status"] in ("synced", "updated") else None
        db.commit()

    except Exception as e:
        logger.error(f"CRM sync failed for {lead_id}: {e}")
    finally:
        db.close()
