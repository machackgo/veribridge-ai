# CareerProof AI API

FastAPI backend skeleton for the CareerProof AI student MVP.

## Create a Virtual Environment

```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
```

## Install Dependencies

```bash
pip install -r requirements.txt
```

## Configure Environment

```bash
cp .env.example .env
```

The default values are safe for local development and do not contain secrets.

## Run Locally

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Test the Health Endpoint

```bash
curl http://localhost:8000/api/v1/health
```

Expected response:

```json
{
  "status": "ok",
  "service": "careerproof-api",
  "version": "0.1.0"
}
```

## Run Tests

```bash
pytest
```
