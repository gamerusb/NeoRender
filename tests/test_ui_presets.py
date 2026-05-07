"""
Тесты для данных UI-пресетов (SIMPLE_PRESETS в ResearchPage, UI_PRESETS в UniqualizerPage).
Парсим TypeScript через regex — без Node.js и без запуска браузера.

Проверяем:
  - Структурную целостность пресетов (все обязательные поля)
  - Уникальность ключей
  - Валидность значений (регионы, периоды, цвета)
  - Маппинг UI_PRESETS → backendPreset совпадает с допустимыми значениями backend
"""

from __future__ import annotations

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages"
RESEARCH_TSX = FRONTEND / "ResearchPage.tsx"
UNIQUALIZER_TSX = FRONTEND / "UniqualizerPage.tsx"

VALID_REGIONS = {"KR", "TH", "MY", "JP", "ID", "US", "RU", "VN", "GLOBAL", ""}
VALID_BACKEND_PRESETS = {"standard", "soft", "deep", "ultra"}
VALID_INTENSITIES = {"low", "med", "high"}


# ── ResearchPage SIMPLE_PRESETS ────────────────────────────────────────────────

def _parse_simple_presets(source: str) -> list[dict]:
    """Вытащить label/region/period/query из SIMPLE_PRESETS в TSX."""
    block_m = re.search(r"const SIMPLE_PRESETS\s*=\s*\[(.*?)\]\s*as const", source, re.DOTALL)
    assert block_m, "SIMPLE_PRESETS не найдены в ResearchPage.tsx"
    block = block_m.group(1)

    presets = []
    # Разбиваем по фигурным скобкам первого уровня
    depth = 0
    start = None
    for i, ch in enumerate(block):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                entry = block[start:i + 1]
                p: dict = {}
                for key, pattern in [
                    ("label",  r'label\s*:\s*"([^"]+)"'),
                    ("query",  r'query\s*:\s*"([^"]+)"'),
                    ("region", r'region\s*:\s*"([^"]+)"'),
                    ("period", r'period\s*:\s*(\d+)'),
                    ("accent", r'accent\s*:\s*"([^"]+)"'),
                ]:
                    m = re.search(pattern, entry)
                    if m:
                        p[key] = m.group(1)
                presets.append(p)
    return presets


def _parse_ui_presets(source: str) -> list[dict]:
    """Вытащить key/backendPreset/intensity/enableAllEffects из UI_PRESETS в TSX."""
    block_m = re.search(r"const UI_PRESETS\s*=\s*\[(.*?)\]\s*as const", source, re.DOTALL)
    assert block_m, "UI_PRESETS не найдены в UniqualizerPage.tsx"
    block = block_m.group(1)

    presets = []
    depth = 0
    start = None
    for i, ch in enumerate(block):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                entry = block[start:i + 1]
                p: dict = {}
                for key, pattern in [
                    ("key",             r'key\s*:\s*"([^"]+)"'),
                    ("label",           r'label\s*:\s*"([^"]+)"'),
                    ("backendPreset",   r'backendPreset\s*:\s*"([^"]+)"'),
                    ("intensity",       r'intensity\s*:\s*"([^"]+)"'),
                    ("enableAllEffects",r'enableAllEffects\s*:\s*(true|false)'),
                ]:
                    m = re.search(pattern, entry)
                    if m:
                        p[key] = m.group(1)
                presets.append(p)
    return presets


class TestSimplePresets:
    def setup_method(self):
        self.src = RESEARCH_TSX.read_text(encoding="utf-8")
        self.presets = _parse_simple_presets(self.src)

    def test_has_six_presets(self):
        assert len(self.presets) == 6, f"Ожидалось 6 пресетов, найдено {len(self.presets)}"

    def test_all_presets_have_required_fields(self):
        required = {"label", "query", "region", "period", "accent"}
        for p in self.presets:
            missing = required - p.keys()
            assert not missing, f"Пресет {p.get('label', '?')} не имеет полей: {missing}"

    def test_labels_are_unique(self):
        labels = [p["label"] for p in self.presets]
        assert len(labels) == len(set(labels)), f"Дублирующиеся label: {labels}"

    def test_regions_are_valid(self):
        for p in self.presets:
            assert p["region"] in VALID_REGIONS, f"Некорректный регион '{p['region']}' в {p['label']}"

    def test_periods_are_positive_integers(self):
        for p in self.presets:
            period = int(p["period"])
            assert period >= 1, f"period должен быть >= 1, получено {period} в {p['label']}"

    def test_gambling_uses_kr_region(self):
        gambling = next((p for p in self.presets if p["label"] == "Gambling"), None)
        assert gambling is not None, "Пресет Gambling не найден"
        assert gambling["region"] == "KR"

    def test_gambling_period_is_2(self):
        gambling = next(p for p in self.presets if p["label"] == "Gambling")
        assert int(gambling["period"]) == 2

    def test_korea_sea_uses_kr_region(self):
        korea = next((p for p in self.presets if p["label"] == "Korea SEA"), None)
        assert korea is not None, "Пресет Korea SEA не найден"
        assert korea["region"] == "KR"

    def test_us_presets_exist(self):
        us_presets = [p for p in self.presets if p["region"] == "US"]
        assert len(us_presets) >= 2, "Должно быть минимум 2 пресета с регионом US"

    def test_accent_colors_are_hex(self):
        hex_re = re.compile(r"^#[0-9A-Fa-f]{6}$")
        for p in self.presets:
            assert hex_re.match(p["accent"]), f"Некорректный hex-цвет '{p['accent']}' в {p['label']}"

    def test_preset_click_uses_preset_region_not_state(self):
        """onClick должен передавать preset.region/period, а не state-переменные."""
        # Ищем конкретно строку с simple-preset-card и applyPreset
        # Проверяем что где-то после SIMPLE_PRESETS.map есть preset.region и preset.period
        simple_presets_map_block = re.search(
            r'SIMPLE_PRESETS\.map.*?simple-preset-card.*?applyPreset(.*?)simple-preset-copy',
            self.src, re.DOTALL
        )
        assert simple_presets_map_block, "SIMPLE_PRESETS.map с applyPreset не найден"
        block_text = simple_presets_map_block.group(0)
        assert "preset.region" in block_text, "onClick должен использовать preset.region"
        assert "preset.period" in block_text, "onClick должен использовать preset.period"


class TestUiPresets:
    def setup_method(self):
        self.src = UNIQUALIZER_TSX.read_text(encoding="utf-8")
        self.presets = _parse_ui_presets(self.src)

    def test_has_four_presets(self):
        assert len(self.presets) == 4, f"Ожидалось 4 UI_PRESETS, найдено {len(self.presets)}"

    def test_all_presets_have_required_fields(self):
        required = {"key", "label", "backendPreset", "intensity", "enableAllEffects"}
        for p in self.presets:
            missing = required - p.keys()
            assert not missing, f"UI_PRESET {p.get('key', '?')} не имеет полей: {missing}"

    def test_keys_are_unique(self):
        keys = [p["key"] for p in self.presets]
        assert len(keys) == len(set(keys)), f"Дублирующиеся key: {keys}"

    def test_backend_presets_are_valid(self):
        for p in self.presets:
            assert p["backendPreset"] in VALID_BACKEND_PRESETS, (
                f"backendPreset '{p['backendPreset']}' в {p['key']} не входит в {VALID_BACKEND_PRESETS}"
            )

    def test_intensities_are_valid(self):
        for p in self.presets:
            assert p["intensity"] in VALID_INTENSITIES, (
                f"intensity '{p['intensity']}' в {p['key']} не входит в {VALID_INTENSITIES}"
            )

    def test_maximum_preset_enables_all_effects(self):
        maximum = next((p for p in self.presets if p["key"] == "maximum"), None)
        assert maximum is not None, "Пресет 'maximum' не найден"
        assert maximum["enableAllEffects"] == "true", "maximum должен иметь enableAllEffects: true"

    def test_soft_preset_does_not_enable_all_effects(self):
        soft = next((p for p in self.presets if p["key"] == "soft"), None)
        assert soft is not None, "Пресет 'soft' не найден"
        assert soft["enableAllEffects"] == "false"

    def test_maximum_uses_ultra_preset(self):
        maximum = next(p for p in self.presets if p["key"] == "maximum")
        assert maximum["backendPreset"] == "ultra"

    def test_soft_uses_soft_preset(self):
        soft = next(p for p in self.presets if p["key"] == "soft")
        assert soft["backendPreset"] == "soft"

    def test_advanced_section_is_collapsed_by_default(self):
        """advancedOpen должен инициализироваться false."""
        assert re.search(
            r'useState\s*\(\s*false\s*\)',
            self.src
        ), "Должен быть useState(false) для advancedOpen"

    def test_apply_ui_preset_function_exists(self):
        assert "function applyUiPreset" in self.src, "applyUiPreset функция не найдена"

    def test_sidebar_uses_ui_preset_label(self):
        """Сайдбар должен показывать label из UI_PRESETS."""
        assert "UI_PRESETS.find" in self.src, "Сайдбар должен использовать UI_PRESETS.find"

    def test_preset_order_is_soft_medium_aggressive_maximum(self):
        keys = [p["key"] for p in self.presets]
        assert keys == ["soft", "medium", "aggressive", "maximum"], (
            f"Порядок пресетов неверный: {keys}"
        )


class TestProfilesPageStatusFilter:
    """Проверяем логику фильтрации в ProfilesPage через анализ TSX."""

    def setup_method(self):
        tsx = FRONTEND / "ProfilesPage.tsx"
        self.src = tsx.read_text(encoding="utf-8")

    def test_status_filter_state_exists(self):
        assert 'useState<"non_ready" | null>' in self.src, \
            "statusFilter state не найден"

    def test_filtered_rows_memo_exists(self):
        assert "filteredRows" in self.src, "filteredRows useMemo не найден"

    def test_filtered_rows_filters_non_ready(self):
        assert 'r.status !== "ready"' in self.src, \
            "filteredRows должен фильтровать по status !== 'ready'"

    def test_table_uses_filtered_rows(self):
        assert "filteredRows.map(" in self.src, \
            "Таблица должна использовать filteredRows.map, а не rows.map"

    def test_five_status_cards_exist(self):
        cards = re.findall(r'stat-card', self.src)
        # 5 карточек статусов
        assert len(cards) >= 5, f"Ожидалось ≥5 stat-card, найдено {len(cards)}"

    def test_prepare_profiles_button_exists(self):
        assert "Подготовить профили" in self.src, \
            "Кнопка 'Подготовить профили' не найдена"

    def test_button_toggles_filter(self):
        assert "non_ready" in self.src, "Фильтр non_ready не найден в компоненте"
