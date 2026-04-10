"""
Open Claw Stack — GPU / Thermal Agent
=======================================
Monitors GPU temperature, VRAM, utilization, and power draw.
Critical for sovereign AI environments running local LLMs like Gemma 4.

Primary: pynvml (NVIDIA only)
Fallback: subprocess nvidia-smi, then graceful no-GPU report
"""
import logging
import platform
import subprocess
import time
from typing import Dict, List, Optional, Tuple

from core.execwall import Execwall
from core.sandbox import Identity, Cgroup
from core.state import AgentStatus, SharedState

logger = logging.getLogger(__name__)
IS_WIN = platform.system() == "Windows"

# Thermal thresholds (Celsius)
TEMP_WARN  = 80
TEMP_CRIT  = 90
VRAM_WARN  = 85   # percent
UTIL_WARN  = 95   # percent


class GPUThermalAgent:
    """
    Monitors GPU health for sovereign AI workloads.
    Detects overheating, VRAM exhaustion, and throttling events.
    """

    def __init__(self, state: SharedState, execwall: Execwall):
        self.state    = state
        self.execwall = execwall
        self.cgroup   = Cgroup("gpu_thermal", mem_max_mb=128, cpu_max_percent=20)
        self._nvml_ok = False
        self._try_init_nvml()

    def _try_init_nvml(self):
        try:
            import pynvml
            pynvml.nvmlInit()
            self._nvml_ok = True
            logger.info("GPUAgent: pynvml initialized successfully")
        except Exception:
            logger.info("GPUAgent: pynvml unavailable — will use nvidia-smi fallback")

    # ──────────────────────────────────────────────
    # Main Run
    # ──────────────────────────────────────────────

    def run(self, task: str = "") -> str:
        with Identity("gpu_thermal", f"gpu-{int(time.time())}"):
            self.state.update_agent(
                "gpu_thermal", AgentStatus.PERCEIVING,
                "🌡️ GPU Agent online — scanning thermal and VRAM status..."
            )

            tool_log = []
            gpus: List[Dict] = []

            if self._nvml_ok:
                gpus = self._query_nvml()
                tool_log.append(f"✅ pynvml: {len(gpus)} GPU(s) detected")
            else:
                gpus = self._query_smi()
                tool_log.append(f"✅ nvidia-smi fallback: {len(gpus)} GPU(s)")

            if not gpus:
                self.state.update_agent(
                    "gpu_thermal", AgentStatus.DONE,
                    "ℹ️ No NVIDIA GPU detected — CPU-only inference mode",
                    metrics={"gpu_count": 0, "status": "no_gpu"},
                )
                return self._no_gpu_report(task)

            score, label = self._health_score(gpus)
            alerts = self._find_alerts(gpus)

            for alert in alerts:
                self.state.add_incident({"type": "GPU_THERMAL", "agent": "gpu_thermal", "detail": alert})

            self.state.update_agent(
                "gpu_thermal", AgentStatus.DONE,
                f"✅ GPU scan complete — {label}",
                metrics={
                    "gpu_count":   len(gpus),
                    "health_score": score,
                    "health_label": label,
                    "max_temp_c":  max(g.get("temp_c", 0) for g in gpus),
                    "max_vram_pct": max(g.get("vram_pct", 0) for g in gpus),
                    "alerts":      len(alerts),
                },
            )
            self.state.agents["gpu_thermal"].tool_calls = [{"tool": t} for t in tool_log]
            return self._format_report(gpus, score, label, alerts, task)

    # ──────────────────────────────────────────────
    # NVML Query (primary)
    # ──────────────────────────────────────────────

    def _query_nvml(self) -> List[Dict]:
        try:
            import pynvml
            count = pynvml.nvmlDeviceGetCount()
            gpus  = []
            for i in range(count):
                h    = pynvml.nvmlDeviceGetHandleByIndex(i)
                name = pynvml.nvmlDeviceGetName(h)
                if isinstance(name, bytes):
                    name = name.decode()
                mem   = pynvml.nvmlDeviceGetMemoryInfo(h)
                temp  = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
                util  = pynvml.nvmlDeviceGetUtilizationRates(h)
                try:
                    power_w = pynvml.nvmlDeviceGetPowerUsage(h) / 1000
                except Exception:
                    power_w = -1
                gpus.append({
                    "index":     i,
                    "name":      name,
                    "temp_c":    temp,
                    "vram_used_mb":  round(mem.used  / 1e6, 1),
                    "vram_total_mb": round(mem.total / 1e6, 1),
                    "vram_pct":  round(mem.used / mem.total * 100, 1),
                    "gpu_util":  util.gpu,
                    "mem_util":  util.memory,
                    "power_w":   round(power_w, 1),
                })
            return gpus
        except Exception as exc:
            logger.warning(f"GPUAgent: nvml query failed: {exc}")
            return []

    # ──────────────────────────────────────────────
    # nvidia-smi Fallback
    # ──────────────────────────────────────────────

    def _query_smi(self) -> List[Dict]:
        try:
            cmd = (
                "nvidia-smi --query-gpu=index,name,temperature.gpu,memory.used,"
                "memory.total,utilization.gpu,utilization.memory,power.draw "
                "--format=csv,noheader,nounits"
            )
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
            if result.returncode != 0:
                return []
            gpus = []
            for line in result.stdout.strip().splitlines():
                p = [x.strip() for x in line.split(",")]
                if len(p) < 8:
                    continue
                vram_used  = float(p[3]) if p[3] != "[N/A]" else 0
                vram_total = float(p[4]) if p[4] != "[N/A]" else 1
                gpus.append({
                    "index":         int(p[0]),
                    "name":          p[1],
                    "temp_c":        float(p[2]) if p[2] != "[N/A]" else -1,
                    "vram_used_mb":  vram_used,
                    "vram_total_mb": vram_total,
                    "vram_pct":      round(vram_used / vram_total * 100, 1),
                    "gpu_util":      float(p[5]) if p[5] != "[N/A]" else -1,
                    "mem_util":      float(p[6]) if p[6] != "[N/A]" else -1,
                    "power_w":       float(p[7]) if p[7] != "[N/A]" else -1,
                })
            return gpus
        except Exception as exc:
            logger.warning(f"GPUAgent: nvidia-smi failed: {exc}")
            return []

    # ──────────────────────────────────────────────
    # Analysis
    # ──────────────────────────────────────────────

    def _find_alerts(self, gpus: List[Dict]) -> List[str]:
        alerts = []
        for g in gpus:
            if g["temp_c"] >= TEMP_CRIT:
                alerts.append(f"🚨 GPU {g['index']} ({g['name']}): CRITICAL TEMP {g['temp_c']}°C — risk of thermal shutdown!")
            elif g["temp_c"] >= TEMP_WARN:
                alerts.append(f"⚠️ GPU {g['index']} ({g['name']}): HIGH TEMP {g['temp_c']}°C — consider improving airflow")
            if g["vram_pct"] >= VRAM_WARN:
                alerts.append(f"⚠️ GPU {g['index']}: VRAM {g['vram_pct']}% full — reduce model batch size or quantization level")
            if g["gpu_util"] >= UTIL_WARN:
                alerts.append(f"⚠️ GPU {g['index']}: GPU util {g['gpu_util']}% — at capacity, inference may slow")
        return alerts

    @staticmethod
    def _health_score(gpus: List[Dict]) -> Tuple[int, str]:
        score = 100
        for g in gpus:
            t = g.get("temp_c", 0)
            v = g.get("vram_pct", 0)
            if t >= TEMP_CRIT:  score -= 40
            elif t >= TEMP_WARN: score -= 20
            if v >= 95:          score -= 30
            elif v >= VRAM_WARN: score -= 15
        score = max(0, min(100, score))
        if score >= 80: label = "🟢 HEALTHY"
        elif score >= 50: label = "🟡 WARM"
        else:             label = "🔴 CRITICAL"
        return score, label

    # ──────────────────────────────────────────────
    # Reports
    # ──────────────────────────────────────────────

    def _format_report(self, gpus, score, label, alerts, task) -> str:
        gpu_rows = "\n".join(
            f"  GPU {g['index']}: {g['name']}\n"
            f"    Temp     : {g['temp_c']}°C  {'🔴 HOT' if g['temp_c'] >= TEMP_WARN else '✅'}\n"
            f"    VRAM     : {g['vram_used_mb']:.0f}MB / {g['vram_total_mb']:.0f}MB ({g['vram_pct']}%)\n"
            f"    GPU Util : {g['gpu_util']}%\n"
            f"    Power    : {g['power_w']}W"
            for g in gpus
        )
        alert_lines = "\n".join(f"  {a}" for a in alerts) or "  ✅ No thermal alerts"
        return f"""## 🌡️ GPU / Thermal Agent Report

**Task**: {task or "GPU health check"}
**Score**: {score}/100  {label}

### GPU Status
{gpu_rows}

### Thermal Alerts
{alert_lines}

### Sovereign AI Inference Guidance
{"✅ GPU is ready for local LLM inference (Gemma 4 / Ollama)." if score >= 80 else "⚠️ Thermal pressure detected. Reduce batch size or enable power limit cap before running LLM inference." if score >= 50 else "🚨 GPU overheating. Stop inference workloads immediately and improve cooling."}
"""

    def _no_gpu_report(self, task) -> str:
        return f"""## 🌡️ GPU / Thermal Agent Report

**Task**: {task or "GPU health check"}

ℹ️ **No NVIDIA GPU detected** — system is in CPU-only mode.

### Inference Recommendation
For running Gemma 4 locally, consider:
  • NVIDIA RTX 3060 (12GB VRAM) — minimum for 7B models
  • NVIDIA RTX 4090 (24GB VRAM) — recommended for 13B+ models
  • Secondary-market Blackwell/Ada GPUs from refurb suppliers

CPU-only inference via Ollama (llama.cpp) is possible but ~10x slower.
"""
