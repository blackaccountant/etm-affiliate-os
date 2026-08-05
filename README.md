# ETM Affiliate OS

> An AI-powered Affiliate Marketing Operating System built with FastAPI, PostgreSQL, OpenAI, and Ollama.

---

## Vision

ETM Affiliate OS is designed to automate the entire affiliate marketing business using Artificial Intelligence.

Instead of simply managing affiliate products, the platform is being built to:

- Discover profitable affiliate products
- Analyze commission structures
- Generate SEO content
- Publish articles automatically
- Track rankings and conversions
- Optimize campaigns
- Operate as an autonomous AI-powered affiliate business

---

# Current Version

**Version:** v0.3.0

Status:

- Sprint 1 ✅ Foundation
- Sprint 2 ✅ Database
- Sprint 3 ✅ API
- Sprint 4 ✅ Repository Pattern
- Sprint 5 ✅ Service Layer
- Sprint 6 ✅ Infrastructure
- Sprint 7 🚧 AI Core (In Progress)

---

# Technology Stack

## Backend

- Python
- FastAPI
- SQLAlchemy
- PostgreSQL
- Alembic

## AI

- OpenAI
- Ollama

## Development

- Git
- GitHub
- Swagger / OpenAPI

---

# Current Features

## Infrastructure

- FastAPI Application
- PostgreSQL Integration
- SQLAlchemy ORM
- Alembic Migrations

## Architecture

- Repository Pattern
- Service Layer
- Dependency Injection
- Global Exception Handling
- Centralized Logging
- Pagination Utilities

## Product Management

- Create Product
- Read Product
- Update Product
- Delete Product

---

# Project Structure

```
backend/
│
├── app/
│   ├── api/
│   ├── common/
│   ├── core/
│   ├── database/
│   ├── exceptions/
│   ├── integrations/
│   ├── jobs/
│   ├── logging/
│   ├── models/
│   ├── providers/
│   ├── repositories/
│   ├── scheduler/
│   ├── schemas/
│   ├── services/
│   ├── utils/
│   └── workflows/
│
docs/
frontend/
tests/
```

---

# Planned AI Architecture

```
AI Manager
        │
        ▼
Provider Factory
   │            │
   ▼            ▼
OpenAI      Ollama
        │
        ▼
Workers
│
├── Product Hunter
├── Content Writer
├── SEO Optimizer
├── Publisher
└── Analytics
```

---

# Development Roadmap

## Phase 1

Backend Infrastructure ✅

## Phase 2

AI Core 🚧

## Phase 3

Affiliate Product Discovery

## Phase 4

Content Generation

## Phase 5

Publishing Engine

## Phase 6

Analytics

## Phase 7

Autonomous Affiliate Business

---

# Running the Project

Clone the repository

```bash
git clone https://github.com/blackaccountant/etm-affiliate-os.git
```

Enter the backend

```bash
cd etm-affiliate-os/backend
```

Install dependencies

```bash
pip install -r Requirements.txt
```

Run FastAPI

```bash
uvicorn app.main:app --reload
```

Swagger Documentation

```
http://127.0.0.1:8000/docs
```

---

# Long-Term Goal

The objective is to build an AI Operating System capable of running an affiliate marketing business with minimal human intervention.

Future AI workers will automatically:

- Discover affiliate products
- Research keywords
- Generate articles
- Create social media posts
- Publish content
- Monitor analytics
- Optimize revenue

---

# Contributing

Contributions, suggestions, and discussions are welcome.

---

# License

MIT License

---

Built by ETM