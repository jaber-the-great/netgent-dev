"""
Traffic shaping via tc/netem for controlled network experiments.

Applies bandwidth limits and latency/loss to the container's egress
interface using tc-htb (rate limiting) and tc-netem (delay, loss).
Only the outbound path is shaped — this is sufficient for testing
application-layer adaptive behaviour (ABR resolution drops, rebuffering)
because the application's TCP receive window and request pacing react to
the shaped egress ACKs and requests.

Requires:
  - iproute2 installed in the container (provides `tc`)
  - NET_ADMIN capability (Docker --cap-add=NET_ADMIN or --privileged)
"""

import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)


def _run(cmd: list[str], check: bool = True) -> str:
    logger.info("tc: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 and check:
        raise RuntimeError(
            f"tc command failed (exit {result.returncode}): "
            f"{' '.join(cmd)}\nstderr: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _detect_interface() -> str:
    """Find the default egress interface from the routing table."""
    ip = shutil.which("ip")
    if ip is None:
        raise FileNotFoundError("ip command not found; install iproute2")
    result = subprocess.run(
        [ip, "route", "show", "default"],
        capture_output=True, text=True,
    )
    for token in result.stdout.split():
        if token.startswith("eth") or token.startswith("enp") or token.startswith("ens"):
            return token
    parts = result.stdout.split()
    if "dev" in parts:
        return parts[parts.index("dev") + 1]
    return "eth0"


class TrafficShaper:
    """Apply and remove tc/netem traffic shaping rules."""

    def __init__(self):
        self._active = False
        self._interface: str | None = None

    @property
    def active(self) -> bool:
        return self._active

    def apply(
        self,
        rate_mbps: float,
        delay_ms: float = 0,
        loss_pct: float = 0,
        interface: str | None = None,
    ):
        """Apply bandwidth cap + optional latency/loss.

        Args:
            rate_mbps: Bandwidth cap in Mbps (e.g. 5.0 = 5 Mbps)
            delay_ms: One-way added latency in ms (RTT impact is 2x)
            loss_pct: Random packet loss percentage (0-100)
            interface: Network interface (auto-detected if omitted)
        """
        tc = shutil.which("tc")
        if tc is None:
            raise FileNotFoundError(
                "tc not found. Install iproute2 and ensure NET_ADMIN capability."
            )

        if self._active:
            self.remove()

        iface = interface or _detect_interface()
        self._interface = iface

        rate_kbit = int(rate_mbps * 1000)
        burst = max(rate_kbit // 8, 15)  # in kbytes, minimum 15k

        _run([tc, "qdisc", "add", "dev", iface, "root", "handle", "1:",
              "htb", "default", "10"])
        _run([tc, "class", "add", "dev", iface, "parent", "1:",
              "classid", "1:10", "htb",
              "rate", f"{rate_kbit}kbit",
              "burst", f"{burst}k"])

        if delay_ms > 0 or loss_pct > 0:
            netem_args = [tc, "qdisc", "add", "dev", iface,
                          "parent", "1:10", "handle", "10:", "netem"]
            if delay_ms > 0:
                netem_args += ["delay", f"{delay_ms}ms"]
            if loss_pct > 0:
                netem_args += ["loss", f"{loss_pct}%"]
            _run(netem_args)

        self._active = True
        logger.info(
            "Traffic shaping applied: %s Mbps, %s ms delay, %s%% loss on %s",
            rate_mbps, delay_ms, loss_pct, iface,
        )

    def remove(self):
        """Remove all tc rules from the interface."""
        if not self._active or not self._interface:
            logger.info("No traffic shaping active; nothing to remove")
            return

        tc = shutil.which("tc")
        if tc is None:
            return

        _run([tc, "qdisc", "del", "dev", self._interface, "root"],
             check=False)
        self._active = False
        logger.info("Traffic shaping removed from %s", self._interface)
