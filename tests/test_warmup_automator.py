"""
Тесты core/warmup_automator.py — без реального браузера/AdsPower.

Всё взаимодействие с Playwright мокируется через unittest.mock.AsyncMock.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core import warmup_automator as w


# ── Константы и пулы ─────────────────────────────────────────────────────────

def test_comment_pool_size():
    """Пул комментариев должен содержать не менее 50 вариантов."""
    assert len(w._KO_COMMENTS) >= 50


def test_comment_pool_no_duplicates():
    """В пуле нет дублей."""
    assert len(w._KO_COMMENTS) == len(set(w._KO_COMMENTS))


def test_comment_pool_all_non_empty():
    """Ни один комментарий не пустой."""
    for c in w._KO_COMMENTS:
        assert c.strip(), f"Пустой комментарий: {c!r}"


def test_korean_keywords_size():
    """Корейских ключевых слов не менее 10."""
    assert len(w._KOREAN_KEYWORDS) >= 10


def test_general_keywords_still_present():
    """Общий пул ключевых слов не пустой."""
    assert len(w._GENERAL_KEYWORDS) >= 5


def test_intensity_configs_complete():
    """Все уровни интенсивности имеют новые поля."""
    required = {"comment_prob", "channel_prob", "bio_pause_prob"}
    for lvl, cfg in w._INTENSITY.items():
        missing = required - cfg.keys()
        assert not missing, f"Уровень {lvl!r} не имеет полей: {missing}"


def test_intensity_comment_prob_range():
    """comment_prob от 0 до 1 для всех уровней."""
    for lvl, cfg in w._INTENSITY.items():
        assert 0.0 <= cfg["comment_prob"] <= 1.0, f"bad comment_prob at {lvl}"


def test_intensity_channel_prob_range():
    """channel_prob от 0 до 1."""
    for lvl, cfg in w._INTENSITY.items():
        assert 0.0 <= cfg["channel_prob"] <= 1.0, f"bad channel_prob at {lvl}"


def test_intensity_bio_pause_prob_range():
    """bio_pause_prob от 0 до 1."""
    for lvl, cfg in w._INTENSITY.items():
        assert 0.0 <= cfg["bio_pause_prob"] <= 1.0, f"bad bio_pause_prob at {lvl}"


def test_intensity_deep_comments_more_than_light():
    """deep имеет более высокую вероятность комментария чем light."""
    assert w._INTENSITY["deep"]["comment_prob"] > w._INTENSITY["light"]["comment_prob"]


def test_normalize_intensity_unknown():
    """Неизвестная строка → medium."""
    assert w._normalize_intensity("ultra_hyper") == "medium"


def test_normalize_intensity_none():
    """None → medium."""
    assert w._normalize_intensity(None) == "medium"


def test_normalize_intensity_valid():
    """Корректные значения возвращаются как есть."""
    for v in ("light", "medium", "deep"):
        assert w._normalize_intensity(v) == v


# ── _bio_pause ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bio_pause_prob_zero_no_sleep():
    """prob=0 → никаких пауз, _random_hover не вызывается."""
    page = AsyncMock()
    # Вызываем с prob=0 — паузы не должно быть (asyncio.sleep не вызовется).
    with patch("core.warmup_automator.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await w._bio_pause(page, prob=0.0)
        mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_bio_pause_prob_one_sleeps():
    """prob=1 → гарантированная пауза в диапазоне 12–45 сек."""
    page = MagicMock()
    page.evaluate = AsyncMock(return_value=1000)
    page.mouse = MagicMock()
    page.mouse.move = AsyncMock()

    sleep_calls: list[float] = []

    async def _capture_sleep(sec: float) -> None:
        sleep_calls.append(sec)

    with patch("core.warmup_automator.asyncio.sleep", side_effect=_capture_sleep):
        await w._bio_pause(page, prob=1.0)

    # Хотя бы один вызов asyncio.sleep должен быть в диапазоне 12–45 сек.
    assert sleep_calls, "asyncio.sleep не был вызван"
    bio_sleeps = [s for s in sleep_calls if 12.0 <= s <= 45.0]
    assert bio_sleeps, f"Ни одна пауза не в диапазоне 12-45 сек: {sleep_calls}"


# ── _bezier_mouse_move ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bezier_mouse_move_calls_move():
    """_bezier_mouse_move вызывает page.mouse.move нужное число раз."""
    page = MagicMock()
    page.mouse = MagicMock()
    page.mouse.move = AsyncMock()

    with patch("core.warmup_automator.asyncio.sleep", new_callable=AsyncMock):
        await w._bezier_mouse_move(page, 0, 0, 500, 300, steps=10)

    # steps + 1 вызов (i=0..steps включительно)
    assert page.mouse.move.call_count == 11


@pytest.mark.asyncio
async def test_bezier_mouse_move_fallback_on_error():
    """При ошибке в основном цикле — fallback mouse.move без краша."""
    page = MagicMock()
    page.mouse = MagicMock()
    page.mouse.move = AsyncMock(side_effect=[Exception("broken")] * 20 + [None])

    with patch("core.warmup_automator.asyncio.sleep", new_callable=AsyncMock):
        # Не должно бросать исключение наружу.
        await w._bezier_mouse_move(page, 0, 0, 100, 100, steps=5)


# ── _scroll_variable_speed ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scroll_variable_speed_calls_wheel():
    """_scroll_variable_speed вызывает mouse.wheel steps раз (минимум)."""
    page = MagicMock()
    page.mouse = MagicMock()
    page.mouse.wheel = AsyncMock()

    with patch("core.warmup_automator.asyncio.sleep", new_callable=AsyncMock):
        await w._scroll_variable_speed(page, steps=5)

    assert page.mouse.wheel.call_count >= 5


@pytest.mark.asyncio
async def test_scroll_variable_speed_positive_delta():
    """Основные дельты скролла вниз (y > 0)."""
    deltas = []

    async def capture_wheel(x, y):
        deltas.append(y)

    page = MagicMock()
    page.mouse = MagicMock()
    page.mouse.wheel = capture_wheel

    with patch("core.warmup_automator.asyncio.sleep", new_callable=AsyncMock):
        await w._scroll_variable_speed(page, steps=6)

    # Большинство дельт положительные (скролл вниз).
    positive = sum(1 for d in deltas if d > 0)
    assert positive >= 5


# ── _leave_comment ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_leave_comment_prob_zero_returns_false():
    """Вероятность 0 → False, страница не трогается."""
    page = MagicMock()
    result = await w._leave_comment(page, w._KO_COMMENTS, comment_prob=0.0)
    assert result is False


@pytest.mark.asyncio
async def test_leave_comment_empty_pool_returns_false():
    """Пустой пул → False."""
    page = MagicMock()
    result = await w._leave_comment(page, [], comment_prob=1.0)
    assert result is False


@pytest.mark.asyncio
async def test_leave_comment_no_placeholder_returns_false():
    """Нет элементов на странице → False (placeholder не найден)."""
    page = MagicMock()
    locator = MagicMock()
    locator.count = AsyncMock(return_value=0)
    locator.is_visible = AsyncMock(return_value=False)
    page.locator = MagicMock(return_value=locator)

    with patch("core.warmup_automator._scroll_variable_speed", new_callable=AsyncMock), \
         patch("core.warmup_automator._pause", new_callable=AsyncMock), \
         patch("core.warmup_automator._bezier_mouse_move", new_callable=AsyncMock):
        result = await w._leave_comment(page, w._KO_COMMENTS, comment_prob=1.0)

    assert result is False


# ── _visit_channel_page ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_visit_channel_page_no_link_returns_false():
    """Нет ссылки на канал → возвращает False."""
    page = MagicMock()
    locator = MagicMock()
    locator.count = AsyncMock(return_value=0)
    locator.is_visible = AsyncMock(return_value=False)
    page.locator = MagicMock(return_value=locator)

    with patch("core.warmup_automator._scroll_variable_speed", new_callable=AsyncMock), \
         patch("core.warmup_automator._pause", new_callable=AsyncMock), \
         patch("core.warmup_automator._random_hover", new_callable=AsyncMock):
        result = await w._visit_channel_page(page, scroll_steps=(2, 4))

    assert result is False


# ── _cookie_prewarm ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cookie_prewarm_visits_google():
    """_cookie_prewarm должен открыть google.com."""
    page = AsyncMock()
    page.goto = AsyncMock()
    page.mouse = MagicMock()
    page.mouse.move = AsyncMock()
    page.mouse.wheel = AsyncMock()
    page.evaluate = AsyncMock(return_value=1000)

    with patch("core.warmup_automator._pause", new_callable=AsyncMock), \
         patch("core.warmup_automator._random_hover", new_callable=AsyncMock), \
         patch("core.warmup_automator._scroll_variable_speed", new_callable=AsyncMock):
        await w._cookie_prewarm(page)

    urls = [str(call.args[0]) for call in page.goto.call_args_list]
    assert any("google.com" in u for u in urls), f"google.com not visited: {urls}"
    assert any("youtube.com" in u for u in urls), f"youtube.com not visited: {urls}"


@pytest.mark.asyncio
async def test_cookie_prewarm_visits_youtube():
    """_cookie_prewarm обязательно открывает youtube.com."""
    page = AsyncMock()
    page.goto = AsyncMock()
    page.evaluate = AsyncMock(return_value=1000)
    page.mouse = MagicMock()
    page.mouse.move = AsyncMock()
    page.mouse.wheel = AsyncMock()

    with patch("core.warmup_automator._pause", new_callable=AsyncMock), \
         patch("core.warmup_automator._random_hover", new_callable=AsyncMock), \
         patch("core.warmup_automator._scroll_variable_speed", new_callable=AsyncMock):
        await w._cookie_prewarm(page)

    urls = [str(call.args[0]) for call in page.goto.call_args_list]
    assert any("youtube.com" in u for u in urls)


@pytest.mark.asyncio
async def test_cookie_prewarm_no_crash_on_error():
    """Если page.goto бросает исключение — _cookie_prewarm не падает."""
    page = AsyncMock()
    page.goto = AsyncMock(side_effect=Exception("network down"))
    page.mouse = MagicMock()

    # Не должно выбросить исключение.
    await w._cookie_prewarm(page)


# ── run_warmup_session — без реального Playwright ────────────────────────────

@pytest.mark.asyncio
async def test_run_warmup_session_no_playwright():
    """Без установленного Playwright — возвращает error с понятным сообщением."""
    with patch.dict("sys.modules", {"playwright": None, "playwright.async_api": None}):
        result = await w.run_warmup_session(
            ws_endpoint="ws://127.0.0.1:1",
            profile_id="test",
            intensity="light",
        )
    assert result["status"] == "error"
    assert "playwright" in result["message"].lower()


@pytest.mark.asyncio
async def test_run_warmup_session_cdp_fail():
    """Если CDP-подключение падает — возвращает error, не исключение.

    async_playwright импортируется локально внутри функции, поэтому
    патчим через playwright.async_api.async_playwright.
    """
    mock_pw_inst = MagicMock()
    mock_pw_inst.stop = AsyncMock()
    mock_pw_inst.chromium = MagicMock()
    mock_pw_inst.chromium.connect_over_cdp = AsyncMock(
        side_effect=Exception("connection refused")
    )

    mock_api = MagicMock()
    mock_api.start = AsyncMock(return_value=mock_pw_inst)

    with patch("playwright.async_api.async_playwright", return_value=mock_api):
        result = await w.run_warmup_session(
            ws_endpoint="ws://127.0.0.1:9999",
            profile_id="p1",
            intensity="light",
        )
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_run_warmup_session_no_contexts():
    """Пустые contexts браузера → ошибка."""
    mock_pw_inst = MagicMock()
    mock_pw_inst.stop = AsyncMock()
    mock_browser = MagicMock()
    mock_browser.contexts = []
    mock_browser.close = AsyncMock()

    mock_chromium = MagicMock()
    mock_chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
    mock_pw_inst.chromium = mock_chromium

    mock_api = MagicMock()
    mock_api.start = AsyncMock(return_value=mock_pw_inst)

    with patch("playwright.async_api.async_playwright", return_value=mock_api):
        result = await w.run_warmup_session(
            ws_endpoint="ws://127.0.0.1:1",
            profile_id="test",
            intensity="light",
        )
    assert result["status"] == "error"


# ── run_warmup_for_profile ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_warmup_for_profile_adspower_fail():
    """Если антидетект не запустил профиль — возвращаем его ошибку."""
    mock_registry = MagicMock()
    mock_registry.start_profile = AsyncMock(
        return_value={"status": "error", "message": "AdsPower не запущен."}
    )
    mock_registry.stop_profile = AsyncMock()

    with patch("core.warmup_automator.run_warmup_session", new_callable=AsyncMock) as mock_sess, \
         patch("core.antidetect_registry.get_registry", return_value=mock_registry):
        result = await w.run_warmup_for_profile("p1", intensity="light")

    assert result["status"] == "error"
    mock_sess.assert_not_called()


@pytest.mark.asyncio
async def test_run_warmup_for_profile_no_ws_endpoint():
    """Антидетект вернул ok, но без ws_endpoint → ошибка."""
    mock_registry = MagicMock()
    mock_registry.start_profile = AsyncMock(
        return_value={"status": "ok", "ws_endpoint": ""}
    )
    mock_registry.stop_profile = AsyncMock()

    with patch("core.antidetect_registry.get_registry", return_value=mock_registry):
        result = await w.run_warmup_for_profile("p1")

    assert result["status"] == "error"
    assert "ws_endpoint" in result["message"]


@pytest.mark.asyncio
async def test_run_warmup_for_profile_stop_called_on_error():
    """stop_profile вызывается даже если сессия упала с исключением."""
    mock_registry = MagicMock()
    mock_registry.start_profile = AsyncMock(
        return_value={"status": "ok", "ws_endpoint": "ws://127.0.0.1:1"}
    )
    mock_registry.stop_profile = AsyncMock()

    with patch("core.antidetect_registry.get_registry", return_value=mock_registry), \
         patch("core.warmup_automator.run_warmup_session", new_callable=AsyncMock) as mock_sess:
        mock_sess.side_effect = RuntimeError("crash")
        with pytest.raises(RuntimeError):
            await w.run_warmup_for_profile("p1")
        mock_registry.stop_profile.assert_called_once()
