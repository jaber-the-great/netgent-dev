"""
Background packet capture using tcpdump.

Runs tcpdump as a subprocess to capture network traffic into a PCAP file.
Designed to work alongside VideoStatsLogger so workflows can collect both
application-layer QoE metrics (when available) and network-level traffic
data (always available, essential for apps like Zoom that don't expose
browser-visible video stats).

Requires:
  - tcpdump installed in the container (added to Dockerfile)
  - NET_ADMIN capability or root privileges (Docker --cap-add=NET_ADMIN
    or --privileged)
"""

import logging
import shutil
import signal
import subprocess
import threading

logger = logging.getLogger(__name__)


class PacketCapture:
    """Start/stop a tcpdump process that writes a PCAP file."""

    def __init__(
        self,
        out_path: str = "capture.pcap",
        interface: str = "any",
        filter_expr: str = "",
        snaplen: int = 0,
    ):
        self.out_path = out_path
        self.interface = interface
        self.filter_expr = filter_expr
        self.snaplen = snaplen
        self._proc: subprocess.Popen | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr_lines: list[str] = []

    def configure(
        self,
        out_path: str | None = None,
        interface: str | None = None,
        filter_expr: str | None = None,
        snaplen: int | None = None,
    ):
        if out_path is not None:
            self.out_path = out_path
        if interface is not None:
            self.interface = interface
        if filter_expr is not None:
            self.filter_expr = filter_expr
        if snaplen is not None:
            self.snaplen = snaplen

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _drain_stderr(self):
        assert self._proc and self._proc.stderr
        for line in self._proc.stderr:
            text = line.decode("utf-8", errors="replace").rstrip()
            self._stderr_lines.append(text)
            logger.debug("tcpdump: %s", text)

    def start(self):
        if self.is_running():
            logger.info("Packet capture already running; ignoring start()")
            return

        tcpdump = shutil.which("tcpdump")
        if tcpdump is None:
            raise FileNotFoundError(
                "tcpdump not found. Install it (apt-get install tcpdump) "
                "and ensure the container has NET_ADMIN capability."
            )

        cmd = [
            tcpdump,
            "-i", self.interface,
            "-w", self.out_path,
            "-U",  # packet-buffered output
        ]
        if self.snaplen:
            cmd += ["-s", str(self.snaplen)]
        if self.filter_expr:
            cmd += self.filter_expr.split()

        logger.info("Starting packet capture: %s", " ".join(cmd))
        self._stderr_lines = []
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, daemon=True, name="tcpdump-stderr"
        )
        self._stderr_thread.start()

    def stop(self) -> str:
        """Stop the capture and return the output path."""
        if not self.is_running():
            logger.info("Packet capture not running; nothing to stop")
            return self.out_path

        self._proc.send_signal(signal.SIGTERM)
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait(timeout=5)

        if self._stderr_thread:
            self._stderr_thread.join(timeout=5)

        captured_line = next(
            (l for l in reversed(self._stderr_lines) if "packets captured" in l),
            None,
        )
        logger.info(
            "Packet capture stopped -> %s%s",
            self.out_path,
            f" ({captured_line})" if captured_line else "",
        )
        self._proc = None
        return self.out_path
