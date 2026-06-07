from __future__ import annotations
import logging
from typing import Optional
from playwright.async_api import Browser, Playwright

logger = logging.getLogger(__name__)

class BrowserLifecycleMixin:
    _active_browser: Optional[Browser] = None
    _active_playwright: Optional[Playwright] = None

    async def force_close(self) -> None:
        browser = self._active_browser
        playwright = self._active_playwright

        if browser is not None:
            try:
                if browser.is_connected():
                    await browser.close()
                    logger.debug("force_close: browser.close() completed")
            except Exception as exc:
                logger.warning("force_close: browser.close() raised: %s", exc)
            finally:
                self._active_browser = None

        if playwright is not None:
            try:
                await playwright.stop()
                logger.debug("force_close: playwright.stop() completed")
            except Exception as exc:
                logger.warning("force_close: playwright.stop() raised: %s", exc)
            finally:
                self._active_playwright = None
