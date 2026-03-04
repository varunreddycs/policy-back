from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
from requests import Response

from .config import Settings
from .models import ManifestItem
from .utils import build_http_session, stable_external_id, with_rate_limit, write_json


logger = logging.getLogger("ohio_docs_ingestor.discover")


_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)


def _normalize_url(base_url: str, href: str) -> str:
    absolute = urljoin(base_url, href.strip())
    parsed = urlparse(absolute)
    parsed = parsed._replace(fragment="", query="")
    return urlunparse(parsed)


def _is_relevant_link(index_url: str, candidate: str, agency: str, include_external_references: bool) -> bool:
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.netloc:
        return False

    path = (parsed.path or "").lower()
    host = (parsed.netloc or "").lower()
    full = candidate.lower()

    if any(x in full for x in ["javascript:", "mailto:", "tel:", "linkedin.com", "twitter.com", "google.com/chrome"]):
        return False
    if "policy-finder/google.com" in path:
        return False

    if agency == "DAS":
        if "codes.ohio.gov" in host:
            if not include_external_references:
                return False
            return True
        if "das.ohio.gov" not in host:
            return False
        return (
            path.endswith(".pdf")
            or path.endswith(".doc")
            or path.endswith(".docx")
            or path.endswith(".html")
            or path.endswith(".htm")
            or "/ohio-revised-code/" in path
            or "/wps/wcm/connect/gov/" in path
            or "/policies" in path
            or "/policy-finder/" in path
            or "policy" in path
        )
    if agency == "JFS":
        return path.endswith(".pdf") or path.endswith(".html") or path.endswith(".htm") or "/policy" in path
    return False


def _doc_type_for_url(url: str) -> str:
    path = urlparse(url).path.lower()
    if path.endswith(".pdf"):
        return "pdf"
    return "html"


def _fetch_with_fallback_user_agent(session, url: str, timeout: tuple[int, int]) -> Response:
    response = session.get(url, timeout=timeout)
    if response.status_code < 400:
        return response
    alt_headers = {"User-Agent": _BROWSER_USER_AGENT}
    response_alt = session.get(url, timeout=timeout, headers=alt_headers)
    return response_alt


def discover_documents(settings: Settings, *, max_docs: int | None = None) -> tuple[list[ManifestItem], Path]:
    agency = settings.agency.upper()
    if agency == "DAS":
        base = settings.das_index_url.rstrip("/")
        candidates = [
            settings.das_index_url,
            f"{base}/",
            base.replace("/policies", "/policy"),
            base.replace("/employee-relations/policies", "/employee-relations"),
            "https://das.ohio.gov/wps/portal/gov/das/home/policy-finder/filter-policy-finder",
        ]
    elif agency == "JFS":
        if not settings.jfs_index_url:
            raise ValueError("JFS_INDEX_URL is not configured. Set it in tools/ohio_docs_ingestor/.env")
        candidates = [settings.jfs_index_url]
    else:
        raise ValueError(f"Unsupported agency: {agency}")

    session = build_http_session(settings.user_agent)
    logger.info("discover.start", extra={"extra_fields": {"agency": agency, "index_url": candidates[0]}})

    response = None
    index_url = candidates[0]
    timeout = (settings.connect_timeout_seconds, settings.read_timeout_seconds)
    for candidate in dict.fromkeys(candidates):
        index_url = candidate
        probe = _fetch_with_fallback_user_agent(session, candidate, timeout)
        if probe.status_code < 400:
            response = probe
            break
        logger.warning(
            "discover.index_unavailable",
            extra={"extra_fields": {"agency": agency, "url": candidate, "status": probe.status_code}},
        )
    if response is None:
        raise RuntimeError(f"Unable to fetch an index page for {agency}; checked {len(set(candidates))} URLs")

    with_rate_limit(0.0, settings.rate_limit_seconds)

    soup = BeautifulSoup(response.text, "html.parser")
    discovered: list[ManifestItem] = []
    seen: set[str] = set()

    final_base_url = response.url or index_url

    def _collect_from_soup(soup_obj: BeautifulSoup, base_url: str) -> None:
        for anchor in soup_obj.find_all("a", href=True):
            href = (anchor.get("href") or "").strip()
            if not href:
                continue
            normalized = _normalize_url(base_url, href)
            if normalized in seen:
                continue
            if not _is_relevant_link(base_url, normalized, agency, settings.include_external_references):
                continue

            title = (anchor.get_text(" ", strip=True) or "").strip() or Path(urlparse(normalized).path).name or normalized
            item = ManifestItem(
                source_url=normalized,
                title=title,
                doc_type=_doc_type_for_url(normalized),
                external_id=stable_external_id(normalized, title),
                suggested_policy_type=settings.default_policy_type,
                effective_date=None,
                agency=agency,
            )
            discovered.append(item)
            seen.add(normalized)

    _collect_from_soup(soup, final_base_url)

    finder_links = [
        item.source_url
        for item in discovered
        if "policy-finder" in item.source_url and item.doc_type == "html"
    ]
    if agency == "DAS" and len(discovered) < 10:
        fallback_pages = set(finder_links)
        fallback_pages.add("https://das.ohio.gov/wps/portal/gov/das/home/policy-finder/filter-policy-finder")
        fallback_pages.add("https://das.ohio.gov/employee-relations/policies/admin-leave")
        for page_url in fallback_pages:
            try:
                page_response = _fetch_with_fallback_user_agent(session, page_url, timeout)
                if page_response.status_code >= 400:
                    continue
                with_rate_limit(0.0, settings.rate_limit_seconds)
                page_soup = BeautifulSoup(page_response.text, "html.parser")
                _collect_from_soup(page_soup, page_response.url or page_url)
            except Exception:
                logger.warning("discover.fallback_page_failed", extra={"extra_fields": {"url": page_url}})

    if agency == "DAS":
        detail_pages = {
            item.source_url
            for item in discovered
            if "das.ohio.gov" in urlparse(item.source_url).netloc.lower()
            and "/employee-relations/policies/" in urlparse(item.source_url).path.lower()
        }
        for page_url in detail_pages:
            try:
                detail_response = _fetch_with_fallback_user_agent(session, page_url, timeout)
                if detail_response.status_code >= 400:
                    continue
                with_rate_limit(0.0, settings.rate_limit_seconds)
                detail_soup = BeautifulSoup(detail_response.text, "html.parser")
                _collect_from_soup(detail_soup, detail_response.url or page_url)
            except Exception:
                logger.warning("discover.detail_page_failed", extra={"extra_fields": {"url": page_url}})

    limit = max_docs if max_docs is not None else settings.max_docs
    if limit and limit > 0:
        discovered = discovered[:limit]

    manifest_path = settings.manifests_dir / f"{agency.lower()}-discovered.json"
    write_json(manifest_path, [item.to_dict() for item in discovered])

    logger.info(
        "discover.completed",
        extra={"extra_fields": {"agency": agency, "count": len(discovered), "manifest": str(manifest_path)}},
    )
    return discovered, manifest_path
