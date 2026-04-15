"""
Прогрев YouTube-аккаунтов через AdsPower + Playwright.

Имитирует поведение живого корейского пользователя:
  - Cookie pre-warm: Google → YouTube без логина → основная сессия
  - Плавное движение мыши (кривые Безье)
  - Переменная скорость скролла (разгон / замедление)
  - Поиск и просмотр видео / Shorts с реалистичными паузами
  - Авто-комментарии на корейском (пул 80+ вариантов)
  - Посещение страницы канала после просмотра
  - «Биологические» паузы (имитация отвлечения)
  - Лайки, подписки с вероятностью по уровню интенсивности

Использование:
    result = await warmup_automator.run_warmup_session(
        ws_endpoint=ws,
        profile_id=profile_id,
        intensity="medium",
        niche_keywords=["korean street food", "seoul vlog"],
    )
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ── Корейские поисковые запросы (ниша — нейтральный/развлекательный контент) ─

_KOREAN_KEYWORDS: list[str] = [
    "한국 길거리 음식",        # street food Korea
    "서울 브이로그",            # Seoul vlog
    "먹방 쇼츠",               # mukbang shorts
    "한국 여행",               # Korea travel
    "코리아 일상",             # Korea daily life
    "편의점 신상",             # convenience store new items
    "한강 피크닉",             # Hangang picnic
    "부산 여행",               # Busan travel
    "K뷰티 루틴",              # K-beauty routine
    "한국 드라마 OST",         # K-drama OST
    "운동 루틴 쇼츠",          # workout routine shorts
    "자취생 요리",             # cooking for one
    "카페 투어 서울",          # cafe tour Seoul
    "홍대 거리",               # Hongdae street
    "한국 노래방",             # Korean karaoke
]

# Общий контент — аккаунт выглядит живее, не только своя ниша.
_GENERAL_KEYWORDS: list[str] = [
    "funny cats compilation",
    "cooking pasta recipe",
    "travel vlog 2024",
    "workout at home",
    "morning routine",
    "top 10 movies",
    "street food tour",
    "ambient music study",
    "satisfying videos",
    "life hack compilation",
    "daily vlog",
    "aesthetic room decor",
    "study with me",
    "relaxing music",
    "nature sounds",
]

# ── Пул корейских комментариев (80+ вариантов, разные стили) ─────────────────
# Разделены по «тональности»: удивление, похвала, вовлечение, нейтральные.
# При выборе случайно перемешиваются чтобы не повторялся паттерн.

_KO_COMMENTS: list[str] = [
    # Удивление / восхищение
    "와 진짜 대박이다 ㅋㅋㅋ",
    "이거 뭐야 너무 좋은데??",
    "와.. 말문이 막히네",
    "헐 이게 가능해?? 😮",
    "대박 ㄹㅇ 소름돋음",
    "이런 거 처음 봤어요 신기하다",
    "와 진짜 눈을 못 떼겠네",
    "어떻게 이런 생각을 했지...",
    "완전 예상 밖이다 ㅋㅋ",
    "헐 저도 해보고 싶어요!",
    # Похвала каналу
    "영상 퀄리티 진짜 좋다",
    "편집이 너무 깔끔해요 👍",
    "이런 채널 찾고 있었어요!",
    "구독 눌렀어요 ❤️",
    "알림도 켰습니다!",
    "이 채널 왜 이제 알았지",
    "오래 전부터 봐왔는데 항상 좋아요",
    "매번 기대 이상이에요",
    "콘텐츠가 정말 알차네요",
    "앞으로도 좋은 영상 부탁드려요!",
    # Вовлечение / вопросы
    "다음 영상도 기대돼요!",
    "2편도 올려주세요 🙏",
    "더 자세히 알고 싶어요",
    "혹시 제품 링크 있나요?",
    "저도 시도해볼게요!",
    "친구한테 공유해야겠다",
    "언제 다음 영상 나와요?",
    "이거 어디서 살 수 있어요?",
    "방법 좀 더 알려주세요",
    "라이브 방송도 해주세요!",
    # Нейтральные / повседневные
    "알고리즘이 데려왔는데 잘 왔다 ㅋㅋ",
    "출퇴근길에 봤는데 완전 힐링",
    "점심 먹다가 봤는데 행복하다",
    "자기 전에 보기 딱 좋은 영상",
    "이거 몇 번째 보는 건지 모르겠다",
    "오늘도 좋은 영상 감사합니다",
    "짧은데 임팩트 있다 👏",
    "한번에 이해됐어요",
    "깔끔하게 정리됐네요",
    "시간 가는 줄 모르고 봤어요",
    # Эмодзи-реакции (короткие)
    "❤️❤️❤️",
    "👏👏👏",
    "🔥🔥",
    "😂ㅋㅋㅋ",
    "👍👍",
    "완전 공감 ㅋㅋ",
    "ㅋㅋㅋㅋㅋ 진짜",
    "ㅇㅈ ㅇㅈ",
    "맞아 맞아!",
    "ㄹㅇㅋㅋ",
    # Специфика для Shorts
    "쇼츠로 딱이다",
    "이 길이가 딱 좋아요",
    "60초 안에 다 담았네",
    "짧고 굵다 ㅋㅋ",
    "반복 재생 중...",
    "또 봤다 ㅋㅋ",
    "몇 번 봤는지 모르겠어",
    "루프 돌리는 중이에요",
    "다시 보기 눌렀습니다",
    "계속 보게 된다 ㅠㅠ",
    # Азарт / казино ниша (нейтральные, без прямых упоминаний)
    "이런 반전이 있을 줄이야",
    "마지막 장면 진짜 충격이다",
    "끝까지 봤는데 후회 없음",
    "한번에 빠져들었어요",
    "긴장되서 심장 쿵쾅ㅋㅋ",
    "다음편이 너무 궁금해요",
    "이렇게 될 줄 몰랐다",
    "반전 대박 ㅋㅋㅋ",
    "손에 땀을 쥐게 하는 영상",
    "오늘 영상 중 제일 재밌다",
    # Общение с другими зрителями
    "여기 사람 있으면 좋아요 눌러요",
    "같이 보는 사람 👇",
    "2026년에 보는 사람?",
    "이거 보고 잠 못 잘 것 같다",
    "현생에 치여 살다 이걸 보니 힐링",
    "오늘 힘들었는데 이 영상 보고 힘냈어요",
    "웃음 참으려다 결국 실패 ㅋㅋ",
    "소리 질렀습니다 ㄹㅇ",
]


# ── Параметры интенсивности ───────────────────────────────────────────────────

_INTENSITY: dict[str, dict[str, Any]] = {
    "light": {
        "videos":            (2, 4),
        "searches":          (1, 2),
        "shorts":            (3, 6),
        "like_prob":         0.05,
        "sub_prob":          0.01,
        "comment_prob":      0.04,   # вероятность оставить комментарий к видео
        "channel_prob":      0.05,   # вероятность зайти на страницу канала
        "bio_pause_prob":    0.10,   # вероятность «биологической» паузы (10–30 сек)
        "pause_range":       (8.0, 20.0),
        "scroll_steps":      (3, 7),
    },
    "medium": {
        "videos":            (4, 7),
        "searches":          (2, 4),
        "shorts":            (6, 12),
        "like_prob":         0.10,
        "sub_prob":          0.03,
        "comment_prob":      0.10,
        "channel_prob":      0.12,
        "bio_pause_prob":    0.15,
        "pause_range":       (15.0, 40.0),
        "scroll_steps":      (5, 12),
    },
    "deep": {
        "videos":            (8, 14),
        "searches":          (4, 7),
        "shorts":            (10, 20),
        "like_prob":         0.15,
        "sub_prob":          0.05,
        "comment_prob":      0.18,
        "channel_prob":      0.20,
        "bio_pause_prob":    0.20,
        "pause_range":       (25.0, 70.0),
        "scroll_steps":      (8, 20),
    },
}


# ── Утилиты ──────────────────────────────────────────────────────────────────

def _error(msg: str, error_type: str = "warmup_error", failed_step: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "error", "message": msg, "error_type": error_type}
    if failed_step:
        out["failed_step"] = failed_step
    return out


def _ok(data: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "ok"}
    if data:
        out.update(data)
    return out


def _normalize_intensity(raw: str | None) -> str:
    k = str(raw or "medium").strip().lower()
    return k if k in _INTENSITY else "medium"


async def _pause(lo: float = 1.5, hi: float = 4.0) -> None:
    """Случайная пауза между действиями."""
    await asyncio.sleep(random.uniform(lo, hi))


async def _bio_pause(page: Any, prob: float = 0.15) -> None:
    """
    «Биологическая» пауза — имитирует отвлечение пользователя (встал за чаем, ответил на сообщение).
    С вероятностью prob делает паузу 12–45 секунд.
    Мышь слегка двигается в начале и конце — браузер не фризит.
    """
    if random.random() >= prob:
        return
    duration = random.uniform(12.0, 45.0)
    logger.debug("bio_pause: %.0f sec", duration)
    await _random_hover(page)
    await asyncio.sleep(duration)
    await _random_hover(page)


async def _human_type(locator: Any, text: str) -> None:
    """Посимвольный ввод с нерегулярными задержками (как реальная печать)."""
    try:
        await locator.click(timeout=10_000)
        await locator.press("Control+a")
        await locator.press("Backspace")
        # Неравномерные задержки: иногда «замешкался», иногда быстро.
        for char in text:
            delay_ms = random.choices(
                [random.randint(40, 80), random.randint(80, 160), random.randint(160, 320)],
                weights=[60, 30, 10],
            )[0]
            await locator.type(char, delay=delay_ms)
    except Exception as exc:
        logger.debug("_human_type fallback: %s", exc)
        try:
            await locator.fill(text)
        except Exception:
            pass


async def _bezier_mouse_move(
    page: Any,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    steps: int = 20,
) -> None:
    """
    Плавное движение мыши по кривой Безье между двумя точками.
    Случайная контрольная точка создаёт естественный изгиб траектории.
    """
    try:
        cx = random.uniform(min(x0, x1), max(x0, x1))
        cy = random.uniform(min(y0, y1) - 60, max(y0, y1) + 60)
        for i in range(steps + 1):
            t = i / steps
            # Квадратная кривая Безье: B(t) = (1-t)^2*P0 + 2(1-t)t*Pc + t^2*P1
            bx = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t ** 2 * x1
            by = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t ** 2 * y1
            await page.mouse.move(bx, by)
            # Замедление в начале и конце (ease-in-out)
            ease = math.sin(t * math.pi) * 0.012 + 0.003
            await asyncio.sleep(ease)
    except Exception:
        try:
            await page.mouse.move(x1, y1)
        except Exception:
            pass


async def _random_hover(page: Any) -> None:
    """Случайное движение мыши — плавное, по кривой Безье."""
    try:
        vw = int(await page.evaluate("window.innerWidth"))
        vh = int(await page.evaluate("window.innerHeight"))
        x0 = random.randint(80, max(81, vw - 80))
        y0 = random.randint(80, max(81, vh - 80))
        x1 = random.randint(80, max(81, vw - 80))
        y1 = random.randint(80, max(81, vh - 80))
        await _bezier_mouse_move(page, x0, y0, x1, y1, steps=random.randint(10, 25))
        await _pause(0.1, 0.4)
    except Exception:
        pass


async def _scroll_variable_speed(page: Any, steps: int) -> None:
    """
    Скролл с переменной скоростью (разгон → крейсерская → замедление).
    Иногда делает небольшой откат вверх — как живой пользователь.
    """
    for i in range(steps):
        # Нарастание в начале, замедление в конце.
        progress = i / max(steps - 1, 1)
        speed = 0.5 + math.sin(progress * math.pi) * 0.5  # 0.5 → 1.0 → 0.5
        delta = int(random.randint(150, 400) * (0.6 + speed * 0.4))
        await page.mouse.wheel(0, delta)
        await asyncio.sleep(random.uniform(0.15, 0.55))
        # Случайный откат (~15% шагов)
        if i > 0 and random.random() < 0.15:
            await page.mouse.wheel(0, -random.randint(60, 180))
            await asyncio.sleep(random.uniform(0.2, 0.6))
        # Редкая длинная пауза при скролле (пользователь читает)
        if random.random() < 0.08:
            await asyncio.sleep(random.uniform(1.5, 4.0))


# ── Cookie pre-warm ──────────────────────────────────────────────────────────

async def _cookie_prewarm(page: Any) -> bool:
    """
    Нагон куки перед основной сессией YouTube.

    Маршрут: google.com → поисковый запрос → YouTube (без логина, как гость)
    → YouTube Music. Это создаёт реалистичную cookie-историю с Google-доменов
    до того как аккаунт начинает активно действовать.
    """
    try:
        # 1. Google.com — смотрим главную, двигаем мышь.
        await page.goto("https://www.google.com", wait_until="domcontentloaded", timeout=30_000)
        await _pause(2.0, 4.0)
        await _random_hover(page)
        await _scroll_variable_speed(page, random.randint(2, 4))

        # 2. Поисковый запрос (нейтральный, корейская тематика).
        queries = [
            "유튜브 쇼츠 추천",
            "한국 유튜브 채널",
            "재밌는 쇼츠",
            "youtube shorts korea",
        ]
        q = random.choice(queries).replace(" ", "+")
        await page.goto(f"https://www.google.com/search?q={q}", wait_until="domcontentloaded", timeout=30_000)
        await _pause(2.0, 5.0)
        await _scroll_variable_speed(page, random.randint(2, 5))
        await _random_hover(page)

        # 3. YouTube как гость (без логина) — brief visit.
        await page.goto("https://www.youtube.com", wait_until="domcontentloaded", timeout=45_000)
        await _pause(3.0, 6.0)
        await _scroll_variable_speed(page, random.randint(3, 6))
        await _random_hover(page)

        # 4. YouTube Music (опционально — строит историю Google-сессии).
        if random.random() < 0.5:
            await page.goto("https://music.youtube.com", wait_until="domcontentloaded", timeout=30_000)
            await _pause(2.0, 4.0)
            await _scroll_variable_speed(page, random.randint(2, 4))

        logger.debug("cookie_prewarm: done")
        return True
    except Exception as exc:
        logger.warning("cookie_prewarm failed: %s", exc)
        return False


# ── Действия ─────────────────────────────────────────────────────────────────

async def _browse_homepage(page: Any, scroll_steps: tuple[int, int]) -> bool:
    """Главная YouTube: скролл + hover."""
    try:
        await page.goto("https://www.youtube.com", wait_until="domcontentloaded", timeout=60_000)
        await _pause(2.0, 5.0)
        steps = random.randint(*scroll_steps)
        await _scroll_variable_speed(page, steps)
        await _random_hover(page)
        return True
    except Exception as exc:
        logger.warning("browse_homepage failed: %s", exc)
        return False


async def _leave_comment(
    page: Any,
    comment_pool: list[str],
    comment_prob: float,
) -> bool:
    """
    Попытка оставить корейский комментарий на текущем открытом видео.

    Возвращает True если комментарий успешно отправлен.
    Ошибки не поднимают исключение — просто пишутся в лог.
    """
    if random.random() >= comment_prob:
        return False
    if not comment_pool:
        return False
    comment_text = random.choice(comment_pool)
    try:
        # Скролл вниз к комментариям.
        await _scroll_variable_speed(page, random.randint(3, 6))
        await _pause(1.0, 2.5)

        # Клик в поле "Добавить комментарий".
        placeholder_selectors = [
            '#simplebox-placeholder',
            '#placeholder-area',
            'ytd-comment-simplebox-renderer #contenteditable-root',
            '[aria-label*="comment" i][aria-label*="Add" i]',
            '[aria-label*="댓글" i]',
        ]
        clicked = False
        for sel in placeholder_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible(timeout=4_000):
                    # Плавно подводим мышь через Bezier.
                    box = await el.bounding_box()
                    if box:
                        await _bezier_mouse_move(
                            page,
                            random.randint(200, 400), random.randint(200, 400),
                            box["x"] + box["width"] / 2,
                            box["y"] + box["height"] / 2,
                        )
                    await el.click(timeout=5_000)
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            return False

        await _pause(0.8, 2.0)

        # Поле ввода после активации placeholder.
        input_selectors = [
            '#contenteditable-root[contenteditable="true"]',
            'div[contenteditable="true"]#contenteditable-root',
            'ytd-comment-simplebox-renderer div[contenteditable]',
        ]
        typed = False
        for sel in input_selectors:
            try:
                area = page.locator(sel).first
                if await area.count() > 0 and await area.is_visible(timeout=5_000):
                    await _human_type(area, comment_text)
                    typed = True
                    break
            except Exception:
                continue

        if not typed:
            return False

        await _pause(1.0, 2.5)

        # Кнопка отправки.
        submit_selectors = [
            '#submit-button button',
            'button[aria-label*="Comment" i]',
            'button[aria-label*="댓글" i]',
            'ytd-button-renderer#submit-button button',
        ]
        for sel in submit_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible(timeout=4_000):
                    box = await btn.bounding_box()
                    if box:
                        await _bezier_mouse_move(
                            page,
                            random.randint(200, 500), random.randint(200, 500),
                            box["x"] + box["width"] / 2,
                            box["y"] + box["height"] / 2,
                        )
                    await btn.click(timeout=5_000)
                    await _pause(1.5, 3.0)
                    logger.debug("comment posted: %r", comment_text[:40])
                    return True
            except Exception:
                continue

        # Fallback: Ctrl+Enter.
        try:
            await page.keyboard.press("Control+Enter")
            await _pause(1.5, 3.0)
            return True
        except Exception:
            pass

    except Exception as exc:
        logger.debug("leave_comment: %s", exc)
    return False


async def _visit_channel_page(page: Any, scroll_steps: tuple[int, int]) -> bool:
    """
    Перейти на страницу канала текущего видео → скролл по видео → вернуться.
    Имитирует интерес к автору контента.
    """
    try:
        # Ищем ссылку на канал (имя/аватар).
        channel_selectors = [
            'ytd-video-owner-renderer a.yt-simple-endpoint',
            '#channel-name a',
            'ytd-channel-name a',
            '#owner-name a',
        ]
        for sel in channel_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible(timeout=4_000):
                    await el.click(timeout=6_000)
                    await _pause(2.5, 5.0)
                    await _scroll_variable_speed(page, random.randint(*scroll_steps))
                    await _random_hover(page)
                    await _pause(1.5, 3.5)
                    await page.go_back()
                    await _pause(1.5, 3.0)
                    return True
            except Exception:
                continue
    except Exception as exc:
        logger.debug("visit_channel_page: %s", exc)
    return False


async def _search_and_watch(
    page: Any,
    query: str,
    watch_sec: tuple[float, float],
    like_prob: float,
    sub_prob: float,
    comment_prob: float,
    channel_prob: float,
    comment_pool: list[str],
    scroll_steps: tuple[int, int],
) -> dict[str, Any]:
    """
    Поиск → клик на видео (не первое, случайный из топ-4) → просмотр →
    опционально: лайк, подписка, комментарий, страница канала.
    """
    try:
        await page.goto(
            f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}",
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        await _pause(1.5, 3.5)
        await _scroll_variable_speed(page, random.randint(2, 4))

        # Клик на видео (случайный из топ-4).
        selectors = [
            'a#video-title[href*="/watch"]',
            'ytd-video-renderer a[href*="/watch"]',
            'a[href*="/watch?v="]',
        ]
        clicked = False
        for sel in selectors:
            try:
                items = page.locator(sel)
                count = await items.count()
                if count > 0:
                    idx = random.randint(0, min(3, count - 1))
                    el = items.nth(idx)
                    box = await el.bounding_box()
                    if box:
                        await _bezier_mouse_move(
                            page,
                            random.randint(100, 300), random.randint(100, 300),
                            box["x"] + box["width"] / 2,
                            box["y"] + box["height"] / 2,
                        )
                    await el.click(timeout=10_000)
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            return _error("no_video_found")

        await _pause(2.0, 4.0)

        # Просмотр видео.
        sec = random.uniform(*watch_sec)
        logger.debug("watching %.0f sec (query=%r)", sec, query)

        # Во время просмотра — редкие движения мыши (пользователь не замер).
        watch_chunks = max(1, int(sec / 15))
        chunk_sec = sec / watch_chunks
        for _ in range(watch_chunks):
            await asyncio.sleep(chunk_sec)
            if random.random() < 0.3:
                await _random_hover(page)

        # Иногда скролим комментарии во время «просмотра».
        commented = False
        if random.random() < 0.40:
            await _scroll_variable_speed(page, random.randint(2, 5))
            commented = await _leave_comment(page, comment_pool, comment_prob)
            if not commented:
                # Скролл обратно вверх к плееру.
                await page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
                await _pause(0.5, 1.5)

        # Лайк.
        liked = False
        if random.random() < like_prob:
            try:
                like_btn = page.locator(
                    'button[aria-label*="like" i]:not([aria-label*="dislike" i]),'
                    'ytd-toggle-button-renderer[is-icon-button] button'
                ).first
                if await like_btn.is_visible(timeout=5_000):
                    box = await like_btn.bounding_box()
                    if box:
                        await _bezier_mouse_move(
                            page,
                            random.randint(100, 400), random.randint(100, 400),
                            box["x"] + box["width"] / 2,
                            box["y"] + box["height"] / 2,
                        )
                    await like_btn.click(timeout=5_000)
                    liked = True
                    await _pause(0.5, 1.5)
            except Exception:
                pass

        # Подписка.
        subscribed = False
        if random.random() < sub_prob:
            try:
                sub_btn = page.locator(
                    'button:has-text("Subscribe"), button:has-text("Подписаться"),'
                    'yt-button-shape button[aria-label*="Subscribe" i]'
                ).first
                if await sub_btn.is_visible(timeout=5_000):
                    await sub_btn.click(timeout=5_000)
                    subscribed = True
                    await _pause(0.8, 2.0)
            except Exception:
                pass

        # Страница канала.
        visited_channel = False
        if random.random() < channel_prob:
            visited_channel = await _visit_channel_page(page, scroll_steps)

        return _ok({
            "liked": liked,
            "subscribed": subscribed,
            "commented": commented,
            "visited_channel": visited_channel,
            "watched_sec": round(sec, 1),
        })

    except Exception as exc:
        logger.debug("search_and_watch error: %s", exc)
        return _error(str(exc))


async def _watch_shorts_feed(
    page: Any,
    count: int,
    like_prob: float,
    comment_prob: float,
    comment_pool: list[str],
) -> dict[str, Any]:
    """
    Shorts-лента: пролистать N роликов. Иногда лайк или комментарий.
    Возвращает статистику: watched, liked, commented.
    """
    watched = liked = commented = 0
    try:
        await page.goto("https://www.youtube.com/shorts", wait_until="domcontentloaded", timeout=60_000)
        await _pause(2.0, 4.0)

        for _ in range(count):
            sec = random.uniform(4.0, 18.0)
            await asyncio.sleep(sec)

            # Лайк.
            if random.random() < like_prob:
                try:
                    btn = page.locator(
                        'button[aria-label*="like" i]:not([aria-label*="dislike" i])'
                    ).first
                    if await btn.is_visible(timeout=3_000):
                        box = await btn.bounding_box()
                        if box:
                            await _bezier_mouse_move(
                                page,
                                random.randint(100, 300), random.randint(300, 500),
                                box["x"] + box["width"] / 2,
                                box["y"] + box["height"] / 2,
                            )
                        await btn.click(timeout=3_000)
                        liked += 1
                        await _pause(0.3, 0.8)
                except Exception:
                    pass

            # Комментарий в Shorts (редко — нужно раскрыть панель).
            if random.random() < comment_prob * 0.5:
                try:
                    comment_btn = page.locator(
                        'button[aria-label*="comment" i],'
                        'ytd-button-renderer[id*="comment"]'
                    ).first
                    if await comment_btn.is_visible(timeout=2_000):
                        await comment_btn.click(timeout=3_000)
                        await _pause(0.8, 2.0)
                        area = page.locator('div[contenteditable="true"]').first
                        if await area.is_visible(timeout=4_000):
                            await _human_type(area, random.choice(comment_pool))
                            await _pause(0.8, 1.5)
                            await page.keyboard.press("Control+Enter")
                            commented += 1
                            await _pause(1.0, 2.0)
                except Exception:
                    pass

            # Следующий Short.
            try:
                nxt = page.locator(
                    'button[aria-label*="Next" i], button[aria-label*="Следующ" i],'
                    '#navigation-button-down button'
                ).first
                if await nxt.is_visible(timeout=3_000):
                    await nxt.click(timeout=3_000)
                else:
                    await page.keyboard.press("ArrowDown")
            except Exception:
                await page.keyboard.press("ArrowDown")

            await _pause(0.6, 1.8)
            watched += 1

    except Exception as exc:
        logger.debug("watch_shorts_feed: %s", exc)

    return {"watched": watched, "liked": liked, "commented": commented}


async def _browse_subscriptions(page: Any, scroll_steps: tuple[int, int]) -> None:
    """Вкладка Подписки — признак живого аккаунта."""
    try:
        await page.goto(
            "https://www.youtube.com/feed/subscriptions",
            wait_until="domcontentloaded",
            timeout=45_000,
        )
        await _pause(2.0, 5.0)
        await _scroll_variable_speed(page, random.randint(*scroll_steps))
        await _random_hover(page)
    except Exception as exc:
        logger.debug("browse_subscriptions: %s", exc)


async def _browse_trending(page: Any, scroll_steps: tuple[int, int]) -> None:
    """Тренды / Explore."""
    try:
        await page.goto(
            "https://www.youtube.com/feed/trending",
            wait_until="domcontentloaded",
            timeout=45_000,
        )
        await _pause(1.5, 4.0)
        await _scroll_variable_speed(page, random.randint(*scroll_steps))
    except Exception as exc:
        logger.debug("browse_trending: %s", exc)


async def _browse_history(page: Any) -> None:
    """Просмотр истории просмотров — глубокое взаимодействие с аккаунтом."""
    try:
        await page.goto(
            "https://www.youtube.com/feed/history",
            wait_until="domcontentloaded",
            timeout=45_000,
        )
        await _pause(1.5, 3.5)
        await _scroll_variable_speed(page, random.randint(3, 7))
    except Exception as exc:
        logger.debug("browse_history: %s", exc)


# ── Точка входа ──────────────────────────────────────────────────────────────

async def run_warmup_session(
    ws_endpoint: str,
    profile_id: str,
    intensity: str = "medium",
    niche_keywords: list[str] | None = None,
    tenant_id: str | None = None,
    enable_prewarm: bool = True,
) -> dict[str, Any]:
    """
    Полная сессия прогрева для профиля AdsPower.

    Параметры
    ---------
    ws_endpoint     : CDP websocket (из adspower_sync.start_profile)
    profile_id      : ID профиля AdsPower (для логов и результата)
    intensity       : "light" | "medium" | "deep"
    niche_keywords  : ключевые слова ниши (смешиваются с корейскими и общими)
    tenant_id       : передаётся в результат (не используется внутри)
    enable_prewarm  : выполнять cookie pre-warm (Google → YouTube гость → YT Music)

    Возвращает
    ----------
    dict: status, profile_id, intensity, actions_log, stats
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return _error("Playwright не установлен. Выполните: pip install playwright && playwright install chromium")

    lvl = _normalize_intensity(intensity)
    cfg = _INTENSITY[lvl]

    # Пул ключевых слов: своя ниша + корейские + общие.
    keywords: list[str] = list(niche_keywords or []) + _KOREAN_KEYWORDS + _GENERAL_KEYWORDS
    random.shuffle(keywords)

    # Пул комментариев — перемешиваем чтобы не было паттерна.
    comment_pool = list(_KO_COMMENTS)
    random.shuffle(comment_pool)

    n_videos   = random.randint(*cfg["videos"])
    n_searches = random.randint(*cfg["searches"])
    n_shorts   = random.randint(*cfg["shorts"])

    actions_log: list[str] = []
    stats: dict[str, Any] = {
        "videos_watched":   0,
        "shorts_watched":   0,
        "shorts_liked":     0,
        "shorts_commented": 0,
        "searches_done":    0,
        "likes_given":      0,
        "subscriptions":    0,
        "comments_left":    0,
        "channels_visited": 0,
        "prewarm_done":     False,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    }

    own_browser = None
    playwright_inst = None

    try:
        playwright_inst = await async_playwright().start()
        own_browser = await playwright_inst.chromium.connect_over_cdp(ws_endpoint)
    except Exception as exc:
        logger.exception("warmup connect: %s", exc)
        return _error(f"Не удалось подключиться к браузеру AdsPower: {exc}")

    try:
        if not own_browser.contexts:
            return _error("Нет контекста браузера. Запустите профиль в AdsPower.")

        context = own_browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()
        page.set_default_timeout(60_000)

        # 0. Cookie pre-warm.
        if enable_prewarm:
            actions_log.append("cookie_prewarm")
            ok = await _cookie_prewarm(page)
            stats["prewarm_done"] = bool(ok)
            if not ok:
                return _error(
                    "Cookie pre-warm завершился с ошибкой.",
                    error_type="prewarm_failed",
                    failed_step="cookie_prewarm",
                )
            await _pause(2.0, 4.0)

        # 1. Главная YouTube.
        actions_log.append("browse_homepage")
        if not await _browse_homepage(page, cfg["scroll_steps"]):
            return _error(
                "Не удалось открыть и пролистать главную YouTube.",
                error_type="homepage_failed",
                failed_step="browse_homepage",
            )
        await _bio_pause(page, cfg["bio_pause_prob"])
        await _pause(1.5, 3.0)

        # 2. Поиск + просмотр видео.
        used_kw: set[str] = set()
        for _ in range(n_searches):
            kw = next((k for k in keywords if k not in used_kw), random.choice(keywords))
            used_kw.add(kw)
            actions_log.append(f"search:{kw}")
            res = await _search_and_watch(
                page,
                query=kw,
                watch_sec=cfg["pause_range"],
                like_prob=cfg["like_prob"],
                sub_prob=cfg["sub_prob"],
                comment_prob=cfg["comment_prob"],
                channel_prob=cfg["channel_prob"],
                comment_pool=comment_pool,
                scroll_steps=cfg["scroll_steps"],
            )
            if res.get("status") == "ok":
                stats["videos_watched"]   += 1
                stats["searches_done"]    += 1
                if res.get("liked"):
                    stats["likes_given"]      += 1
                if res.get("subscribed"):
                    stats["subscriptions"]    += 1
                if res.get("commented"):
                    stats["comments_left"]    += 1
                if res.get("visited_channel"):
                    stats["channels_visited"] += 1
            else:
                actions_log.append(f"search_failed:{kw}")
            await _bio_pause(page, cfg["bio_pause_prob"])
            await _pause(2.0, 6.0)

        # 3. Shorts-лента.
        actions_log.append(f"shorts_feed:{n_shorts}")
        shorts_stats = await _watch_shorts_feed(
            page, n_shorts,
            like_prob=cfg["like_prob"],
            comment_prob=cfg["comment_prob"],
            comment_pool=comment_pool,
        )
        stats["shorts_watched"]   = shorts_stats["watched"]
        stats["shorts_liked"]     = shorts_stats["liked"]
        stats["shorts_commented"] = shorts_stats["commented"]
        await _bio_pause(page, cfg["bio_pause_prob"])
        await _pause(1.5, 4.0)

        # 4. Дополнительные видео с главной страницы.
        remaining = n_videos - stats["videos_watched"]
        if remaining > 0:
            if not await _browse_homepage(page, cfg["scroll_steps"]):
                actions_log.append("homepage_followup_failed")
            for _ in range(remaining):
                try:
                    items = page.locator('a#video-title[href*="/watch"]')
                    cnt = await items.count()
                    if cnt > 0:
                        el = items.nth(random.randint(0, min(5, cnt - 1)))
                        box = await el.bounding_box()
                        if box:
                            await _bezier_mouse_move(
                                page,
                                random.randint(100, 400), random.randint(100, 400),
                                box["x"] + box["width"] / 2,
                                box["y"] + box["height"] / 2,
                            )
                        await el.click(timeout=10_000)
                        await _pause(1.5, 3.0)
                        sec = random.uniform(*cfg["pause_range"])
                        await asyncio.sleep(sec)
                        stats["videos_watched"] += 1
                        actions_log.append(f"homepage_video:{round(sec, 0)}s")
                        # Лайк.
                        if random.random() < cfg["like_prob"]:
                            try:
                                btn = page.locator(
                                    'button[aria-label*="like" i]:not([aria-label*="dislike" i])'
                                ).first
                                if await btn.is_visible(timeout=4_000):
                                    await btn.click(timeout=4_000)
                                    stats["likes_given"] += 1
                            except Exception:
                                pass
                        # Комментарий.
                        if await _leave_comment(page, comment_pool, cfg["comment_prob"]):
                            stats["comments_left"] += 1
                        await page.go_back()
                        await _pause(1.0, 3.0)
                except Exception:
                    pass

        # 5. Подписки, Тренды, История (medium / deep).
        if lvl in ("medium", "deep"):
            if random.random() < 0.5:
                actions_log.append("browse_subscriptions")
                await _browse_subscriptions(page, cfg["scroll_steps"])
                await _pause(1.0, 3.0)
            if random.random() < 0.4:
                actions_log.append("browse_trending")
                await _browse_trending(page, cfg["scroll_steps"])
                await _pause(1.0, 3.0)
            if lvl == "deep" and random.random() < 0.35:
                actions_log.append("browse_history")
                await _browse_history(page)
                await _pause(1.0, 2.5)

        # 6. Финальный возврат на главную.
        try:
            await page.goto("https://www.youtube.com", wait_until="domcontentloaded", timeout=30_000)
            await _pause(1.0, 2.5)
            await _random_hover(page)
        except Exception:
            pass

        stats["finished_at"] = datetime.now(timezone.utc).isoformat()

        if n_searches > 0 and stats["searches_done"] == 0:
            return _error(
                "Сессия прогрева не выполнила ни одного успешного поиска/просмотра.",
                error_type="search_flow_failed",
                failed_step="search_and_watch",
            )

        return _ok({
            "profile_id":   profile_id,
            "intensity":    lvl,
            "tenant_id":    tenant_id,
            "actions_log":  actions_log,
            "stats":        stats,
            "warnings": [a for a in actions_log if "failed" in a],
        })

    except Exception as exc:
        logger.exception("warmup session error: %s", exc)
        return _error(f"Ошибка сессии прогрева: {exc}", error_type="session_exception")

    finally:
        try:
            if own_browser:
                await own_browser.close()
        except Exception:
            pass
        try:
            if playwright_inst:
                await playwright_inst.stop()
        except Exception:
            pass


async def run_warmup_for_profile(
    profile_id: str,
    intensity: str = "medium",
    niche_keywords: list[str] | None = None,
    tenant_id: str | None = None,
    enable_prewarm: bool = True,
) -> dict[str, Any]:
    """
    Высокоуровневая обёртка: start_profile → warmup → stop_profile.
    Использовать из API или планировщика.
    """
    from core.antidetect_registry import get_registry
    registry = get_registry()

    start_res = await registry.start_profile(profile_id, tenant_id=tenant_id or "default")
    if start_res.get("status") != "ok":
        return start_res

    ws = start_res.get("ws_endpoint", "")
    if not ws:
        await registry.stop_profile(profile_id, tenant_id=tenant_id or "default")
        return _error("Антидетект-браузер не вернул ws_endpoint.")

    try:
        return await run_warmup_session(
            ws_endpoint=ws,
            profile_id=profile_id,
            intensity=intensity,
            niche_keywords=niche_keywords,
            tenant_id=tenant_id,
            enable_prewarm=enable_prewarm,
        )
    finally:
        await registry.stop_profile(profile_id, tenant_id=tenant_id or "default")
