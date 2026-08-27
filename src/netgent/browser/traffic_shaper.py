"""
Traffic shaping via tc/netem + IFB for controlled network experiments.

Shapes both ingress (download) and egress (upload) traffic:
  - Download rate limiting uses an IFB (Intermediate Functional Block)
    device: incoming packets on the real interface are redirected to ifb0,
    where tc-htb enforces the bandwidth cap and the chosen qdisc (pfifo
    or fq_codel) controls queuing behaviour.
  - Latency and packet loss are applied on the real interface's egress
    via tc-netem, which delays outgoing ACKs and requests (adding to RTT).

Requires:
  - iproute2 installed in the container (provides `tc` and `ip`)
  - kmod installed (provides `modprobe` for the ifb kernel module)
  - NET_ADMIN capability (Docker --cap-add=NET_ADMIN or --privileged)
"""

import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)

_IFB_DEV = "ifb0"


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


def _setup_ifb(iface: str):
    """Create and link IFB device to redirect ingress traffic."""
    modprobe = shutil.which("modprobe")
    ip = shutil.which("ip")
    tc = shutil.which("tc")

    if modprobe:
        subprocess.run([modprobe, "ifb"],
                       capture_output=True, check=False)

    subprocess.run([ip, "link", "add", _IFB_DEV, "type", "ifb"],
                   capture_output=True, check=False)
    subprocess.run([ip, "link", "set", _IFB_DEV, "up"],
                   capture_output=True, check=False)

    _run([tc, "qdisc", "add", "dev", iface,
          "handle", "ffff:", "ingress"], check=False)

    _run([tc, "filter", "add", "dev", iface,
          "parent", "ffff:", "protocol", "all",
          "u32", "match", "u32", "0", "0",
          "action", "mirred", "egress", "redirect", "dev", _IFB_DEV])


def _teardown_ifb(iface: str):
    """Remove IFB redirection and clean up."""
    tc = shutil.which("tc")
    ip = shutil.which("ip")
    if tc:
        _run([tc, "qdisc", "del", "dev", _IFB_DEV, "root"], check=False)
        _run([tc, "qdisc", "del", "dev", iface, "ingress"], check=False)
    if ip:
        subprocess.run([ip, "link", "set", _IFB_DEV, "down"],
                       capture_output=True, check=False)


class TrafficShaper:
    """Apply and remove tc/netem traffic shaping on both directions."""

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
        qdisc: str = "default",
        qdisc_limit: int = 50,
    ):
        """Apply download bandwidth cap + optional latency/loss + optional AQM.

        Download (ingress) rate limiting is applied via IFB device.
        Latency/loss is applied on the egress path of the real interface.

        Args:
            rate_mbps: Download bandwidth cap in Mbps (e.g. 6.0 = 6 Mbps)
            delay_ms: Added latency in ms applied to egress (affects RTT)
            loss_pct: Random packet loss percentage on egress (0-100)
            interface: Network interface (auto-detected if omitted)
            qdisc: Leaf queueing discipline on the download path —
                   "default" (no explicit leaf), "pfifo" (tail-drop FIFO),
                   or "fq_codel" (fair-queue CoDel).
            qdisc_limit: Buffer size in packets for pfifo.
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
        burst = max(rate_kbit // 8, 15)

        _setup_ifb(iface)

        _run([tc, "qdisc", "add", "dev", _IFB_DEV, "root", "handle", "1:",
              "htb", "default", "10"])
        _run([tc, "class", "add", "dev", _IFB_DEV, "parent", "1:",
              "classid", "1:10", "htb",
              "rate", f"{rate_kbit}kbit",
              "burst", f"{burst}k"])

        if qdisc == "pfifo":
            _run([tc, "qdisc", "add", "dev", _IFB_DEV,
                  "parent", "1:10", "handle", "10:",
                  "pfifo", "limit", str(qdisc_limit)])
        elif qdisc == "fq_codel":
            _run([tc, "qdisc", "add", "dev", _IFB_DEV,
                  "parent", "1:10", "handle", "10:", "fq_codel"])

        if delay_ms > 0 or loss_pct > 0:
            netem_args = [tc, "qdisc", "add", "dev", iface,
                          "root", "handle", "1:", "netem"]
            if delay_ms > 0:
                netem_args += ["delay", f"{delay_ms}ms"]
            if loss_pct > 0:
                netem_args += ["loss", f"{loss_pct}%"]
            _run(netem_args)

        self._active = True
        logger.info(
            "Traffic shaping applied: %s Mbps (ingress via %s), "
            "%s ms delay, %s%% loss, qdisc=%s on %s",
            rate_mbps, _IFB_DEV, delay_ms, loss_pct, qdisc, iface,
        )

    def remove(self):
        """Remove all tc rules from both the real interface and IFB."""
        if not self._active or not self._interface:
            logger.info("No traffic shaping active; nothing to remove")
            return

        tc = shutil.which("tc")
        if tc is None:
            return

        _run([tc, "qdisc", "del", "dev", self._interface, "root"],
             check=False)
        _teardown_ifb(self._interface)

        self._active = False
        logger.info("Traffic shaping removed from %s + %s",
                     self._interface, _IFB_DEV)
