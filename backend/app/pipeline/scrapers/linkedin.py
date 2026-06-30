import asyncio
import logging
import random
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

BLOCKED_STATUSES = {999, 429, 403, 401, 302}
BLOCKED_MARKERS = ["authwall", "login", "sign-in", "captcha", "checkpoint"]


def _is_blocked(resp: httpx.Response) -> bool:
    if resp.status_code in BLOCKED_STATUSES:
        return True
    if any(m in str(resp.url) for m in BLOCKED_MARKERS):
        return True
    # Check if we got a login redirect in the body
    text_lower = resp.text[:500].lower()
    if "join linkedin" in text_lower or "sign in" in text_lower:
        return True
    return False


async def search_linkedin_via_google(company_slug: str) -> dict:
    """Fallback: Search Google for the LinkedIn page if directly blocked."""
    from app.config import settings
    if not settings.GOOGLE_API_KEY or not settings.GOOGLE_CSE_ID:
        return {}
        
    query = f"site:linkedin.com/company/{company_slug}"
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": settings.GOOGLE_API_KEY,
        "cx": settings.GOOGLE_CSE_ID,
        "q": query,
        "num": 3
    }
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                if not items:
                    return {}
                    
                snippet = items[0].get("snippet", "")
                result_data = {"raw_text": snippet}
                
                # Try to extract employee count from snippet (e.g. "500 - 1000 employees")
                emp_match = re.search(r"([\d,]+)\s+employees?", snippet, re.IGNORECASE)
                if emp_match:
                    result_data["employee_count_text"] = emp_match.group(0)
                    try:
                        result_data["employee_count"] = int(emp_match.group(1).replace(",", ""))
                    except ValueError:
                        pass
                        
                # Extract industry if present (often separated by · in snippets)
                parts = snippet.split("·")
                if len(parts) > 1:
                    result_data["industry"] = parts[1].strip()[:100]
                    
                return result_data
    except Exception as e:
        logger.debug(f"Google fallback search failed for {company_slug}: {e}")
        
    return {}


async def scrape_linkedin_company(company_slug: str) -> dict:
    """
    Scrape LinkedIn company public page.
    Returns dict with data or {blocked: True} on any auth wall.
    NEVER raises an exception.
    """
    if not company_slug:
        return {"blocked": False, "error": "no slug provided", "data": {}}

    # Random delay to mimic human browsing
    await asyncio.sleep(random.uniform(2.0, 5.0))

    url = f"https://www.linkedin.com/company/{company_slug}/"
    result = {"blocked": False, "url": url, "data": {}, "error": None}

    try:
        async with httpx.AsyncClient(
            headers=HEADERS,
            timeout=15,
            follow_redirects=True,
            verify=False,
        ) as client:
            resp = await client.get(url)

            if _is_blocked(resp):
                logger.info(f"LinkedIn blocked company: {company_slug} ({resp.status_code}). Triggering Google fallback.")
                fallback_data = await search_linkedin_via_google(company_slug)
                if fallback_data:
                    logger.info(f"Google fallback successful for {company_slug}")
                    result["data"] = fallback_data
                    result["blocked"] = False # Recovered via fallback
                    result["error"] = None
                else:
                    result["blocked"] = True
                    result["error"] = f"LinkedIn blocked with status {resp.status_code} and Google fallback failed"
                return result

            soup = BeautifulSoup(resp.text, "lxml")
            text = soup.get_text(separator=" ", strip=True)

            # Employee count: LinkedIn often shows "X employees" in company header
            emp_match = re.search(r"([\d,]+)\s+employees?", text, re.IGNORECASE)
            if emp_match:
                result["data"]["employee_count_text"] = emp_match.group(0)
                try:
                    result["data"]["employee_count"] = int(emp_match.group(1).replace(",", ""))
                except ValueError:
                    pass

            # About section
            about_section = soup.find("p", class_=re.compile(r"about|description", re.I))
            if about_section:
                result["data"]["about"] = about_section.get_text(strip=True)[:500]
            else:
                # Try meta description
                meta = soup.find("meta", attrs={"name": "description"})
                if meta:
                    result["data"]["about"] = meta.get("content", "")[:500]

            # Headquarters
            hq_match = re.search(r"Headquarters?\s*:?\s*([^\n]+)", text, re.IGNORECASE)
            if hq_match:
                result["data"]["headquarters"] = hq_match.group(1).strip()[:100]

            # Industry
            industry_match = re.search(r"Industry\s*:?\s*([^\n]+)", text, re.IGNORECASE)
            if industry_match:
                result["data"]["industry"] = industry_match.group(1).strip()[:100]

            result["data"]["raw_text"] = text[:2000]

    except httpx.TimeoutException:
        result["blocked"] = True
        result["error"] = "Timeout connecting to LinkedIn"
    except Exception as e:
        result["error"] = str(e)
        logger.debug(f"LinkedIn company scrape error for {company_slug}: {e}")

    return result


async def search_linkedin_profile_via_google(profile_slug: str) -> dict:
    """Fallback: Search Google for the LinkedIn profile page if directly blocked."""
    from app.config import settings
    if not settings.GOOGLE_API_KEY or not settings.GOOGLE_CSE_ID:
        return {}
        
    query = f"site:linkedin.com/in/{profile_slug}"
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": settings.GOOGLE_API_KEY,
        "cx": settings.GOOGLE_CSE_ID,
        "q": query,
        "num": 3
    }
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                if not items:
                    return {}
                    
                snippet = items[0].get("snippet", "")
                title = items[0].get("title", "")
                result_data = {"raw_text": snippet}
                
                # Title typically looks like "John Doe - Software Engineer - Google | LinkedIn"
                name_part = title.split("-")[0].split("|")[0].strip()
                if name_part and "LinkedIn" not in name_part:
                    result_data["name"] = name_part[:100]

                result_data["headline"] = snippet[:200]
                
                at_match = re.search(r" is (?:a |an |the )?(.+?) at (.+?)[\.|,]", snippet, re.IGNORECASE)
                if at_match:
                    result_data["title"] = at_match.group(1).strip()[:100]
                    result_data["company"] = at_match.group(2).strip()[:100]
                    
                return result_data
    except Exception as e:
        logger.debug(f"Google fallback search failed for profile {profile_slug}: {e}")
        
    return {}

async def find_linkedin_profile_slug(name: str, company: str) -> Optional[str]:
    """Search Google to find the LinkedIn profile slug for a given name and company."""
    from app.config import settings
    if not settings.GOOGLE_API_KEY or not settings.GOOGLE_CSE_ID:
        return None
        
    query = f"{name} {company} site:linkedin.com/in"
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": settings.GOOGLE_API_KEY,
        "cx": settings.GOOGLE_CSE_ID,
        "q": query,
        "num": 1
    }
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                if items:
                    link = items[0].get("link", "")
                    if "linkedin.com/in/" in link:
                        return extract_slug_from_url(link, "in")
    except Exception as e:
        logger.debug(f"Failed to find profile slug for {name} at {company}: {e}")
    return None


async def scrape_linkedin_profile(profile_slug: str) -> dict:
    """
    Scrape LinkedIn individual profile public page.
    Returns dict with data or {blocked: True} on any auth wall.
    NEVER raises an exception.
    """
    if not profile_slug:
        return {"blocked": False, "error": "no slug provided", "data": {}}

    await asyncio.sleep(random.uniform(2.0, 4.5))

    url = f"https://www.linkedin.com/in/{profile_slug}/"
    result = {"blocked": False, "url": url, "data": {}, "error": None}

    try:
        async with httpx.AsyncClient(
            headers=HEADERS,
            timeout=15,
            follow_redirects=True,
            verify=False,
        ) as client:
            resp = await client.get(url)

            if _is_blocked(resp):
                logger.info(f"LinkedIn blocked profile: {profile_slug} ({resp.status_code}). Triggering Google fallback.")
                fallback_data = await search_linkedin_profile_via_google(profile_slug)
                if fallback_data:
                    logger.info(f"Google fallback successful for profile {profile_slug}")
                    result["data"] = fallback_data
                    result["blocked"] = False # Recovered via fallback
                    result["error"] = None
                else:
                    result["blocked"] = True
                    result["error"] = f"LinkedIn blocked with status {resp.status_code} and Google fallback failed"
                return result

            soup = BeautifulSoup(resp.text, "lxml")
            text = soup.get_text(separator=" ", strip=True)

            # Name from title tag: "Name | LinkedIn"
            title_tag = soup.find("title")
            if title_tag:
                name_part = title_tag.get_text().split("|")[0].strip()
                if name_part and "LinkedIn" not in name_part:
                    result["data"]["name"] = name_part[:100]

            # Title from meta description
            meta = soup.find("meta", attrs={"name": "description"})
            if meta:
                desc = meta.get("content", "")
                result["data"]["headline"] = desc[:200]
                # Try to extract title: "Name is the Title at Company"
                at_match = re.search(r" is (?:a |an |the )?(.+?) at (.+?)[\.|,]", desc, re.IGNORECASE)
                if at_match:
                    result["data"]["title"] = at_match.group(1).strip()[:100]
                    result["data"]["company"] = at_match.group(2).strip()[:100]

            result["data"]["raw_text"] = text[:1500]

    except httpx.TimeoutException:
        result["blocked"] = True
        result["error"] = "Timeout"
    except Exception as e:
        result["error"] = str(e)
        logger.debug(f"LinkedIn profile scrape error for {profile_slug}: {e}")

    return result


def extract_slug_from_url(url: str, page_type: str = "company") -> Optional[str]:
    """Extract LinkedIn slug from a full URL."""
    if not url:
        return None
    try:
        parts = url.rstrip("/").split("/")
        if page_type in url:
            idx = parts.index(page_type)
            if idx + 1 < len(parts):
                return parts[idx + 1].split("?")[0]
    except (ValueError, IndexError):
        pass
    return None
