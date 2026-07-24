# SyncUp — AI Operations Manager for Student Organizations

**Track 2: Friction to Flow · Subtrack 2A: Task & Time Management**
**Team: 3 members · Duration: 24 hours · Budget: $0 (free Microsoft services only)**

## Problem Statement

University student organizations run on volunteers juggling classes, exams, jobs, and multiple clubs. Scheduling one meeting takes days of group-chat polls. On top of that, orgs constantly lose track of shared resources (who has the projector?) and run events on guesswork budgets in scattered spreadsheets. SyncUp turns scheduling, resource, and financial chaos into one AI-managed workflow.

## Solution Overview

SyncUp is an AI agent that plans an event end-to-end: the organizer describes it in plain English — *"Plan a 100-person orientation night next week, budget $300"* — and SyncUp finds a conflict-free time, reserves the room and equipment, and drafts an itemized budget. One request, three plans.

## Core Features (24-hour scope)

### Scheduling (the anchor)

1. **Smart conflict resolution** — Ranks slots by weighted attendance: "Tue 7pm works for 9/10; the missing member is optional."
2. **Priority-aware** — Exams and deadlines outrank club meetings; crunch weeks are flagged automatically.
3. **Natural-language scheduling** — Plain-English requests via chat; the agent handles constraints and books the event.

### Resource Planning (new)

4. **Equipment & venue registry** — Track org assets (projector, banners, booth kits) and campus rooms in one inventory.
5. **Resource conflict detection** — Booking an event auto-reserves needed items; double-booked equipment across events is flagged just like calendar conflicts.
6. **AI packing lists** — From the event description, the agent proposes what's needed ("orientation night → projector, 2 mics, sign-in table, 100 chairs") and checks availability.

### Financial Planning (new)

7. **AI budget builder** — Generates an itemized cost estimate from the event description (food, printing, deposits), editable before approval.
8. **Budget vs. actual tracking** — Log expenses per event; dashboard shows semester budget burn-down across all events.
9. **Overspend early warning** — Agent flags when a planned event pushes the org past its semester allocation and suggests cuts or cheaper slots/venues.

### Distribution: meet students where they are

10. **Discord bot as the primary interface** — Student orgs already live in Discord servers. Add SyncUp to the org's server; anyone plans events with `/plan` or by mentioning @SyncUp in natural language. Zero onboarding, no new app. (Telegram bot as an optional second channel — same agent, different adapter.)

### Cut from 24h scope (mention as roadmap)

Auto-negotiation DMs, cross-org deconfliction, Teams/Copilot extension, fairness rotation.

## Free Microsoft Tech Stack

| Layer | Technology | Free how |
|---|---|---|
| LLM | **GitHub Models (GPT-4o-mini)** | Free with any GitHub account; OpenAI-compatible API. Alternative: Azure OpenAI via **Azure for Students** ($100 credit, no card) |
| Agent orchestration | **Semantic Kernel (C#)** | Open source |
| Backend | **ASP.NET Core 8 Minimal API** | Open source |
| Frontend | **Blazor** + **Fluent UI Blazor components** | Open source; deploy on **Azure Static Web Apps free tier** |
| API hosting | **Azure App Service F1** or **Azure Functions consumption plan** | Free tier / 1M free executions per month |
| Database | **Azure Cosmos DB free tier** (1000 RU/s + 25 GB) — or **SQLite** for zero setup risk | Free forever tier |
| Calendar & identity | **Microsoft Graph API** + **Microsoft Entra ID free tier** | Free; use a university M365 Education tenant or M365 developer sandbox |
| Chat interface | **Discord bot** via **Discord.Net** (C#) — optional Telegram via **Telegram.Bot** (C#) | Both bot platforms and SDKs are 100% free, no card, instant setup |
| DevOps | **GitHub** + **GitHub Actions** | Free tier |

**Why Discord/Telegram beats a Teams bot here:** no Azure Bot registration, no M365 tenant dependency for the chat layer, and it's where student orgs already coordinate. The Microsoft stack (backend, AI, hosting, data, Graph for calendars) stays fully intact — the bot is just a thin adapter.

**Risk hedge:** if Graph tenant setup eats time, mock 10 member calendars in Cosmos/SQLite — the Discord bot demo looks identical either way; swap Graph in later. Bonus: Discord identity doubles as lightweight auth — map Discord user IDs to member profiles, no SSO needed for the demo.

## Architecture

Discord bot (slash commands + mentions) / Blazor dashboard → ASP.NET Core API → Semantic Kernel agent (GitHub Models) with native functions: `FindSlots`, `CheckResources`, `BuildBudget`, `BookEvent` → Graph API (calendars/rooms) + Cosmos DB (inventory, budgets, events)

The Discord bot runs as a hosted service inside the same ASP.NET Core app (Discord.Net uses an outbound WebSocket gateway — no public webhook endpoint or tunneling needed, which also makes local dev during the hackathon painless). Telegram adapter, if added, reuses the exact same agent pipeline via long polling.

The key insight: **conflicts are one abstraction** — time conflicts, resource conflicts, and budget conflicts all run through the same scoring engine, which makes the build small and the story clean.

## 24-Hour Plan (3 people)

| Hours | Member A (Backend/Graph) | Member B (AI Agent) | Member C (Frontend/Pitch) |
|---|---|---|---|
| 0–4 | API skeleton, DB schema | Semantic Kernel setup, GitHub Models wired | Discord bot registered, slash commands responding |
| 4–10 | Scheduling engine + slot scoring | `FindSlots` + `BuildBudget` functions, prompt tuning | Bot ↔ agent pipeline; rich embeds for slot/budget replies |
| 10–16 | Resource registry + conflict checks | `CheckResources` + packing-list generation | Blazor dashboard: calendar heatmap, budget burn-down |
| 16–20 | Graph integration or mock-data fallback | End-to-end agent flow, edge cases | Demo Discord server, demo data, polish |
| 20–24 | **All: integration, demo rehearsal, pitch, buffer** | | |

## Demo Script (3 minutes)

1. In a real Discord server: `@SyncUp plan a 100-person orientation night next Thursday-ish, budget $300.`
2. SyncUp replies with rich embeds: 3 ranked time slots (with attendance %), a reserved room, a packing list with one flagged conflict ("projector already booked by Chess Club — here are alternatives"), and an itemized $287 budget.
3. Organizer taps an ✅ button on the embed → event, resources, and budget all committed; announcement posted to #events.
4. Switch to Blazor dashboard: semester burn-down shows this event keeps the org $140 under budget.

## Judging Angles

- **One-sentence pitch:** "A chief of staff for student clubs — it schedules the meeting, reserves the projector, and balances the budget in one conversation."
- Unified conflict engine (time + resources + money) is a defensible technical idea, not just an LLM wrapper.
- 100% free Microsoft stack = any student org can actually adopt it Monday morning.