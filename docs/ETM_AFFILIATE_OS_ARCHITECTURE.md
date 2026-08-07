# ETM Affiliate OS Architecture
Version: v0.8.0
Status: Living Architecture Document

---

# Vision

ETM Affiliate OS is an AI Operating System designed to discover, evaluate, organize, and monetize affiliate opportunities autonomously.

Instead of being a single AI application, ETM Affiliate OS coordinates specialized AI workers that collaborate through shared workflows, memory, scheduling, and intelligent orchestration.

The long-term goal is to create an autonomous digital business capable of continuously researching products, producing content, publishing marketing assets, monitoring performance, and improving itself with minimal human intervention.

---

# Core Principles

1. One responsibility per component.
2. Workers should never know about each other directly.
3. All execution flows through the Workflow Engine.
4. Memory should be centralized.
5. Every major feature must be testable.
6. Infrastructure should remain modular.
7. Every subsystem should be replaceable without affecting the rest of the platform.

---

# System Overview

                    User/API
                        │
                        ▼
                  Workflow Engine
                        │
                        ▼
               Workflow Registry
                        │
                        ▼
                 Selected Workflow
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
   Research        Intelligence     Repository
        │               │               │
        └───────────────┼───────────────┘
                        ▼
                  Memory Bus
                        │
                        ▼
                   PostgreSQL

Future Layers

Scheduler
Task Queue
Executor
Analytics
Learning
Automation

---

# Major Components

## Workflow Engine

Responsible for executing workflows.

Responsibilities:

- Receive workflow requests
- Resolve workflow from registry
- Execute workflow
- Return workflow results

---

## Workflow Registry

Maintains all registered workflows.

Responsibilities:

- Register workflows
- Retrieve workflows
- List available workflows

No workflow should be hardcoded inside the Workflow Engine.

---

## Workflow

A workflow represents a complete business process.

Example:

Affiliate Discovery Workflow

Steps:

1. Fetch website
2. Analyze company
3. Score affiliate opportunity
4. Save to database
5. Return structured result

---

## Worker

A worker performs one specialized task.

Examples:

- Product Hunter
- Keyword Hunter
- Content Writer
- Publisher
- SEO Auditor
- Analytics Worker

Workers do not communicate directly.

Workers communicate through workflows.

---

## Scheduler

Responsible for deciding when work should begin.

Future responsibilities:

- Scheduled execution
- Recurring jobs
- Delayed jobs
- Prioritized jobs

---

## Task Queue

Stores pending work.

Task lifecycle:

CREATED

↓

QUEUED

↓

RUNNING

↓

COMPLETED

or

FAILED

---

## Task Executor

Consumes queued tasks.

Responsibilities:

- Retrieve task
- Execute workflow
- Update task status
- Return results

---

## Memory Bus

Shared runtime memory.

Purpose:

- Share context
- Store temporary execution state
- Reduce repeated computation
- Enable future multi-agent collaboration

Future versions may support:

- Redis
- Vector databases
- Long-term memory
- Embeddings

---

## Intelligence Engine

Responsible for scoring and evaluating opportunities.

Current features:

- Rule-based scoring
- Affiliate grading
- Confidence scoring

Future features:

- ML-assisted scoring
- Historical learning
- Success prediction

---

## Repository Layer

Responsible for persistence.

Responsibilities:

- Save products
- Detect duplicates
- Retrieve opportunities
- Update records

Repositories never contain business logic.

---

# Current Workers

Product Hunter

Purpose:

Analyze company websites and identify affiliate opportunities.

Status:

Production Ready

---

# Planned Workers

Keyword Hunter

Content Writer

SEO Auditor

Publisher

Competitor Analyzer

Email Outreach

Trend Monitor

Social Media Manager

Revenue Optimizer

Analytics Worker

---

# Development Philosophy

Every new subsystem must satisfy:

✓ Single responsibility

✓ Unit tested

✓ Independent

✓ Replaceable

✓ Documented

---

# Roadmap

v0.8.x

- Infrastructure stabilization
- Scheduler
- Executor
- Memory improvements

v0.9.x

- Multi-worker orchestration
- Autonomous execution
- Background jobs
- Worker communication

v1.0

- Production-ready AI Operating System
- Persistent memory
- Multiple autonomous workers
- Full workflow orchestration
- Monitoring
- Metrics
- Plugin architecture

---

# Guiding Principle

ETM Affiliate OS is not an AI assistant.

It is an operating system for autonomous AI businesses.

Every architectural decision should move the platform closer to that vision.