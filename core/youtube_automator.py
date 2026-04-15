"""
Загрузка Shorts в YouTube через Playwright + CDP (подключение к браузеру AdsPower).

Интерфейс YouTube меняется; используются несколько запасных селекторов.
Любая ошибка — словарь с понятным русским текстом, без traceback в UI.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Папка для скриншотов при запросе верификации Google (для пользователя).
_DEFAULT_SHOT_DIR = Path(__file__).resolve().parent.parent / "data" / "screenshots"

_VERIFY_MARKERS = (
    "verify it's you",
    "verify it is you",
    "confirm it’s you",
    "подтвердите, что это вы",
    "본인 확인",
    "본인 인증",
)


def _error(message: str, error_type: str = "unknown_error") -> dict[str, str]:
    return {"status": "error", "message": message, "error_type": error_type}


def _ok(data: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "ok"}
    if data:
        out.update(data)
    return out


def _typing_delay() -> int:
    return random.randint(50, 120)


async def _human_type(locator, text: str) -> None:
    """Ввод текста с задержками между символами (как у человека)."""
    try:
        await locator.click(timeout=15_000)
        await asyncio.sleep(0)  # уступить event loop
        await locator.press("Control+a")
        await locator.press("Backspace")
        await locator.type(text, delay=_typing_delay())
    except Exception as exc:
        logger.warning("_human_type fallback: %s", exc)
        # Fallback должен всё равно оставить требуемый текст в поле.
        await locator.fill(text)


async def _page_text_lower(page) -> str:
    try:
        t = await page.content()
        return t.lower()
    except Exception:
        return ""


async def _detect_verification(page) -> bool:
    body = await _page_text_lower(page)
    return any(m in body for m in _VERIFY_MARKERS)


async def _screenshot_verification(page, shot_dir: Path) -> str | None:
    try:
        shot_dir.mkdir(parents=True, exist_ok=True)
        name = datetime.now().strftime("verify_%Y%m%d_%H%M%S.png")
        path = shot_dir / name
        await page.screenshot(path=str(path), full_page=True)
        return str(path.resolve())
    except Exception as exc:
        logger.exception("screenshot: %s", exc)
        return None


async def _pick_work_page(context) -> Any:
    """Страница для работы: первая открытая или новая вкладка."""
    try:
        if context.pages:
            return context.pages[0]
        return await context.new_page()
    except Exception:
        return await context.new_page()


async def _wait_publish_confirmation(page, timeout_sec: int = 45) -> tuple[bool, str]:
    """
    Дожидаемся сигналов, что publish-flow завершился.
    URL в модалке не используем как главный критерий.
    """
    success_markers = (
        "video published",
        "опубликовано",
        "опубликовали",
        "checks complete",
        "проверки завершены",
    )
    error_markers = (
        "daily upload limit",
        "лимит загрузок",
        "copyright claim",
        "нарушает правила",
        "upload failed",
    )
    for _ in range(timeout_sec):
        body = await _page_text_lower(page)
        if any(m in body for m in error_markers):
            return False, "publish_rejected"
        if any(m in body for m in success_markers):
            return True, "publish_confirmed"
        try:
            done = page.locator("#close-button, #done-button, ytcp-button#done-button button").first
            if await done.count() > 0 and await done.is_visible():
                return True, "dialog_closed_or_ready"
        except Exception:
            pass
        await asyncio.sleep(1)
    return False, "publish_timeout"


async def upload_and_publish(
    ws_endpoint: str,
    video_path: str | Path,
    title: str,
    description: str,
    comment: str | None = None,
    screenshot_dir: str | Path | None = None,
    tags: list[str] | None = None,
    thumbnail_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Подключение по CDP → studio/upload → файл → заголовок/описание → Next ×3
    → публично → Опубликовать → URL. Опционально: комментарий, закрепление,
    хэштеги (дописываются к описанию), кастомный thumbnail.

    При окне «Verify it's you» — скриншот, закрытие браузера Playwright,
    возврат ошибки с русским текстом.
    """
    vp = Path(video_path)
    if not vp.is_file():
        return _error("Видеофайл для загрузки не найден.", "file_not_found")

    # Формируем финальное описание: оригинал + хэштеги в конце
    final_description = description or ""
    if tags:
        clean_tags = [t.strip().lstrip("#") for t in tags if t.strip()]
        if clean_tags:
            hashtag_line = " ".join(f"#{t}" for t in clean_tags[:30])
            final_description = f"{final_description}\n\n{hashtag_line}".strip()

    thumb_path: Path | None = None
    if thumbnail_path:
        tp = Path(thumbnail_path)
        if tp.is_file():
            thumb_path = tp
        else:
            logger.warning("upload_and_publish: thumbnail не найден: %s", thumbnail_path)

    shot_dir = Path(screenshot_dir) if screenshot_dir else _DEFAULT_SHOT_DIR
    own_browser = None
    playwright = None

    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        logger.exception("playwright import: %s", exc)
        return _error("Не установлен Playwright. Выполните: pip install playwright && playwright install chromium", "playwright_missing")

    try:
        playwright = await async_playwright().start()
        own_browser = await playwright.chromium.connect_over_cdp(ws_endpoint)
    except Exception as exc:
        logger.exception("upload_and_publish connect: %s", exc)
        try:
            if own_browser:
                await own_browser.close()
        except Exception:
            pass
        try:
            if playwright:
                await playwright.stop()
        except Exception:
            pass
        return _error("Не удалось подключиться к браузеру AdsPower. Проверьте, что профиль запущен.", "cdp_connect_failed")

    # После успешного подключения — try/finally гарантирует закрытие браузера на всех путях выхода.
    try:
        if not own_browser.contexts:
            return _error("Не удалось открыть окно браузера. Запустите профиль в AdsPower снова.", "no_browser_context")

        context = own_browser.contexts[0]
        page = await _pick_work_page(context)
        page.set_default_timeout(120_000)

        await page.goto("https://www.youtube.com/upload", wait_until="domcontentloaded")

        if await _detect_verification(page):
            shot_path = await _screenshot_verification(page, shot_dir)
            try:
                await own_browser.close()
            except Exception:
                pass
            try:
                await playwright.stop()
            except Exception:
                pass
            err = _error("Требуется ручное подтверждение Google (см. скриншот).", "verification_required")
            err["screenshot_path"] = shot_path
            return err

        # --- Файл ---
        try:
            file_input = page.locator('input[type="file"]').first
            await file_input.wait_for(state="attached", timeout=90_000)
            await file_input.set_input_files(str(vp.resolve()))
        except Exception as exc:
            logger.exception("file input: %s", exc)
            return _error("Не удалось выбрать файл на YouTube. Проверьте вход в аккаунт.", "file_input_failed")

        await asyncio.sleep(0.5)  # файл уже обработан, долго ждать нет смысла

        # --- Thumbnail (кастомная обложка) ---
        if thumb_path is not None:
            try:
                # Ждём появления кнопки загрузки thumbnail (доступна после загрузки файла)
                thumb_btn = page.locator(
                    'button[aria-label*="thumbnail" i], '
                    'button:has-text("Upload thumbnail"), '
                    'button:has-text("Загрузить"), '
                    '[data-testid="upload-thumbnail"]'
                ).first
                if await thumb_btn.count() > 0:
                    await thumb_btn.wait_for(state="visible", timeout=20_000)
                    await thumb_btn.click()
                    await asyncio.sleep(0.5)
                    # Ищем file input для thumbnail (отдельный от основного)
                    thumb_file_inputs = page.locator('input[type="file"][accept*="image"]')
                    if await thumb_file_inputs.count() > 0:
                        await thumb_file_inputs.first.set_input_files(str(thumb_path.resolve()))
                        await asyncio.sleep(1)
                        logger.info("thumbnail загружен: %s", thumb_path)
                    else:
                        logger.warning("thumbnail file input не найден")
                else:
                    logger.warning("кнопка загрузки thumbnail не найдена на странице")
            except Exception as exc:
                logger.warning("thumbnail upload: %s", exc)

        # (пауза удалена — sleep(0) не давал никакого эффекта)

        # --- Заголовок ---
        title_filled = False
        title_timeout = False
        title_selectors = [
            lambda: page.get_by_label(re.compile(r"title|заголовок|제목", re.I)).first,
            lambda: page.locator("#textbox").first,
            lambda: page.locator('[id*="textbox"]').first,
            lambda: page.locator('textarea, [contenteditable="true"]').first,
        ]
        for get_loc in title_selectors:
            try:
                loc = get_loc()
                if await loc.count() == 0:
                    continue
                await loc.first.wait_for(state="visible", timeout=60_000)
                await _human_type(loc.first, title[:100])
                title_filled = True
                break
            except Exception as exc:
                # Playwright timeout marker в тексте исключения.
                title_timeout = title_timeout or ("timeout" in str(exc).lower())
                continue
        if not title_filled:
            return _error(
                "Не удалось ввести заголовок. Попробуйте загрузить вручную один раз.",
                "title_timeout" if title_timeout else "title_input_failed",
            )

        # --- Описание ---
        try:
            desc_locators = [
                page.get_by_label(re.compile(r"description|описание|설명", re.I)).first,
                page.locator("ytcp-social-suggestions-textbox textarea").first,
                page.locator("textarea").nth(1),
            ]
            for dl in desc_locators:
                try:
                    if await dl.count() == 0:
                        continue
                    await dl.wait_for(state="visible", timeout=30_000)
                    await _human_type(dl, final_description[:5000])
                    break
                except Exception:
                    continue
        except Exception as exc:
            logger.warning("description: %s", exc)

        # --- Next → Next → Next ---
        for _ in range(3):
            try:
                next_btn = page.get_by_role("button", name=re.compile(r"next|далее|다음", re.I))
                if await next_btn.count() > 0:
                    await next_btn.first.click()
                else:
                    alt = page.locator("#next-button, ytcp-button#next-button button").first
                    await alt.click()
            except Exception as exc:
                logger.warning("next click: %s", exc)
            await asyncio.sleep(0.8)  # ждём перехода между шагами мастера

        # --- Публичность: Public ---
        try:
            public_radio = page.get_by_role("radio", name=re.compile(r"public|все|전체", re.I))
            if await public_radio.count() > 0:
                await public_radio.first.click()
            else:
                await page.locator('tp-yt-paper-radio-button[name="PUBLIC"]').click()
        except Exception as exc:
            logger.warning("public: %s", exc)

        # --- Publish ---
        try:
            pub = page.get_by_role("button", name=re.compile(r"publish|опубликовать|게시", re.I))
            if await pub.count() > 0:
                await pub.first.click()
            else:
                await page.locator("#done-button, ytcp-button#done-button button").first.click()
        except Exception as exc:
            logger.exception("publish: %s", exc)
            return _error("Не удалось нажать «Опубликовать». Проверьте настройки канала.", "publish_click_failed")

        publish_ok, publish_reason = await _wait_publish_confirmation(page)
        if not publish_ok:
            return _error(
                "YouTube не подтвердил публикацию. Проверьте ограничения канала в Studio.",
                publish_reason,
            )

        # --- URL из модалки / страницы ---
        video_url: str | None = None
        try:
            await asyncio.sleep(2)
            for _ in range(30):
                if await _detect_verification(page):
                    shot_path2 = await _screenshot_verification(page, shot_dir)
                    try:
                        await own_browser.close()
                    except Exception:
                        pass
                    try:
                        await playwright.stop()
                    except Exception:
                        pass
                    err2 = _error("Требуется ручное подтверждение Google (см. скриншот).", "verification_required")
                    err2["screenshot_path"] = shot_path2
                    return err2

                link = page.locator('a[href*="youtube.com/watch"]').first
                if await link.count() > 0:
                    href = await link.get_attribute("href")
                    if href and "watch" in href:
                        video_url = href.split("&")[0]
                        break
                # Иногда ссылка в поле
                inp = page.locator('input[value*="youtube.com/watch"]').first
                if await inp.count() > 0:
                    video_url = await inp.input_value()
                    if video_url:
                        break
                await asyncio.sleep(1)  # всегда ждём — не busy-loop
        except Exception as exc:
            logger.exception("extract url: %s", exc)

        if not video_url:
            logger.warning("publish confirmed but video URL missing in DOM")
            return _ok({"video_url": None, "comment_pinned": False, "warning": "video_url_not_found"})

        # --- Комментарий + закреп (бонус; сбой не ломает успех загрузки) ---
        comment_pinned = False
        if comment and comment.strip():
            try:
                watch = video_url if video_url.startswith("http") else f"https://{video_url}"
                await page.goto(watch, wait_until="domcontentloaded", timeout=90_000)
                if await _detect_verification(page):
                    path = await _screenshot_verification(page, shot_dir)
                    logger.warning("verification on watch page, shot=%s", path)
                else:
                    box = page.locator("#simplebox-placeholder, #placeholder-area").first
                    if await box.count() > 0:
                        await box.click()
                    area = page.locator("#contenteditable-root, div[contenteditable]").first
                    await area.wait_for(state="visible", timeout=25_000)
                    await _human_type(area, comment[:500])
                    submit = page.get_by_role("button", name=re.compile(r"comment|комментарий|댓글", re.I))
                    if await submit.count() > 0:
                        await submit.first.click()
                    else:
                        await page.keyboard.press("Control+Enter")
                    await asyncio.sleep(3)
                    # Закреп: меню «⋯» у своего комментария
                    menu = page.locator("#comment-button, button[aria-label*='Action']").first
                    if await menu.count() > 0:
                        await menu.click()
                        pin = page.get_by_text(re.compile(r"pin|закреп|고정", re.I)).first
                        if await pin.count() > 0:
                            await pin.click()
                            comment_pinned = True
            except Exception as exc:
                logger.warning("comment/pin: %s", exc)

        return _ok(
            {
                "video_url": video_url,
                "comment_pinned": comment_pinned,
            }
        )

    except Exception as exc:
        logger.exception("upload_and_publish: %s", exc)
        return _error("Не удалось завершить загрузку на YouTube. Попробуйте позже.", "internal_error")
    finally:
        # Закрываем браузер и playwright на всех путях выхода (возврат, исключение).
        # Повторное закрытие уже-закрытого браузера (из verification-путей) — безопасно.
        try:
            if own_browser:
                await own_browser.close()
        except Exception:
            pass
        try:
            if playwright:
                await playwright.stop()
        except Exception:
            pass
