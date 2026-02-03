# PixelKid API - Minecraft Pixel Art Generator

## Übersicht

PixelKid ist eine AI-gestützte Plattform zur Generierung von Minecraft-Pixel-Art. Die API verarbeitet Anfragen über eine Redis-Queue und skaliert automatisch Worker-Container je nach Last.

## Architektur

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Frontend      │────▶│   API Server    │────▶│   Redis Queue   │
│  (Next.js)      │     │   (FastAPI)     │     │                 │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                          │
                              ┌───────────────────────────┼───────────────────────────┐
                              │                           │                           │
                        ┌─────▼─────┐               ┌─────▼─────┐               ┌─────▼─────┐
                        │  Worker 1  │               │  Worker 2  │               │  Worker N  │
                        │ (Container)│               │ (Container)│               │ (Container)│
                        └─────┬─────┘               └─────┬─────┘               └─────┬─────┘
                              │                           │                           │
                              └───────────────────────────┼───────────────────────────┘
                                                          │
                                                    ┌─────▼─────┐
                                                    │ Stability │
                                                    │ AI / SDXL │
                                                    └───────────┘
```

## Quick Start

### Mit Docker Compose

```bash
# .env Datei erstellen
cp .env.example .env

# Anpassen (wichtig: STABILITY_API_KEY oder REPLICATE_API_KEY setzen)
nano .env

# Starten
docker-compose up -d

# Logs anzeigen
docker-compose logs -f api
```

### Lokal entwickeln

```bash
# Virtuelle Umgebung erstellen
python -m venv venv
source venv/bin/activate  # oder: venv\Scripts\activate (Windows)

# Abhängigkeiten installieren
pip install -r requirements.txt

# Redis und MySQL starten (via Docker)
docker-compose up -d redis db

# API starten
uvicorn api:app --reload

# Worker starten (neues Terminal)
python -m src.app.worker.processor
```

## API Endpoints

### Authentifizierung

```bash
# Registrieren
POST /v1/auth/register
{
  "email": "user@example.com",
  "username": "pixelartist",
  "password": "securepassword123"
}

# Login
POST /v1/auth/login
{
  "email": "user@example.com",
  "password": "securepassword123"
}
# -> Returns: access_token, refresh_token

# API Key erstellen
POST /v1/auth/api-keys
Authorization: Bearer <token>
{
  "name": "My App"
}
# -> Returns: api_key (nur einmal sichtbar!)
```

### Generierung

```bash
# Pixel Art generieren
POST /v1/responses
Authorization: Bearer <token_oder_api_key>
{
  "model": "block-agent",
  "input": "diamond ore block with blue crystals",
  "size": "16x16",
  "is_public": false
}

# Status abfragen
GET /v1/responses/{id}/status

# Ergebnis abrufen
GET /v1/responses/{id}
```

### Verfügbare Models

| Model | Beschreibung | Beste für |
|-------|--------------|-----------|
| `block-agent` | 2D Frontal-Texturen | Block-Texturen, Tiles |
| `item-agent` | Isometrische Item-Icons | Inventar-Items, Tools |
| `armor-agent` | Rüstungs-Sprites | Helm, Brustpanzer, etc. |
| `prompt-agent` | Freie Pixel-Art | Alles andere |

### Größen

- `16x16` (Standard für Minecraft)
- `32x32` (HD)
- `64x64` (Ultra HD)
- `128x128` (Extrem HD)

## Umgebungsvariablen

| Variable | Beschreibung | Standard |
|----------|--------------|----------|
| `DATABASE_URL` | MySQL Connection String | - |
| `REDIS_HOST` | Redis Host | localhost |
| `REDIS_PORT` | Redis Port | 6379 |
| `STABILITY_API_KEY` | Stability AI API Key | - |
| `REPLICATE_API_KEY` | Replicate API Key (Fallback) | - |
| `MIN_CONTAINERS` | Minimale Worker | 2 |
| `MAX_CONTAINERS` | Maximale Worker | 3 |
| `SCALING_THRESHOLD` | Skalierungs-Schwelle (%) | 75 |
| `MAXIMUM_REQUESTS` | Max Anfragen pro Container | 200 |
| `JWT_SECRET` | JWT Geheimnis | - |

## Container-Skalierung

Das System skaliert automatisch Worker-Container:

1. **Scale Up** wenn:
   - Durchschnittliche Last > `SCALING_THRESHOLD` (75%)
   - Queue > 50% der Kapazität

2. **Scale Down** wenn:
   - Last < 30%
   - Queue < 10% der Kapazität
   - Mehr als `MIN_CONTAINERS` aktiv

## Entwicklung

### Projekt-Struktur

```
pixelkid-api/
├── api.py                 # FastAPI App
├── docker-compose.yml     # Container-Orchestrierung
├── Dockerfile             # API Container
├── Dockerfile.worker      # Worker Container
├── requirements.txt       # Python-Abhängigkeiten
└── src/
    └── app/
        ├── config.py      # Konfiguration
        ├── database.py    # SQLAlchemy Setup
        ├── redis_client.py # Redis Setup
        ├── models.py      # Datenbank-Modelle
        ├── schemas.py     # Pydantic Schemas
        ├── auth.py        # Authentifizierung
        ├── dependencies.py # FastAPI Dependencies
        ├── routes/        # API Endpoints
        │   ├── auth.py
        │   ├── generations.py
        │   ├── gallery.py
        │   └── health.py
        ├── services/      # Business Logic
        │   └── ai_generator.py
        └── worker/        # Queue Processing
            ├── processor.py
            └── scaler.py
```

## Lizenz

MIT
