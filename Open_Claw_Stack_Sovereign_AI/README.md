# ⚡ Open Claw Stack — Sovereign AI Multi-Agent System

> *"The architect who builds the environment where AI lives is the one who will thrive in the emerging Operator era."*

A **Full-Stack Sovereign AI** implementation built on the four-pillar Open Claw Stack framework.
Designed for complete technical independence — no cloud dependencies, no black-box SLAs.

---

## Architecture

```
┌────────────────────────────────────────────────────────┐
│               OPEN CLAW STACK — PRA LOOP              │
│  Perception → Reasoning (Gemini 2.0 Flash) → Action   │
└────────────────────────────────────────────────────────┘
         ↕                  ↕                 ↕
   [SUPERVISOR]      [SPECIALIST AGENTS]  [EXECWALL]
   Orchestration     Security | Network   Command
   & Routing         SysAdmin | ProdLead  Firewall
```

## The Four Pillars

| Pillar | Technology | Purpose |
|--------|-----------|---------|
| **I — OS Hardening** | `sandbox.py` — Identity Dubbing, Namespace, Cgroup | Zero persistent root access |
| **II — IaC** | `execwall.py` + `policy.yaml` — PHASR rules | Command governance gateway |
| **III — Agentic Orchestration** | `supervisor.py` — PRA Loop, LangGraph-inspired | Multi-agent coordination |
| **IV — Local Inference** | `llm_client.py` — Gemini 2.0 Flash | Sovereign reasoning engine |

## The Super Team (5 Agents)

| Agent | Role | Tools |
|-------|------|-------|
| 🧭 **Supervisor** | Orchestration, task routing, report synthesis | Gemini LLM, threading |
| 🔐 **Security Auditor** | Shadow AI detection, PHASR enforcement, port audit | psutil, netstat |
| 🌐 **Network Engineer** | Ping, DNS, traceroute, latency analysis | ping, nslookup, ipconfig |
| 🖥️ **SysAdmin** | CPU, RAM, disk, process health | psutil, tasklist |
| 📝 **Product Lead** | Plain-English executive summary | Gemini NLP |

## Quick Start

```bash
pip install -r requirements.txt
python main.py
# Dashboard opens at http://localhost:8765
```

## Security Model

- **Execwall**: All commands pass through the PHASR firewall (24 allow / 13 deny rules)
- **Identity Dubbing**: Agents are dubbed for a task duration only — undubbed on completion
- **Namespace Isolation**: Documented per Linux CLONE_NEW* flags (kernel-enforced on Linux)
- **Cgroup Governance**: Resource limits prevent memory bombs and CPU exhaustion

## Built By

**Denis Aosa** — AI & Computer Vision Student at Houston Community College
- ITAI 1378 | ITSC 1307 | AWS Cloud Institute
- AntiGravity Network Vision Portfolio

---

*Part of the AntiGravity Technical Portfolio — Building Sovereign AI, One Pillar at a Time.*
