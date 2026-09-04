"""V2 UI 驱动封装：Playwright + 系统 Microsoft Edge。

为什么用 Playwright + Edge channel：
- V1 已站在 pytest 生态上（requests 打接口）；V2 要模拟真人点页面，Playwright 是成熟 UI 驱动；
- channel="msedge" 直接复用系统 Edge（用户偏好），免 `playwright install` 下载 Chromium，
  也避免再引入一套浏览器 —— 可复现、省磁盘。

本模块职责（V2 链路的「失败捕获」端）：
- 打开被测页面、截图；
- 提取页面关键结构（form/input/button/a 的 name/id/type/文本）—— 供「错误签名」做页面指纹，
  也作为 LLM/RAG 看「新页面长啥样」的上下文；
- try_locate：按选择器定位；定位失败时返回结构化失败信息（错误签名与自愈的输入）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, Playwright, sync_playwright

# 提取页面结构时关心的元素与属性
_STRUCTURE_SELECTOR = "form, input, button, a, textarea, select"
_ATTR_KEYS = ("tag", "name", "id", "type", "placeholder", "text")


def _element_brief(tag: str, loc) -> dict[str, Any]:
    """把单个元素压缩成 {tag, name, id, type, placeholder, text} 的稳定摘要。"""
    item: dict[str, Any] = {"tag": tag}
    for key in ("name", "id", "type", "placeholder"):
        value = loc.get_attribute(key)
        if value:
            item[key] = value
    if tag in ("button", "a", "textarea"):
        text = (loc.inner_text() or "").strip()
        if text:
            item["text"] = text
    return item


@dataclass
class LocateResult:
    """一次定位尝试的结果。ok=False 时 error_info 是自愈/签名的输入。"""

    ok: bool
    error_info: dict[str, Any] = field(default_factory=dict)


class UISession:
    """一个 Edge(headless) 会话：打开页面 -> 提取信息 -> 尝试定位。"""

    def __init__(self, base_url: str, *, headless: bool = True, channel: str = "msedge"):
        self.base_url = base_url.rstrip("/")
        self._pw: Playwright = sync_playwright().start()
        self._browser = self._pw.chromium.launch(channel=channel, headless=headless)
        self._page: Page | None = None

    def open(self, path: str, *, timeout_ms: int = 20000) -> Page:
        """打开 base_url + path，等待网络空闲后返回 page。"""
        return self.open_url(f"{self.base_url}/{path.lstrip('/')}", timeout_ms=timeout_ms)

    def open_url(self, url: str, *, timeout_ms: int = 20000) -> Page:
        """直接打开完整 URL（不依赖 base_url，供 heal 从失败样本的 page_url 恢复现场）。"""
        page = self._browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        self._page = page
        return page

    def page_title(self) -> str:
        return self._page.title() if self._page else ""

    def structure(self) -> list[dict[str, Any]]:
        """提取页面关键元素结构（顺序即 DOM 顺序；签名层会做顺序无关归一化）。"""
        if self._page is None:
            return []
        briefs: list[dict[str, Any]] = []
        for loc in self._page.locator(_STRUCTURE_SELECTOR).all():
            tag = loc.evaluate("el => el.tagName.toLowerCase()")
            briefs.append(_element_brief(tag, loc))
        return briefs

    def try_locate(self, selector: str, *, timeout_ms: int = 3000) -> LocateResult:
        """按选择器定位；找不到返回结构化失败信息（error_type=locator_not_found）。"""
        if self._page is None:
            raise RuntimeError("先调用 open() 打开页面")
        loc = self._page.locator(selector)
        try:
            loc.wait_for(state="attached", timeout=timeout_ms)
        except Exception:
            return LocateResult(ok=False, error_info={
                "error_type": "locator_not_found",
                "locator": selector,
                "page_title": self.page_title(),
                "page_url": self._page.url,
                "structure": self.structure(),
            })
        return LocateResult(ok=True)

    def screenshot(self, path: str | Path) -> Path:
        if self._page is None:
            raise RuntimeError("先调用 open() 打开页面")
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._page.screenshot(path=str(target), full_page=True)
        return target

    def close(self) -> None:
        try:
            if self._browser:
                self._browser.close()
        finally:
            self._pw.stop()

    def __enter__(self) -> "UISession":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
