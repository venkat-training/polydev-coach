"""
PolyDev Coach - FastAPI Application
Main entry point with all routes, middleware, and error handling.
"""
import logging
import os
import shutil
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

# Load config first — will raise if env vars missing
from config import settings
from models.schemas import (
    ErrorResponse,
    HealthResponse,
    ReviewRequest,
    ReviewResponse,
)
from agents.orchestrator import run_review_pipeline
from parsers.mulesoft_parser import (
    extract_zip_to_temp,
    run_static_analysis_on_project,
)

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ─── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("PolyDev Coach starting up | env=%s", settings.environment)
    yield
    logger.info("PolyDev Coach shutting down")


# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="PolyDev Coach API",
    description=(
        "Multi-agent AI code review for MuleSoft, Python, and Java. "
        "Powered by DigitalOcean Gradient AI Platform."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Gzip compression for large responses
app.add_middleware(GZipMiddleware, minimum_size=1000)


# ─── Exception handlers ───────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "Internal server error", "detail": str(exc)},
    )


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["system"])
def health_check():
    """Liveness probe — used by DigitalOcean App Platform."""
    return HealthResponse(
        status="ok",
        version="1.0.0",
        environment=settings.environment,
    )


@app.post(
    "/api/review",
    response_model=ReviewResponse,
    tags=["review"],
    summary="Review code (text input)",
    description=(
        "Submit source code as text. Runs the full 6-agent pipeline: "
        "static analysis → AI analyzer → coach → refactor → validator → optimizer."
    ),
)
async def review_code(request: ReviewRequest):
    """
    Main code review endpoint.

    - **code**: Source code string (MuleSoft XML, Python, or Java)
    - **language**: `python`, `java`, or `mulesoft`
    - **filename**: Optional filename for additional context
    """
    if len(request.code) > settings.max_code_length:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Code exceeds maximum length of {settings.max_code_length} characters.",
        )

    logger.info(
        "Review request | language=%s | code_len=%d | file=%s",
        request.language, len(request.code), request.filename or "N/A",
    )

    try:
        result = await run_review_pipeline(
            code=request.code,
            language=request.language.value,
            filename=request.filename or "",
        )
    except Exception as exc:
        logger.error("Pipeline failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Review pipeline failed: {str(exc)}",
        )

    return result


@app.post(
    "/api/review/mulesoft-project",
    tags=["review"],
    summary="Review a full MuleSoft project zip",
    description=(
        "Upload a .zip archive of a complete MuleSoft project. "
        "Runs mulesoft_package_validator on the full project, then the AI pipeline."
    ),
)
async def review_mulesoft_project(file: UploadFile = File(...)):
    """
    Upload a MuleSoft project zip for full validation.

    Uses your existing mulesoft_package_validator for deep static analysis,
    then passes enriched findings through the AI agent pipeline.
    """
    if not file.filename.endswith(".zip"):
        raise HTTPException(400, "Only .zip files are accepted.")

    # 50 MB limit
    MAX_ZIP_SIZE = 50 * 1024 * 1024
    content = await file.read()
    if len(content) > MAX_ZIP_SIZE:
        raise HTTPException(413, "Project zip exceeds 50MB limit.")

    tmpdir = extract_zip_to_temp(content)
    if not tmpdir:
        raise HTTPException(500, "Failed to extract zip file.")

    try:
        # Run full mulesoft_package_validator on the project
        static_result = run_static_analysis_on_project(tmpdir)

        # Build a summary XML snippet for the AI agents
        issues = static_result.get("issues", [])
        summary_code = (
            f"<!-- MuleSoft project: {file.filename} -->\n"
            f"<!-- Static analysis found {len(issues)} issues -->\n"
            f"<!-- See mulesoft_static field for full validator output -->\n"
            f"<project-summary>\n"
            f"  <total-issues>{len(issues)}</total-issues>\n"
            f"  <risk>{static_result.get('overall_risk', 'UNKNOWN')}</risk>\n"
            f"</project-summary>"
        )

        result = await run_review_pipeline(
            code=summary_code,
            language="mulesoft",
            filename=file.filename,
        )
        # Attach full static output for UI
        result["analysis"]["mulesoft_static"] = static_result.get("raw_validator_output", {})
        return result

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
