# OCR service

Minimum-capability OCR service for the Decisioning Engine PoC. Wraps [docTR](https://github.com/mindee/doctr) behind a small FastAPI surface so PAF and the backend can call it over HTTP.

The service is intentionally **not** in `deploy/podman/compose.local.yml` — it is meant to run on a separate GPU-equipped host on the LAN (e.g. an NVIDIA DGX Spark), with `.env`'s `OCR_HOST` / `OCR_PORT` pointing at it. See [`docs/DESIGN.md`](../../docs/DESIGN.md) for the wider picture.

## Why docTR (vs PaddleOCR / Tesseract / EasyOCR)

The synthetic ID / payslip / statement templates used by the PoC are controlled and clean. docTR gives us:

- A clean Python API and predictable outputs (`page → block → line → word → value, confidence, bbox`).
- Lighter container footprint than PaddleOCR (no PaddlePaddle stack).
- PyTorch backend that runs unmodified inside NVIDIA's NGC PyTorch container.
- Per-word confidence usable directly for our `USABLE / MARGINAL / UNUSABLE` tier logic.

If real-world document quality later drives us toward PaddleOCR, swapping is a single-file change inside `app.py` because the `/extract` contract stays the same.

YOLO-based field detection (the second half of the use case's OCR pipeline) is **not** in scope here. It belongs in a later iteration once the synthetic ID templates exist; this service will then move from "extract all text" to "extract per-field text + per-field confidence".

## API

| Method | Path       | Body                        | Response                                            |
| ------ | ---------- | --------------------------- | --------------------------------------------------- |
| `GET`  | `/health`  | —                           | `{status, model_loaded, usable_min, marginal_min}`  |
| `POST` | `/extract` | multipart `file=@image.png` | `{text, mean_confidence, quality_tier, word_count}` |

`quality_tier` is one of `USABLE` / `MARGINAL` / `UNUSABLE`, derived from `mean_confidence` and the configurable thresholds.

## Configuration

| Env var                       | Default | Purpose                                                        |
| ----------------------------- | ------- | -------------------------------------------------------------- |
| `OCR_PORT`                    | `8500`  | HTTP port                                                      |
| `OCR_USABLE_MIN_CONFIDENCE`   | `0.85`  | Mean-confidence floor for `USABLE`                             |
| `OCR_MARGINAL_MIN_CONFIDENCE` | `0.60`  | Mean-confidence floor for `MARGINAL` (below this → `UNUSABLE`) |

The thresholds are deliberately exposed as env vars rather than in DB config for now — they are infrastructure tuning, not policy. The use case's per-document quality logic lives in OPA + the Application Service; this service only reports raw confidence.

## Prerequisites on the GPU host

- NVIDIA driver matching the chosen NGC tag (verify with `nvidia-smi`).
- `podman` 5+ (or `docker` if you prefer).
- For DGX Spark (Grace+Blackwell ARM): use the same NGC PyTorch tag — NVIDIA's NGC images are multi-arch.

## Build

From a checkout of this repo on the GPU host:

```bash
cd src/ocr
podman build -t paf-ocr:latest -f Containerfile .
```

The first build pulls the NGC PyTorch base (~10 GB) and the docTR model weights on first run. Subsequent builds are fast.

## Run

```bash
podman run --rm -d \
  --name paf-ocr \
  --device nvidia.com/gpu=all \
  -p 8500:8500 \
  -e OCR_USABLE_MIN_CONFIDENCE=0.85 \
  -e OCR_MARGINAL_MIN_CONFIDENCE=0.60 \
  paf-ocr:latest
```

On Docker, the GPU flag is `--gpus all` instead of `--device nvidia.com/gpu=all`.

Once it is up, point `.env` on the developer machine at it:

```
OCR_HOST=<dgx-spark-lan-ip>
OCR_PORT=8500
```

## Smoke test

```bash
# Liveness
curl -s http://<dgx-spark-lan-ip>:8500/health | jq .

# Expected:
# {
#   "status": "ok",
#   "model_loaded": true,
#   "usable_min": 0.85,
#   "marginal_min": 0.60
# }
```

```bash
# Extraction (use any text-bearing image you have on hand)
curl -s -F "file=@sample-payslip.png" \
  http://<dgx-spark-lan-ip>:8500/extract | jq .

# Expected (illustrative):
# {
#   "text": "ACME PAYROLL ...",
#   "mean_confidence": 0.93,
#   "quality_tier": "USABLE",
#   "word_count": 127
# }
```

## Troubleshooting

**`Model not loaded yet` (HTTP 503).** The service is still pulling docTR weights on first start. Wait ~30–60 s and retry. `start-period` in the Containerfile healthcheck is 120 s for this reason.

**Container starts but `nvidia-smi` is empty inside.** GPU device passthrough failed. Verify `nvidia-ctk` / NVIDIA Container Toolkit is installed on the host and CDI generation has been run (`sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml`).

**Slow inference.** docTR defaults are fine for clean synthetic docs. If you need higher accuracy on noisier inputs, switch the predictor to `ocr_predictor(det_arch="db_resnet50", reco_arch="parseq", pretrained=True)` in `app.py`; the API contract stays the same.

**Build fails with `nvcr.io` 401/403.** NGC public PyTorch images are pullable without login, but if you hit auth issues, run `podman login nvcr.io` with an NGC API key. The image is also mirrored on Docker Hub if needed: `pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime` (you would lose NVIDIA's NGC optimisations but the service still works).

## Future work

1. Synthetic dataset: generate template IDs / payslips / bank statements at the three quality tiers (clean / marginal / unusable).
2. YOLO field detection: train a small YOLOv8/v11 model on the synthetic templates; replace "extract all text" with "extract per-field text".
3. MCP wrapper: expose this service as an MCP server (`/extract_document` tool) for direct consumption by the Decisioning Agent in PAF. The current HTTP surface stays for the Application Service's fast-path.
4. Multi-page PDF support: `DocumentFile.from_pdf(...)` is a one-line change once the use case needs it.
