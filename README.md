# OutreachOS — Web-Based Automated Outreach & Network Management Platform

**Developed by Talha Doğan**

---

## What is OutreachOS?

OutreachOS is a full-stack SaaS platform built for **educational and research purposes**.  
It demonstrates how modern web automation, asynchronous task queues, and real-time communication systems work together in a production-grade architecture.

The system allows users to:
- Configure proxy settings via a web interface
- Set daily operation limits
- Run browser automation tasks asynchronously in the background
- Monitor task progress in real-time via WebSocket

---

## How It Works
### Step by Step

1. **User opens the dashboard** and configures proxy settings and daily limits
2. **User dispatches a task** (visit profile / send connection / send message)
3. **FastAPI validates the request** and pushes the task to Redis queue
4. **Celery Worker picks up the task** from the queue
5. **Playwright launches a headless Chromium browser** with stealth configuration
6. **Human behavior simulation** runs: random delays, mouse movements, natural typing speed
7. **Task result is saved** to Redis and the database
8. **Frontend receives real-time updates** via WebSocket

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend API | Python FastAPI |
| Task Queue | Celery + Redis |
| Browser Automation | Playwright (Chromium) |
| Database | PostgreSQL 16 |
| Cache / Broker | Redis 7 |
| Authentication | JWT (access + refresh tokens) |
| Frontend | React + TypeScript |
| Containerization | Docker + Docker Compose |

---

## Key Features

- **Async-first architecture** — Non-blocking I/O throughout the stack
- **Human behavior simulation** — Gaussian-distributed delays, realistic mouse paths, variable typing speed
- **Anti-detection measures** — Browser fingerprint spoofing, stealth launch flags, navigator patches
- **Zombie-process prevention** — `force_close()` guarantees Playwright/Chromium cleanup in all exit paths
- **Connection leak prevention** — SQLAlchemy `yield` dependency with guaranteed `session.close()`
- **Rate limiting** — Redis Lua script for atomic per-user daily action counting
- **Real-time monitoring** — Redis Pub/Sub → WebSocket → React dashboard

---

## ⚠️ Legal Disclaimer

> **This project is strictly an educational and portfolio demonstration.**
>
> - This software was developed solely to showcase software architecture, async systems design, and full-stack development skills.
> - The developer (**Talha Doğan**) does not take any responsibility for how this software is used by third parties.
> - Automating interactions on any platform (LinkedIn, Twitter, etc.) may violate their Terms of Service.
> - It is the **sole responsibility of the end user** to ensure compliance with applicable laws, platform terms, and regulations before using this software.
> - This project is **not intended for commercial use or deployment** against any live platform without explicit authorization.
> - The developer bears **no legal liability** for misuse of this codebase.
>
> **Use at your own risk. This is a learning project only.**

---

## Project Structure
---

## Getting Started

```bash
# Start infrastructure
docker compose -f docker-compose.dev.yml up -d

# Start API
cd apps/api && .venv\Scripts\Activate.ps1
cd src && python -m uvicorn main:app --reload --port 8000

# Start Worker
cd apps/worker && .venv\Scripts\Activate.ps1
cd src && celery -A celery_app worker -Q outreach:high,outreach:default,outreach:low --loglevel=info
```

---

## Developer

**Talha Doğan**  
Full-Stack Developer | Software Architecture Enthusiast

---

*This project is for educational purposes only. All rights reserved © 2026 Talha Doğan*
