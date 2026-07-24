import json
import time
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from seleniumbase import Driver

from ..registry import ActionTriggerMeta, action, trigger
from ..stats_logger import VideoStatsLogger


def _xpath_literal(value: str) -> str:
    """Return an XPath string literal for values that may contain quotes."""
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    return "concat(" + ", '\"', ".join(f"'{part}'" for part in value.split('"')) + ")"


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


class BaseController(ABC, metaclass=ActionTriggerMeta):
    """Base controller with automatic action and trigger registration via combined metaclass."""
    
    def __init__(self, driver: Driver):
        self.driver = driver
        self.stats_logger = VideoStatsLogger(driver)
        self._tabs: dict[str, str] = {}
        self._variables: dict[str, str] = {}
        self._webrtc_tracking_source: str | None = None

    @action()
    def navigate(self, url: str):
        """Navigate to a specified URL"""
        self.driver.get(url)

    @action()
    def remember_tab(self, name: str):
        """Remember the current browser tab by name."""
        self._tabs[name] = self.driver.current_window_handle
        return name

    @action()
    def switch_tab(self, name: str):
        """Switch to a browser tab previously saved with remember_tab."""
        handle = self._tabs.get(name)
        if handle is None or handle not in self.driver.window_handles:
            raise ValueError(f"Remembered tab is unavailable: {name}")
        self.driver.switch_to.window(handle)
        return name

    @action()
    def store_current_url(self, name: str, strip_query: bool = False):
        """Store the current URL for a later action in the same workflow."""
        value = self.driver.current_url
        if strip_query:
            parsed = urlsplit(value)
            value = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        self._variables[name] = value
        return value

    @action()
    def open_stored_url(
        self,
        name: str,
        suffix: str = "",
        tab_name: str | None = None,
    ):
        """Open a URL saved by store_current_url in a new named tab."""
        value = self._variables.get(name)
        if value is None:
            raise ValueError(f"Stored URL is unavailable: {name}")
        self.driver.switch_to.new_window("tab")
        if tab_name:
            self._tabs[tab_name] = self.driver.current_window_handle
        if self._webrtc_tracking_source:
            self._install_webrtc_tracking()
        self.driver.get(f"{value}{suffix}")
        return self.driver.current_url

    @action()
    def click_first_text(
        self,
        texts: list[str] | str,
        timeout: float = 10,
    ):
        """Click the first visible button-like element matching one of the texts."""
        last_error = None
        for text in _as_list(texts):
            literal = _xpath_literal(text.strip())
            selector = (
                "//*[self::button or @role='button']"
                f"[normalize-space(.)={literal}]"
            )
            try:
                element = WebDriverWait(self.driver, timeout).until(
                    EC.element_to_be_clickable((By.XPATH, selector))
                )
                try:
                    element.click()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", element)
                return text
            except Exception as exc:
                last_error = exc
        raise ValueError(f"No clickable text matched: {last_error}")

    @action()
    def click_accessible_name(
        self,
        names: list[str] | str,
        timeout: float = 10,
    ):
        """Click the first visible button with a matching accessible name."""
        expected = {name.strip() for name in _as_list(names)}

        def find_match(driver):
            for element in driver.find_elements(
                By.CSS_SELECTOR,
                "button, [role='button']",
            ):
                try:
                    if (
                        element.is_displayed()
                        and element.is_enabled()
                        and element.accessible_name.strip() in expected
                    ):
                        return element
                except Exception:
                    continue
            return False

        element = WebDriverWait(self.driver, timeout).until(find_match)
        selected_name = element.accessible_name.strip()
        try:
            element.click()
        except Exception:
            self.driver.execute_script("arguments[0].click();", element)
        return selected_name

    @action()
    def wait_for_element(
        self,
        selector: str,
        visible: bool = True,
        timeout: float = 30,
    ):
        """Wait until a CSS selector is visible or hidden."""
        condition = EC.visibility_of_element_located((By.CSS_SELECTOR, selector))
        waiter = WebDriverWait(self.driver, timeout)
        if visible:
            waiter.until(condition)
        else:
            waiter.until_not(condition)
        return visible

    @action()
    def wait_for_text(
        self,
        text: str,
        visible: bool = True,
        timeout: float = 30,
    ):
        """Wait until exact visible text is present or absent."""
        literal = _xpath_literal(text.strip())
        condition = EC.visibility_of_element_located(
            (By.XPATH, f"//*[normalize-space(.)={literal}]")
        )
        waiter = WebDriverWait(self.driver, timeout)
        if visible:
            waiter.until(condition)
        else:
            waiter.until_not(condition)
        return visible

    @action()
    def start_webrtc_tracking(self):
        """Track peer connections created by subsequently loaded pages."""
        self._webrtc_tracking_source = """
        (() => {
            if (window.__netgentPeerConnections || !window.RTCPeerConnection) return;
            const connections = [];
            const NativeRTCPeerConnection = window.RTCPeerConnection;
            function TrackedRTCPeerConnection(...args) {
                const connection = new NativeRTCPeerConnection(...args);
                connections.push(connection);
                return connection;
            }
            TrackedRTCPeerConnection.prototype = NativeRTCPeerConnection.prototype;
            Object.setPrototypeOf(TrackedRTCPeerConnection, NativeRTCPeerConnection);
            window.RTCPeerConnection = TrackedRTCPeerConnection;
            Object.defineProperty(window, "__netgentPeerConnections", {
                value: connections,
                configurable: false,
            });
        })();
        """
        self._install_webrtc_tracking()

    def _install_webrtc_tracking(self):
        source = self._webrtc_tracking_source
        if source is None:
            return
        self.driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": source},
        )
        self.driver.execute_script(source)

    @action()
    def collect_webrtc_metrics(self, out_path: str):
        """Write resource and WebRTC totals for each tab in the active meeting."""
        meeting_url = self._variables.get("meeting_url", self.driver.current_url)
        meeting_path = urlsplit(meeting_url).path
        original_handle = self.driver.current_window_handle
        pages = []
        script = """
        const done = arguments[arguments.length - 1];
        (async () => {
            const resources = performance.getEntriesByType("resource");
            const aggregate = {
                connection_count: 0,
                bytes_received: 0,
                bytes_sent: 0,
                packets_received: 0,
                packets_sent: 0,
                packets_lost: 0,
                frames_decoded: 0,
                frames_encoded: 0,
                jitter_seconds_max: 0,
                connection_states: [],
            };
            const connections = window.__netgentPeerConnections || [];
            aggregate.connection_count = connections.length;
            for (const connection of connections) {
                aggregate.connection_states.push(connection.connectionState);
                const report = await connection.getStats();
                report.forEach((stat) => {
                    aggregate.bytes_received += Number(stat.bytesReceived || 0);
                    aggregate.bytes_sent += Number(stat.bytesSent || 0);
                    aggregate.packets_received += Number(stat.packetsReceived || 0);
                    aggregate.packets_sent += Number(stat.packetsSent || 0);
                    aggregate.packets_lost += Number(stat.packetsLost || 0);
                    aggregate.frames_decoded += Number(stat.framesDecoded || 0);
                    aggregate.frames_encoded += Number(stat.framesEncoded || 0);
                    aggregate.jitter_seconds_max = Math.max(
                        aggregate.jitter_seconds_max,
                        Number(stat.jitter || 0)
                    );
                });
            }
            done({
                url: window.location.href,
                title: document.title,
                resources: {
                    count: resources.length,
                    transfer_bytes: resources.reduce(
                        (total, item) => total + Number(item.transferSize || 0), 0
                    ),
                    decoded_body_bytes: resources.reduce(
                        (total, item) => total + Number(item.decodedBodySize || 0), 0
                    ),
                },
                webrtc: aggregate,
            });
        })().catch((error) => done({error: String(error)}));
        """

        try:
            for handle in self.driver.window_handles:
                self.driver.switch_to.window(handle)
                current = urlsplit(self.driver.current_url)
                if current.hostname != "meet.google.com" or current.path != meeting_path:
                    continue
                pages.append(self.driver.execute_async_script(script))
        finally:
            self.driver.switch_to.window(original_handle)

        metrics = {"page_count": len(pages), "pages": pages}
        output = Path(out_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
        return metrics

    @action()
    def start_stats_logging(self, out_path: str = "netgent_video_stats.jsonl", interval: float = 2.0):
        """Start logging video 'Stats for Nerds' metrics (YouTube/Twitch) to a JSONL file in the background.

        Args:
            out_path: File to append JSONL stats samples to
            interval: Seconds between samples
        """
        self.stats_logger.configure(out_path=out_path, interval=interval)
        self.stats_logger.start()
        return out_path

    @action()
    def stop_stats_logging(self):
        """Stop the background video stats logger and flush the log file."""
        self.stats_logger.stop()

    @action()
    def wait(self, seconds: float):
        """Wait for a specified number of seconds"""
        time.sleep(seconds)
    
    @action()
    def terminate(self, reason: str = "Task completed"):
        """Terminate the agent execution"""
        print(f"TERMINATING: {reason}")
        return reason
    
    def quit(self):
        """Quit the browser (not an action - used for cleanup)"""
        if self.stats_logger:
            self.stats_logger.stop()
        if self.driver:
            self.driver.quit()

    # -- Actions Methods --
    @abstractmethod
    @action()
    def click(self, by: str = None, selector: str = None, x: float = None, y: float = None, percentage: float = 0.5):
        """Click on a specified element or coordinates.
        
        Args:
            by: Locator strategy (optional)
            selector: Selector string (optional)
            x: X coordinate (optional, used if by/selector not provided or fails)
            y: Y coordinate (optional, used if by/selector not provided or fails)
            percentage: Percentage of the element to click (0.0 to 1.0) for the x coordinate
        """
        pass

    @abstractmethod
    @action(name="type")  # Custom name to match common JSON schema naming
    def type_text(self, text: str, by: str = None, selector: str = None, x: float = None, y: float = None):
        """Type text into a specified element or at coordinates.
        
        Args:
            text: Text to type
            by: Locator strategy (optional)
            selector: Selector string (optional)
            x: X coordinate (optional, used if by/selector not provided or fails)
            y: Y coordinate (optional, used if by/selector not provided or fails)
        """
        pass
    
    @abstractmethod
    @action()
    def scroll_to(self, by: str = None, selector: str = None, x: float = None, y: float = None):
        """Scroll to a specified element or coordinates.
        
        Args:
            by: Locator strategy (optional)
            selector: Selector string (optional)
            x: X coordinate (optional, used if by/selector not provided or fails)
            y: Y coordinate (optional, used if by/selector not provided or fails)
        """
        pass
    
    @abstractmethod
    @action()
    def scroll(self, pixels: int, direction: str, by: str = None, selector: str = None, x: float = None, y: float = None):
        """Scroll a specified number of pixels in a specified direction.
        
        Args:
            pixels: Number of pixels to scroll
            direction: Direction to scroll ("up" or "down")
            by: Locator strategy (optional)
            selector: Selector string (optional)
            x: X coordinate (optional, used if by/selector not provided or fails)
            y: Y coordinate (optional, used if by/selector not provided or fails)
        """
        pass
    
    @abstractmethod
    @action()
    def press_key(self, key: str):
        """Press a specified key"""
        pass

    @abstractmethod
    @action()
    def move(self, by: str = None, selector: str = None, x: float = None, y: float = None, percentage: float = 0.5):
        """Move to a specified element or coordinates.
        
        Args:
            by: Locator strategy (optional)
            selector: Selector string (optional)
            x: X coordinate (optional, used if by/selector not provided or fails)
            y: Y coordinate (optional, used if by/selector not provided or fails)
            percentage: Percentage of the element to move to (0.0 to 1.0) for the x coordinate
        """
        pass

    def is_element_visible_in_viewpoint(self, element) -> bool:
        return self.driver.execute_script("""
    const elem = arguments[0];
    const style = window.getComputedStyle(elem);
    const rect = elem.getBoundingClientRect();

    const isVisible = (
        style.display !== 'none' &&
        style.visibility !== 'hidden' &&
        style.opacity !== '0'
    );

    const isInViewport = (
        rect.top >= 0 &&
        rect.left >= 0 &&
        rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
        rect.right <= (window.innerWidth || document.documentElement.clientWidth)
    );

    return isVisible && isInViewport;
""", element)

    # -- Trigger Methods --
    @trigger(name="element")
    def check_element(self, by: str, selector: str, check_visibility: bool = True, timeout: float = 0.1) -> bool:
        """Check if an element exists and optionally if it's visible."""
        try:
            element = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, selector))
            )
            if check_visibility:
                return self.is_element_visible_in_viewpoint(element)
            return True
        except Exception:
            return False
    
    @trigger(name="url")
    def check_url(self, url: str) -> bool:
        """Check if the current URL matches the given URL."""
        try:
            return self.driver.current_url == url
        except Exception:
            return False

    @trigger(name="text")
    def check_text(self, text: str, check_visibility: bool = True, timeout: float = 0.1) -> bool:
        """Check if text exists on the page and optionally if it's visible."""
        try:
            element = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, f"//*[normalize-space(text())='{text}']"))
            )
            if check_visibility:
                return self.is_element_visible_in_viewpoint(element)
            return True
        except Exception:
            return False

    
    def get_element_coordinates(self, x, y, width, height, percentage=0.5):
        """
        Get the absolute screen coordinates for an element.
        
        Args:
            element: Selenium WebElement
            percentage: Horizontal offset percentage within the element (0.0 to 1.0)
            
        Returns:
            tuple: (abs_x, abs_y) absolute screen coordinates
        """
        # Get element coordinates relative to the document
        element_x = x
        element_y = y

        # Get current scroll position
        scroll_x = self.driver.execute_cdp_cmd("Runtime.evaluate", {"expression": "window.pageXOffset || document.documentElement.scrollLeft", "returnByValue": True})["result"]["value"]
        scroll_y = self.driver.execute_cdp_cmd("Runtime.evaluate", {"expression": "window.pageYOffset || document.documentElement.scrollTop", "returnByValue": True})["result"]["value"]

        # Get browser window position and panel dimensions
        panel_height = self.driver.execute_cdp_cmd("Runtime.evaluate", {"expression": "window.outerHeight - window.innerHeight", "returnByValue": True})["result"]["value"]
        panel_width = self.driver.execute_cdp_cmd("Runtime.evaluate", {"expression": "window.outerWidth - window.innerWidth", "returnByValue": True})["result"]["value"]
        
        window_pos = self.driver.get_window_position()
        window_x = window_pos['x']
        window_y = window_pos['y']

        # Calculate coordinates relative to the viewport (subtract scroll position)
        viewport_x = element_x - scroll_x
        viewport_y = element_y - scroll_y

        # Calculate absolute screen coordinates (account for both horizontal and vertical panels)
        abs_x = window_x + viewport_x + panel_width
        abs_y = window_y + viewport_y + panel_height

        abs_x += width * percentage
        abs_y += height * 0.5
        
        return abs_x, abs_y
    
