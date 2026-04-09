"""
Open Claw Stack — Main Entry Point
=====================================
Bootstraps the entire sovereign AI stack:
  1. Loads config and policy
  2. Initializes SharedState, Execwall, LLM client
  3. Instantiates all 5 agents
  4. Starts the FastAPI/WebSocket server in a background thread
  5. Opens the dashboard in the browser
  6. Accepts CLI task input

Usage:
  python main.py                          # Interactive mode (opens dashboard)
  python main.py --task "Check my system" # One-shot mode
  python main.py --no-browser             # Skip auto-opening browser
"""
import argparse
import logging
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Force UTF-8 output on Windows to handle Unicode characters
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import uvicorn
import yaml

# ── Path setup ──────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# ── Core imports ────────────────────────────────
from core.state     import SharedState
from core.execwall  import Execwall
from core.sandbox   import Cgroup

# ── Agent imports ────────────────────────────────
from inference.llm_client         import LLMClient
from agents.supervisor            import SupervisorAgent
from agents.security_auditor      import SecurityAuditorAgent
from agents.network_engineer      import NetworkEngineerAgent
from agents.sysadmin              import SysAdminAgent
from agents.product_lead          import ProductLeadAgent

# ── Server ──────────────────────────────────────
import server as srv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("open_claw.main")

BANNER = """
╔══════════════════════════════════════════════════════════════╗
║          🌐  OPEN CLAW STACK — SOVEREIGN AI SYSTEM          ║
║         Four-Pillar Autonomous Administration Platform       ║
╠══════════════════════════════════════════════════════════════╣
║  Pillar I  : OS Hardening & Identity (Dubbing / Execwall)   ║
║  Pillar II : Infrastructure as Code (Bash + Python IaC)     ║
║  Pillar III: Agentic Orchestration (PRA Loop / LangGraph)   ║
║  Pillar IV : Local Inference (Gemini 2.0 Flash / Quantized) ║
╠══════════════════════════════════════════════════════════════╣
║  Agents: Supervisor | Security | Network | SysAdmin | PLead ║
╚══════════════════════════════════════════════════════════════╝
"""


def load_config() -> dict:
    cfg_path = ROOT / "config.yaml"
    try:
        with open(cfg_path) as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.warning(f"Config load failed ({e}), using defaults")
        return {
            "llm":       {"model": "gemini-2.0-flash"},
            "dashboard": {"port": 8765, "host": "localhost", "auto_open": True},
        }


def build_stack(config: dict):
    """Construct all components of the Open Claw Stack."""

    logger.info("🔧 Initializing SharedState...")
    state = SharedState()
    state.add_message("system", "🚀 Open Claw Stack initializing...", "system")

    logger.info("🛡️  Loading Execwall policy...")
    execwall = Execwall(policy_path=ROOT / "policy.yaml", state=state)

    logger.info("🧠 Connecting to Gemini LLM...")
    llm_cfg = config.get("llm", {})
    llm = LLMClient(model=llm_cfg.get("model", "gemini-2.0-flash"))
    state.add_message(
        "system",
        f"🧠 LLM backend: {llm.backend.upper()} ({llm.model_name})",
        "system",
    )

    logger.info("🤖 Instantiating agents...")
    net_agent     = NetworkEngineerAgent(state, execwall)
    sec_agent     = SecurityAuditorAgent(state, execwall)
    sys_agent     = SysAdminAgent(state, execwall)
    product_agent = ProductLeadAgent(state, llm)

    agents = {
        "network_engineer": net_agent,
        "security_auditor": sec_agent,
        "sysadmin":         sys_agent,
        "product_lead":     product_agent,
    }

    supervisor = SupervisorAgent(state, llm, execwall, agents)

    state.add_message(
        "system",
        "✅ All systems online. Open Claw Stack ready for tasks.",
        "system",
    )
    logger.info("✅ Stack initialized — all 5 agents ready")
    return state, execwall, supervisor


def run_server_thread(host: str, port: int):
    """Run the uvicorn server in a background daemon thread."""
    server = uvicorn.Server(
        uvicorn.Config(
            srv.app,
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
        )
    )
    server.run()


def main():
    parser = argparse.ArgumentParser(description="Open Claw Stack — Sovereign AI System")
    parser.add_argument("--task",       type=str, default=None, help="Run a one-shot task")
    parser.add_argument("--no-browser", action="store_true",    help="Skip opening browser")
    parser.add_argument("--port",       type=int, default=8765, help="Dashboard port")
    args = parser.parse_args()

    print(BANNER)

    # Load config
    config = load_config()
    dash   = config.get("dashboard", {})
    host   = dash.get("host", "localhost")
    port   = args.port or dash.get("port", 8765)
    url    = f"http://{host}:{port}"

    # Build stack
    state, execwall, supervisor = build_stack(config)

    # Inject into server module
    srv.shared_state = state
    srv.execwall     = execwall
    srv.supervisor   = supervisor

    # Start server in background thread
    logger.info(f"🌐 Starting dashboard server at {url}")
    t = threading.Thread(target=run_server_thread, args=(host, port), daemon=True)
    t.start()
    time.sleep(1.5)   # Let server warm up

    print(f"\n  🌐 Dashboard: {url}")
    print(f"  📡 WebSocket: ws://{host}:{port}/ws")
    print(f"  🛡️  Execwall:  {len(execwall._allow)} allow rules, {len(execwall._deny)} deny rules")
    print(f"  🧠 LLM:       {supervisor.llm.backend.upper()} ({supervisor.llm.model_name})")
    print()

    # Auto-open browser
    if not args.no_browser and (config.get("dashboard", {}).get("auto_open", True)):
        webbrowser.open(url)
        logger.info("🌐 Browser opened")

    # One-shot mode
    if args.task:
        print(f"  ▶  Running task: {args.task}\n")
        result = supervisor.run(args.task)
        print("\n" + "─" * 60)
        print(result)
        print("─" * 60)
        print("\n  ✅ Task complete. Dashboard still running at", url)
        print("  Press Ctrl+C to exit.\n")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n  👋 Shutting down Open Claw Stack.")
        return

    # Interactive CLI mode
    print("  Type a task and press Enter. Type 'quit' to exit.")
    print("  Example: 'Check if the network is slow and if there's a security breach'\n")

    while True:
        try:
            task = input("  🔵 Task > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  👋 Shutting down Open Claw Stack.")
            break

        if not task:
            continue
        if task.lower() in ("quit", "exit", "q"):
            print("\n  👋 Shutting down Open Claw Stack.")
            break
        if task.lower() == "status":
            d = state.to_dict()
            print(f"  Phase: {d['pra_phase']} | Agents:", {k: v["status"] for k, v in d["agents"].items()})
            continue

        print(f"\n  ▶  Dispatching task to Supervisor...\n")
        # Run in thread so CLI stays responsive
        def _run():
            try:
                result = supervisor.run(task)
                print("\n" + "─" * 60)
                print(result[:3000])
                print("─" * 60 + "\n")
                print("  🔵 Task > ", end="", flush=True)
            except Exception as exc:
                print(f"\n  ❌ Error: {exc}\n")

        t2 = threading.Thread(target=_run, daemon=True)
        t2.start()


if __name__ == "__main__":
    main()
