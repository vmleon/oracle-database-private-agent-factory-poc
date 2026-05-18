"""OCR service for the PAF Decisioning Engine PoC.

Wraps docTR behind a small FastAPI surface. Designed to run on a LAN GPU host
(DGX Spark or commodity NVIDIA box) and be reached over HTTP from PAF / the
backend.

Endpoints:
    GET  /health         service liveness + model-loaded flag
    POST /extract        multipart image -> {text, mean_confidence, quality_tier, ...}

Quality tier thresholds are configurable via OCR_USABLE_MIN_CONFIDENCE and
OCR_MARGINAL_MIN_CONFIDENCE (defaults 0.85 / 0.60).
"""

from __future__ import annotations

import io
import logging
import os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from PIL import Image

log = logging.getLogger("ocr")

USABLE_MIN = float(os.environ.get("OCR_USABLE_MIN_CONFIDENCE", "0.85"))
MARGINAL_MIN = float(os.environ.get("OCR_MARGINAL_MIN_CONFIDENCE", "0.60"))

state: dict = {"model": None}


@asynccontextmanager
async def lifespan(_: FastAPI):
    from doctr.models import ocr_predictor

    log.info("Loading docTR model (pretrained)...")
    state["model"] = ocr_predictor(pretrained=True)
    log.info("docTR model loaded.")
    yield
    state["model"] = None


app = FastAPI(title="PAF OCR Service", lifespan=lifespan)


def _tier(mean_conf: float) -> Literal["USABLE", "MARGINAL", "UNUSABLE"]:
    if mean_conf >= USABLE_MIN:
        return "USABLE"
    if mean_conf >= MARGINAL_MIN:
        return "MARGINAL"
    return "UNUSABLE"


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model_loaded": state["model"] is not None,
        "usable_min": USABLE_MIN,
        "marginal_min": MARGINAL_MIN,
    }


@app.post("/extract")
async def extract(file: UploadFile = File(...)):
    if state["model"] is None:
        raise HTTPException(status_code=503, detail="Model not loaded yet")

    raw = await file.read()
    try:
        Image.open(io.BytesIO(raw)).verify()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Not a valid image: {e}")

    from doctr.io import DocumentFile

    doc = DocumentFile.from_images(raw)
    result = state["model"](doc)

    words = [
        w
        for page in result.pages
        for block in page.blocks
        for line in block.lines
        for w in line.words
    ]
    if not words:
        return {
            "text": "",
            "mean_confidence": 0.0,
            "quality_tier": "UNUSABLE",
            "word_count": 0,
        }

    text = " ".join(w.value for w in words)
    mean_conf = sum(w.confidence for w in words) / len(words)
    return {
        "text": text,
        "mean_confidence": round(mean_conf, 4),
        "quality_tier": _tier(mean_conf),
        "word_count": len(words),
    }
