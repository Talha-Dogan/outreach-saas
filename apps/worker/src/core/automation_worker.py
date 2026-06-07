from __future__ import annotations
import asyncio
import json
import logging
import random
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, AsyncGenerator, Optional
import redis.asyncio as aioredis
from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright
from core.browser_lifecycle import BrowserLifecycleMixin

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(name)s | %(levelname)s | %(message)s")

class TaskStatus(Enum):
    PENDING = auto()
    RUNNING = auto()
    SUCCESS = auto()
    FAILED = auto()
    RATE_LIMITED = auto()
    RETRY = auto()

@dataclass(frozen=True)
class ProxyConfig:
    server: str
    username: Optional[str] = None
    password: Optional[str] = None

    def to_playwright_dict(self) -> dict[str, str]:
        config: dict[str, str] = {"server": self.server}
        if self.username and self.password:
            config["username"] = self.username
            config["password"] = self.password
        return config

@dataclass
class TaskPayload:
    task_id: str
    user_id: str
    action: str
    target_url: str
    message: Optional[str] = None
    proxy: Optional[ProxyConfig] = None
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class TaskResult:
    task_id: str
    status: TaskStatus
    message: str
    screenshot: Optional[str] = None
    duration_s: float = 0.0
    error: Optional[str] = None

class HumanSimulator:
    _MICRO_DELAY_MU = 0.12
    _MICRO_DELAY_SIGMA = 0.04
    _ACTION_DELAY_MU = 2.4
    _ACTION_DELAY_SIGMA = 0.9
    _PAGE_READ_MU = 4.5
    _PAGE_READ_SIGMA = 1.8
    _SCROLL_PAUSE_MU = 0.8
    _SCROLL_PAUSE_SIGMA = 0.25
    _MIN_TYPING_SPEED = 3.5
    _MAX_TYPING_SPEED = 7.2

    @staticmethod
    def _gaussian_delay(mu: float, sigma: float, min_val: float = 0.05) -> float:
        return max(min_val, random.gauss(mu, sigma))

    @classmethod
    async def micro_pause(cls) -> None:
        await asyncio.sleep(cls._gaussian_delay(cls._MICRO_DELAY_MU, cls._MICRO_DELAY_SIGMA))

    @classmethod
    async def action_pause(cls) -> None:
        if random.random() < 0.15:
            await asyncio.sleep(random.uniform(5.0, 12.0))
            return
        await asyncio.sleep(cls._gaussian_delay(cls._ACTION_DELAY_MU, cls._ACTION_DELAY_SIGMA))

    @classmethod
    async def reading_pause(cls) -> None:
        await asyncio.sleep(cls._gaussian_delay(cls._PAGE_READ_MU, cls._PAGE_READ_SIGMA))

    @classmethod
    async def type_humanly(cls, page: Page, selector: str, text: str) -> None:
        await page.click(selector)
        await asyncio.sleep(cls._gaussian_delay(0.3, 0.1))
        chars_per_second = random.uniform(cls._MIN_TYPING_SPEED, cls._MAX_TYPING_SPEED)
        base_delay = 1.0 / chars_per_second
        for char in text:
            await page.keyboard.type(char)
            char_delay = max(0.03, random.gauss(base_delay, base_delay * 0.25))
            await asyncio.sleep(char_delay)

    @classmethod
    async def scroll_naturally(cls, page: Page, total_distance: int = 800) -> None:
        num_steps = random.randint(4, 8)
        remaining = total_distance
        for i in range(num_steps):
            if i == num_steps - 1:
                step = remaining
            else:
                step = random.randint(int(remaining * 0.1), int(remaining * 0.4))
                remaining -= step
            await page.mouse.wheel(0, step)
            await asyncio.sleep(cls._gaussian_delay(cls._SCROLL_PAUSE_MU, cls._SCROLL_PAUSE_SIGMA))

    @staticmethod
    async def move_mouse_randomly(page: Page) -> None:
        viewport = page.viewport_size or {"width": 1280, "height": 800}
        for _ in range(random.randint(2, 5)):
            target_x = random.randint(100, viewport["width"] - 100)
            target_y = random.randint(100, viewport["height"] - 100)
            steps = random.randint(8, 20)
            current = await page.evaluate("() => ({ x: window.mouseX || 640, y: window.mouseY || 400 })")
            for step in range(steps):
                t = step / steps
                ease = t * t * (3 - 2 * t)
                interp_x = int(current.get("x", 640) + (target_x - current.get("x", 640)) * ease)
                interp_y = int(current.get("y", 400) + (target_y - current.get("y", 400)) * ease)
                await page.mouse.move(interp_x + random.randint(-3, 3), interp_y + random.randint(-3, 3))
                await asyncio.sleep(random.uniform(0.008, 0.025))
class BrowserFactory:
    _USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    ]
    _VIEWPORTS = [
        {"width": 1920, "height": 1080},
        {"width": 1440, "height": 900},
        {"width": 1366, "height": 768},
        {"width": 1536, "height": 864},
    ]
    _LOCALES = ["en-US", "en-GB", "en-CA"]
    _TIMEZONES = ["America/New_York", "America/Chicago", "Europe/London"]

    @classmethod
    async def create_stealth_context(cls, browser: Browser, proxy: Optional[ProxyConfig] = None, cookies: Optional[list[dict]] = None) -> BrowserContext:
        context_options: dict[str, Any] = {
            "user_agent": random.choice(cls._USER_AGENTS),
            "viewport": random.choice(cls._VIEWPORTS),
            "locale": random.choice(cls._LOCALES),
            "timezone_id": random.choice(cls._TIMEZONES),
            "color_scheme": random.choice(["light", "dark"]),
            "java_script_enabled": True,
            "accept_downloads": False,
            "extra_http_headers": {
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "sec-ch-ua-platform": random.choice(['"Windows"', '"macOS"', '"Linux"']),
            },
        }
        if proxy:
            context_options["proxy"] = proxy.to_playwright_dict()
        context = await browser.new_context(**context_options)
        await context.add_init_script(cls._get_stealth_init_script())
        if cookies:
            await context.add_cookies(cookies)
        return context

    @staticmethod
    def _get_stealth_init_script() -> str:
        return """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined, configurable: true });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'], configurable: true });
            if (!window.chrome) { window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} }; }
            Object.defineProperty(navigator, 'plugins', { get: () => [{ name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' }], configurable: true });
        """

class SessionManager:
    _SESSION_KEY_PREFIX = "session"
    _SESSION_TTL_SECONDS = 86_400

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    def _session_key(self, user_id: str) -> str:
        return f"{self._SESSION_KEY_PREFIX}:{user_id}"

    async def load(self, user_id: str) -> Optional[list[dict]]:
        raw = await self._redis.get(self._session_key(user_id))
        if raw is None:
            return None
        return json.loads(raw)

    async def save(self, user_id: str, cookies: list[dict]) -> None:
        await self._redis.setex(name=self._session_key(user_id), time=self._SESSION_TTL_SECONDS, value=json.dumps(cookies))

    async def invalidate(self, user_id: str) -> None:
        await self._redis.delete(self._session_key(user_id))

class RateLimiter:
    _RATE_KEY_PREFIX = "rate"
    _WINDOW_SECONDS = 86_400

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    def _rate_key(self, user_id: str) -> str:
        return f"{self._RATE_KEY_PREFIX}:{user_id}"

    async def check_and_increment(self, user_id: str, daily_limit: int) -> tuple[bool, int]:
        lua_script = """
            local key = KEYS[1]
            local limit = tonumber(ARGV[1])
            local window = tonumber(ARGV[2])
            local current = redis.call('GET', key)
            if current == false then
                redis.call('SET', key, 1, 'EX', window)
                return {1, 1}
            end
            current = tonumber(current)
            if current >= limit then
                return {0, current}
            end
            redis.call('INCR', key)
            return {1, current + 1}
        """
        result = await self._redis.eval(lua_script, 1, self._rate_key(user_id), daily_limit, self._WINDOW_SECONDS)
        return bool(result[0]), int(result[1])

    async def get_remaining(self, user_id: str, daily_limit: int) -> int:
        raw = await self._redis.get(self._rate_key(user_id))
        current = int(raw) if raw else 0
        return max(0, daily_limit - current)

class CoreAutomationWorker(BrowserLifecycleMixin):
    _MAX_RETRIES = 3
    _RETRY_BACKOFF_BASE = 2.0
    _CHANNEL_PREFIX = "task_updates"

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client
        self._session_manager = SessionManager(redis_client)
        self._rate_limiter = RateLimiter(redis_client)
        self._human = HumanSimulator()

    async def execute(self, payload: TaskPayload, daily_limit: int = 50) -> TaskResult:
        start_time = time.monotonic()
        allowed, count = await self._rate_limiter.check_and_increment(payload.user_id, daily_limit)
        if not allowed:
            return TaskResult(task_id=payload.task_id, status=TaskStatus.RATE_LIMITED, message=f"Daily limit of {daily_limit} actions reached.", duration_s=time.monotonic() - start_time)
        await self._publish_status(payload.task_id, TaskStatus.RUNNING, "Task started")
        last_error: Optional[Exception] = None
        for attempt in range(1, self._MAX_RETRIES + 1):
            try:
                result = await self._run_automation(payload)
                result.duration_s = time.monotonic() - start_time
                await self._publish_status(payload.task_id, result.status, result.message)
                return result
            except Exception as exc:
                last_error = exc
                backoff = self._RETRY_BACKOFF_BASE ** attempt + random.uniform(0.5, 1.5)
                logger.error("Task %s failed attempt %d/%d: %s. Retrying in %.1fs", payload.task_id, attempt, self._MAX_RETRIES, exc, backoff)
                await self._publish_status(payload.task_id, TaskStatus.RETRY, f"Attempt {attempt} failed. Retrying in {backoff:.1f}s...")
                await asyncio.sleep(backoff)
        error_msg = str(last_error) if last_error else "Unknown error"
        await self._publish_status(payload.task_id, TaskStatus.FAILED, error_msg)
        return TaskResult(task_id=payload.task_id, status=TaskStatus.FAILED, message=f"Task failed after {self._MAX_RETRIES} attempts", duration_s=time.monotonic() - start_time, error=error_msg)

    async def _run_automation(self, payload: TaskPayload) -> TaskResult:
        async with self._managed_browser_context(payload) as (page, context):
            await self._human.move_mouse_randomly(page)
            await self._human.reading_pause()
            action_handler = self._get_action_handler(payload.action)
            result = await action_handler(page, payload)
            cookies = await context.cookies()
            await self._session_manager.save(payload.user_id, cookies)
            return result

    @asynccontextmanager
    async def _managed_browser_context(self, payload: TaskPayload) -> AsyncGenerator[tuple[Page, BrowserContext], None]:
        async with async_playwright() as playwright:
            self._active_playwright = playwright
            browser = await self._launch_browser(playwright)
            self._active_browser = browser
            cookies = await self._session_manager.load(payload.user_id)
            context = await BrowserFactory.create_stealth_context(browser=browser, proxy=payload.proxy, cookies=cookies)
            page = await context.new_page()
            await self._configure_request_interception(page)
            try:
                yield page, context
            finally:
                await context.close()
                await browser.close()

    @staticmethod
    async def _launch_browser(playwright: Playwright) -> Browser:
        return await playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage", "--no-first-run", "--disable-gpu", "--hide-scrollbars", "--mute-audio"],
        )

    @staticmethod
    async def _configure_request_interception(page: Page) -> None:
        async def block_resources(route, request):
            if request.resource_type in {"image", "media", "font", "other"}:
                await route.abort()
            else:
                await route.continue_()
        await page.route("**/*", block_resources)

    def _get_action_handler(self, action: str):
        handlers = {"visit_profile": self._handle_visit_profile, "send_connection": self._handle_send_connection, "send_message": self._handle_send_message}
        handler = handlers.get(action)
        if handler is None:
            raise ValueError(f"Unknown action type: '{action}'")
        return handler

    async def _handle_visit_profile(self, page: Page, payload: TaskPayload) -> TaskResult:
        await page.goto(payload.target_url, wait_until="domcontentloaded", timeout=30_000)
        await self._human.reading_pause()
        await self._human.scroll_naturally(page, total_distance=600)
        await self._human.action_pause()
        await self._human.scroll_naturally(page, total_distance=400)
        await self._human.move_mouse_randomly(page)
        return TaskResult(task_id=payload.task_id, status=TaskStatus.SUCCESS, message=f"Successfully visited profile: {payload.target_url}")

    async def _handle_send_connection(self, page: Page, payload: TaskPayload) -> TaskResult:
        await page.goto(payload.target_url, wait_until="domcontentloaded", timeout=30_000)
        await self._human.reading_pause()
        await self._human.scroll_naturally(page, total_distance=500)
        await self._human.action_pause()
        connect_button = page.locator("button:has-text('Connect')").first
        if not await connect_button.is_visible(timeout=5_000):
            return TaskResult(task_id=payload.task_id, status=TaskStatus.FAILED, message="Connect button not found.")
        await self._human.move_mouse_randomly(page)
        await connect_button.click()
        await self._human.action_pause()
        if payload.message:
            add_note = page.locator("button:has-text('Add a note')")
            if await add_note.is_visible(timeout=3_000):
                await add_note.click()
                await self._human.action_pause()
            note_field = page.locator("textarea[name='message']")
            if await note_field.is_visible(timeout=3_000):
                await self._human.type_humanly(page, "textarea[name='message']", payload.message)
                await self._human.action_pause()
        send_button = page.locator("button:has-text('Send now'), button:has-text('Send invitation')")
        await send_button.click()
        return TaskResult(task_id=payload.task_id, status=TaskStatus.SUCCESS, message=f"Connection request sent to {payload.target_url}")

    async def _handle_send_message(self, page: Page, payload: TaskPayload) -> TaskResult:
        if not payload.message:
            return TaskResult(task_id=payload.task_id, status=TaskStatus.FAILED, message="Cannot send message: payload.message is empty")
        await page.goto(payload.target_url, wait_until="domcontentloaded", timeout=30_000)
        await self._human.reading_pause()
        message_button = page.locator("a:has-text('Message'), button:has-text('Message')").first
        await message_button.click()
        await self._human.action_pause()
        await self._human.type_humanly(page, "div[role='textbox']", payload.message)
        await self._human.action_pause()
        send_button = page.locator("button.msg-form__send-button")
        await send_button.click()
        return TaskResult(task_id=payload.task_id, status=TaskStatus.SUCCESS, message=f"Message delivered to {payload.target_url}")

    async def _publish_status(self, task_id: str, status: TaskStatus, message: str) -> None:
        channel = f"{self._CHANNEL_PREFIX}:{task_id}"
        payload_json = json.dumps({"task_id": task_id, "status": status.name, "message": message, "timestamp": time.time()})
        await self._redis.publish(channel, payload_json)
