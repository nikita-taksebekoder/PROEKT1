# PROEKT1 — Правила работы над проектом

---

## Основные правила

0. **⚠ ДИЗАЙН — АБСОЛЮТНЫЙ ПРИОРИТЕТ ПРИ РАБОТЕ С UI:**
   Перед каждым изменением, связанным с внешним видом приложения — **ОСТАНОВИСЬ и выполни полное пиксель-за-пикселем сравнение** с `appDESIGN/design-preview.html`.

   **Обязательный чеклист сравнения (проверять ВСЁ, без исключений):**
   - [ ] Шрифт: семейство, размер в pt, вес (400/500/600/700), цвет, `letter-spacing`, `line-height`, регистр (upper/lower)
   - [ ] Фон элемента: точный `rgba()` или градиент, наличие radial-gradient блобов, grain-текстура
   - [ ] Граница: толщина (всегда 1px), цвет `rgba()`, `border-radius` в px
   - [ ] Отступы: `padding` по всем 4 сторонам, `gap`, `margin` — каждый в px
   - [ ] Размеры: ширина и высота в px для фиксированных элементов
   - [ ] Тени и свечения: все слои `box-shadow` / `text-shadow` с точными радиусами и цветами
   - [ ] Иконка: размер SVG, `stroke-width`, тип (`stroke` vs `fill`), цвет, анимация
   - [ ] Разделители: высота (1px), точный `rgba()` с нужной прозрачностью
   - [ ] Состояния: hover, active, disabled, focus — каждое состояние отдельно
   - [ ] Пропорции колонок и flex-соотношения элементов

   **Порядок работы с UI:**
   1. Открыть `design-preview.html` и найти нужный элемент
   2. Скопировать **все** CSS-свойства элемента дословно
   3. Перевести в QSS / QPainter / QGraphicsEffect
   4. Запустить приложение, сделать скриншот
   5. Визуально сравнить скриншот с HTML-макетом — каждый пиксель, каждый отступ, каждый цвет
   6. Если есть хоть малейшее расхождение — **исправить до полного совпадения**

   Любое «приблизительно», «похоже», «почти так же» — **недопустимо**. Только точное соответствие.

1. **Экспертиза:** Я эксперт в разработке прошивок ESP32 (ESP-IDF, FreeRTOS, NimBLE) и приложений на PySide6/Python.

2. **Язык:** Все ответы всегда на **русском языке**.

3. **Краткость:** Ответ — только главное. Без воды. Допускается 1–2 практических совета сверх задачи.

4. **Актуальность дерева:** Любые изменения в проекте (новые файлы, функции, GPIO, NVS-ключи, задачи, команды протокола) **немедленно отражаются в `PROEKT1 tree.md`**.

5. **Стабильность при изменениях:** Любое внесение изменений в функционал обязано сохранять работоспособность остальных функций — изменения не должны ломать или ухудшать другой функционал. Каждое изменение должно повышать стабильность и надёжность приложения и прошивки. Если изменение потенциально ломает одну часть ради исправления другой (конфликт интересов), вы должны получить ЯВНОЕ предупреждение с описанием рисков и компромиссов и подтверждение перед применением.

---

## Правила разработки прошивки (ESP32)

5. **Синхронность протокола:** UUID, форматы пакетов и команды в прошивке (`main.c`) и приложении (`PROEKT1.py`) должны быть **идентичны**. При изменении протокола — менять оба места одновременно.

6. **Версия NVS-структур:** При любом изменении `curve_cfg_t`, `led_profile_t`, `pump_hours_t` — **инкрементировать версию** (`version` поле) и обновить ключ (`cfg_v2` и т.д.) чтобы избежать загрузки устаревших данных.

7. **ISR-безопасность:** В ISR (`tach_isr`, IRAM_ATTR) — **только атомарные операции**, без `ESP_LOG*`, без malloc, без mutex.

8. **Стек задач:** При добавлении локальных буферов в задачу — проверять, не превышает ли суммарный стек лимит. Ориентир: uart_rx=3072, oled=4096, control=4096.

9. **Пины при старте:** Любой выходной GPIO, который может «дёрнуть» нагрузку — **пинать в LOW в самом начале `app_main()`**, до любой другой инициализации (как FAN/PUMP GPIO).

10. **Forced-stop guard:** После команды SP — всегда выставлять `g_forced_stop_deadline_ms`. Во время продувки (purge) guard **не блокирует** помпу/клапан.

---

## Правила разработки приложения (PySide6 / Python)

10.1. **Дизайн UI — ГЛАВНЫЙ ПРИНЦИП:** Визуальный результат в приложении (`PROEKT1.py`) должен **на 100% совпадать** с макетом `appDESIGN/design-preview.html`. HTML-макет — единственный источник правды по дизайну. Любое расхождение — баг, подлежащий немедленному исправлению. Функционал при этом должен оставаться полностью рабочим.

10.2. **Цветовая палитра (строго по макету):**
   - `#8bd5ff` — голубой акцент (CPU, Вода, ссылки)
   - `#cdbdff` — фиолетовый светлый (GPU, Primary-кнопки, слайдеры)
   - `#7c4dff` — Primary-container (активный nav, кнопки действий, обводка фокуса)
   - `#ffb4ab` — Error/Danger (кнопка продувки, опасные действия)
   - `#e1e0ff` — основной текст
   - `rgba(202,195,216,0.7)` — второстепенный текст / подписи
   - `#0f112b` / `#0a0b20` — фоновый цвет окна
   - `rgba(14,16,40,0.65)` — `--card-bg` (базовый фон карточек)

10.3. **Структура окна (строго по макету):**
   - Окно: `1100×760 px`, `border-radius: 24px`, без системных рамок, тёмный градиент.
   - **Sidebar** (`self.sidebar`): `244 px` фиксированная ширина, `rgba(18,19,46,0.7)`, правая граница `rgba(255,255,255,0.055)`. Содержит: лого, 4 nav-кнопки, кнопку `ПРОДУВКА СИСТЕМЫ`, кнопку `ЛОГИ`.
   - **Main area**: flex-1, padding `18/24/24/24 px`, gap `20 px`. Содержит: header + `QStackedWidget`.
   - **Header**: 44 px, заголовок страницы + subtitle (голубой) + кнопки окна (свернуть/закрыть).
   - **Dashboard card** (`self.dashboard_card`): `border-radius: 24px`, сетка 7:5 (left-col : right-col). Left: температуры (3 MetricCard) + вентиляторы (2 FanCard) + info-card. Bottom-bar: TriStateSwitch (СТОП / РАБОТА / ПРОДУВКА).
   - **Settings card** (`self.settings_card`): `border-radius: 24px`, двухколоночная сетка (`set-grid`). Левая col: подключение, запуск, защита. Правая col: моточасы, подсветка/дисплей, локализация/темы. Footer: ЛОГИ + отмена + сохранить.

10.4. **Компоненты UI (имена `self.xxx` в PySide6, строго по макету):**
   - `self.sidebar` — боковая панель
   - `self.title_lbl` / `self.status_lbl` — «ПРОЕКТ 1» / «v2.4 · STABLE»
   - `self.sidebar_buttons["dashboard" | "pump" | "led" | "settings"]` — nav-кнопки
   - `self.btn_purge_system` — красная кнопка продувки внизу сайдбара
   - `self.btn_log` — кнопка «ЛОГИ»
   - `self.page_title` / `self.page_subtitle` — заголовок и subtitle в header
   - `self.btn_win_min` / `self.btn_win_close` — кнопки управления окном
   - `self.cpu_card` / `self.cpu_label` — MetricCard CPU (акцент `#8bd5ff`)
   - `self.gpu_card` / `self.gpu_label` — MetricCard GPU (акцент `#cdbdff`)
   - `self.water_card` / `self.water_label` — MetricCard Вода (акцент `#8bd5ff`)
   - `self.fan1_card` / `self.fan1_val` — FanCard Вентилятор 1 (RPM)
   - `self.fan2_card` / `self.fan2_val` — FanCard Вентилятор 2 (RPM)
   - `self.info_card` — InfoCard: Цели + бэйдж связи + профиль + статус гидролиний
   - `self.targets_lbl` / `self.link_badge` / `self.profile_lbl` / `self.loop_label` — элементы InfoCard
   - `self.tri_switch` — TriStateSwitch: СТОП (0) / РАБОТА (1) / ПРОДУВКА (2)
   - `self.transport_combo` — ComboBox «BLE / USB»
   - `self.stack` — QStackedWidget

10.5. **Glassmorphism-карточки:** Все карточки (`metric-card`, `fan-card`, `info-card`, `set-card`) используют: `border: 1px solid rgba(255,255,255,0.07)`, `box-shadow: inset 0 1px 0 rgba(255,255,255,0.06), 0 6px 18px rgba(0,0,0,0.25)`, уникальные радиальные gradients-блобы для каждой карточки (перевести в QSS `background` через `qlineargradient` или SVG-слой). Зерно-текстура (grain overlay) эмулировать псевдоэлементом или SVG-фоном.

10.6. **Температурная окраска баров:** Синий `#8bd5ff` при ≤30°C → плавный переход через розовый `#ff85c2` при 45–65°C → красный `#ff2828` при ≥85°C. Реализовывать через QSS динамическое обновление цвета или setStyleSheet при обновлении значений.

10.7. **Темы оформления (3 варианта):**
   - **Фиолетовый** (по умолчанию): фон `#0a0b20`, карточки `rgba(14,16,40,0.65)`
   - **Графит**: фон `#0a0b0e`, карточки `rgba(20,21,26,0.72)`, окно `#1d1e22→#101116`
   - **Белый**: фон `#e8ebf3`, карточки `rgba(255,255,255,0.78)`, текст `#1a1b2e`
   Смена темы — через `config.json` + динамический QSS на `QApplication`.

10.8. **CSS → QSS трансляция:** `border-radius` → напрямую; `rgba()` → `rgba()`; `linear-gradient` → `qlineargradient()`; `font-weight: 700` → `font-weight: bold`; `letter-spacing` → через QFont или QSS `letter-spacing`; box-shadow — через QGraphicsDropShadowEffect или SVG-обёртку. Шрифт: `Inter` (если доступен) или `Segoe UI`.

10.9. **Типографика (точные значения из макета):**
   | Элемент | Размер | Вес | Цвет | Letter-spacing |
   |---|---|---|---|---|
   | `logo-title` | 13pt | 700 | `#ffffff` | 0.5px |
   | `logo-sub` | 8pt | 600 | `rgba(139,213,255,0.78)` | 1.5px |
   | `nav-text` (обычный) | 10pt | 600 | `rgba(202,195,216,0.82)` | 0.2px |
   | `nav-text` (активный) | 10pt | 700 | `#ffffff` | 0.2px |
   | `page-title` | 13pt | 700 | `#ffffff` | 1px |
   | `page-subtitle` | 9pt | 600 | `rgba(139,213,255,0.78)` | 1px |
   | `section-caption` | 8pt | 700 | `rgba(202,195,216,0.65)` | 2px |
   | `metric-cap` / `fan-cap` / `info-cap` | 8pt | 700 | `rgba(202,195,216,0.7)` | 1.5px |
   | `metric-val` (число температуры) | 22pt | 700 | accent-цвет | — |
   | `metric-unit` (°C) | 10pt | 400 | accent-цвет | — |
   | `fan-val` (RPM число) | 20pt | 600 | `#e1e0ff` | — |
   | `fan-unit` (RPM) | 8pt | 700 | `rgba(202,195,216,0.7)` | 1px |
   | `info-val` (цели/профиль) | 11pt | 400 | `#e1e0ff` | — |
   | `loop-status` | 11pt | 400 | `#8bd5ff` | — |
   | `link-badge` | 9pt | 700 | `#cdbdff` (active) | 1px |
   | `set-head` | 8pt | 700 | `rgba(202,195,216,0.60)` | 2px |
   | `set-row-label` | 10pt | 500 | `#e1e0ff` | — |
   | `set-row-hint` | 8.5pt | 400 | `rgba(202,195,216,0.55)` | — |
   | `set-slider-val` | 11pt | 700 | `#cdbdff` | — (tabular-nums) |
   | `btn-purge` | 9pt | 700 | `#ffb4ab` | 1.4px |
   | `btn-log` | 8pt | 700 | `rgba(202,195,216,0.67)` | 2.5px |
   | `hours-big` (наработка) | 22pt | 700 | `#ffffff` | 1px (моноширинный) |
   | `hours-pct` | 22pt | 700 | gradient `#8bd5ff→#cdbdff` | — |
   | `set-btn` (кнопки в настройках) | 10pt | 600 | — | 1px, lowercase |

   Все элементы с `letter-spacing` ≥ 2px и верхний регистр — текст всегда UPPER CASE. Моноширинный шрифт (`JetBrains Mono`, `Consolas`) — только для `hours-big` и `hours-pct`.

10.10. **Формы подложек и скруглений (точные значения из макета):**
   - **Окно приложения:** `border-radius: 24px`, `border: 1px solid rgba(255,255,255,0.12)`, без системных рамок
   - **Dashboard card / Settings card:** `border-radius: 24px`, `background: rgba(28,29,56,0.67)`, `border: 1px solid rgba(255,255,255,0.07)`, padding dashboard: `30px 34px 26px 34px`, padding settings: `22px 28px 18px`
   - **MetricCard (CPU/GPU/Water):** `border-radius: 16px`, `padding: 10px 12px`, gap внутри `4px`
   - **FanCard:** `border-radius: 16px`, `padding: 12px 14px`
   - **InfoCard:** `border-radius: 18px`, `padding: 14px 18px`
   - **Set-card (карточки настроек):** `border-radius: 18px`, `padding: 14px 18px 16px`
   - **Nav-кнопка:** `height: 46px`, `border-radius: 12px`, `margin-bottom: 4px`. Активная: `background: rgba(124,77,255,0.165)`. Ховер: `rgba(255,255,255,0.07)`
   - **Logo icon:** `34×34px`, `border-radius: 10px`, `background: rgba(124,77,255,0.21)`, `border: 1px solid rgba(124,77,255,0.35)`
   - **Кнопка ПРОДУВКА:** `height: 42px`, `border-radius: 12px`, `background: rgba(255,180,171,0.063)`, `border: 1px solid rgba(255,180,171,0.275)`
   - **Win-кнопки (свернуть/закрыть):** `27×27px`, `border-radius: 8px`, `background: rgba(255,255,255,0.055)`, `border: 1px solid rgba(255,255,255,0.086)`
   - **Link-badge:** `padding: 4px 12px`, `border-radius: 12px`. Active: `background: rgba(124,77,255,0.22)`, `border: 1px solid rgba(124,77,255,0.63)`. Inactive: `background: rgba(255,255,255,0.07)`, `border: 1px solid rgba(255,255,255,0.11)`
   - **TriStateSwitch:** `height: 48px`, `border-radius: 14px`, `background: rgba(10,11,37,0.63)`, `border: 1px solid rgba(255,255,255,0.1)`, `padding: 4px`, gap `4px`. Сегменты: `border-radius: 11px`
   - **Toggle:** `44×24px`, `border-radius: 14px`. Ручка: `18×18px`, `border-radius: 50%`, `top: 2px`, OFF: `left: 2px`, ON: `left: 22px`
   - **Dropdown-кнопка:** `border-radius: 10px`, `padding: 7px 12px`. Open: `border-color: #7c4dff`. Меню: `border-radius: 10px`, items: `border-radius: 7px`, `padding: 4px` (внутри)
   - **Slider track:** `height: 6px`, `border-radius: 3px`. Thumb: `16×16px`, `border-radius: 50%`, `background: #ffffff`, `border: 2px solid #7c4dff`
   - **Fan icon circle:** `44×44px`, `border-radius: 22px`, `background: rgba(49,50,78,0.63)`, `border: 1px solid rgba(255,255,255,0.086)`

10.11. **Разделители (строго по макету):**
   - **Горизонтальный dash-sep** (между grid и bottom-bar в dashboard): `height: 1px`, `background: rgba(255,255,255,0.07)`
   - **info-sep** (внутри InfoCard, между Цели и Профиль): `height: 1px`, `background: rgba(255,255,255,0.07)`
   - **Разделители строк в set-card** (между соседними set-row): `border-top: 1px solid rgba(255,255,255,0.03)` — ещё тоньше, почти невидимые
   - **Разделитель footer настроек** (над кнопками сохранить/отмена): `border-top: 1px solid rgba(255,255,255,0.05)`, `padding-top: 14px`, `margin-top: 14px`
   - **Sidebar border-right** (граница сайдбара): `1px solid rgba(255,255,255,0.055)` — самая тонкая, почти незаметная
   - Все разделители — только горизонтальные линии, без закруглений, без теней.

10.12. **Иконки (точные характеристики из макета):**
   - **Nav-иконки:** SVG `20×20px`, только `stroke`, `stroke-width: 1.4`, `stroke-linecap: round`, цвет `currentColor` (наследует от `nav-text`). Стиль — линейный, без заливки.
   - **Section caption иконки:** SVG `12×12px`, в основном `fill: currentColor` (заполненные). Значки: термометр, вентилятор (4 лопасти), молния, круг с буквой i.
   - **Fan SVG (анимированный):** `26×26px` внутри круга `44×44px`. Центральная окружность + 4 одинаковых лезвия, `stroke: currentColor`, `stroke-width: 1.4`. Анимация: `fan-spin 1.8s linear infinite`, `transform-origin: 13px 13px` (центр SVG).
   - **Logo иконка:** символ `✦` (FOUR POINTED BLACK STAR), `font-size: 16px`, `color: #cdbdff`.
   - **Win-кнопки:** текстовые символы `—` (свернуть) и `✕` (закрыть), `font-size: 11px`, `color: #cac3d8`.
   - **btn-log иконка:** SVG `14×14px`, горизонтальные полосы (список) + стрелка вправо, `opacity: 0.7–0.9`.
   - **Set-head иконки:** SVG `12×12px`, уникальные для каждой секции: подключение (три линии), запуск (треугольник play), защита (щит), часы (окружность + стрелки), свет (звезда с лучами), глобус (эллипсы+линии).
   - **Стрелка dropdown:** SVG `10×6px`, `stroke: #cdbdff`, `stroke-width: 1.2`, вращается 180° при открытии.
   - Все SVG иконки — только inline (не img/icon-font). Цвет всегда через `currentColor` или явный hex из палитры.

10.13. **Пропорции и отступы (точные значения из макета):**
   - **Sidebar:** ширина `244px` (фиксированная, `flex-shrink: 0`), padding `30px 16px 22px 20px`
   - **Main area:** padding `18px 24px 24px 24px`, gap `20px` (между header и card)
   - **Logo margin-bottom:** `34px` (от лого до первой nav-кнопки)
   - **Nav-кнопки:** `height: 46px`, `margin-bottom: 4px`, `padding-left: 13px` (inner), gap иконка↔текст `12px`
   - **Dashboard card:** padding `30px 34px 26px 34px`; grid gap (L↔R колонки) `28px`; left-col:right-col = `flex: 7` : `flex: 5`; gap внутри left-col `22px`; gap внутри right-col `22px`
   - **Metric row:** gap `12px` (между тремя карточками). Bar высота `4px`, dot-маркер `7×7px`
   - **Fan row:** gap `12px`
   - **Section caption:** `margin-bottom: -8px` (плотное прилегание к следующей строке)
   - **Info card:** gap внутренних секций `10px`; info-top и info-bot — flex, gap `10px`
   - **TriStateSwitch:** внутренний padding `4px`, gap сегментов `4px`
   - **Bottom bar (режим работы):** flex column, gap `14px`, `padding-top: 4px`
   - **Settings set-grid:** `grid-template-columns: 1fr 1fr`, gap `14px`; set-col gap `14px`
   - **Set-row:** `padding: 6px 0`, gap `14px` (label↔control)
   - **Settings footer:** gap `10px`, `padding-top: 14px`
   - **Scrollbar (settings):** ширина `6px`, `border-radius: 3px`, thumb: `rgba(205,189,255,0.15)`, hover: `rgba(205,189,255,0.30)`, track: transparent

10.14. **Свечения и тени (точные значения из макета):**
   - **Окно (внешняя тень):** `box-shadow: 0 40px 120px rgba(0,0,0,0.7)` — глубокая, размытая
   - **Карточки (верхний shimmer):** `inset 0 1px 0 rgba(255,255,255,0.06)` — тонкая белая линия сверху
   - **Карточки (нижняя тень):** `0 6px 18px rgba(0,0,0,0.25)`
   - **Температурный бар (свечение трека):** `box-shadow: 0 0 5px 1px rgba(accent,0.55)` на fill-элементе
   - **Dot-маркер конца бара (3-слойное свечение):**
     - Внутренний: `0 0 6px 3px accent` (яркое ядро)
     - Средний: `0 0 14px 5px rgba(accent,0.55)` (ореол)
     - Внешний: `0 0 24px 8px rgba(accent,0.25)` (рассеяние)
   - **Toggle ON:** `box-shadow: 0 0 14px rgba(124,77,255,0.45)` на всём виджете
   - **TriStateSwitch сегменты (тени при активации):**
     - СТОП: `box-shadow: 0 2px 10px rgba(180,60,70,0.27)`
     - РАБОТА: `box-shadow: 0 2px 10px rgba(124,77,255,0.27)`
     - ПРОДУВКА: `box-shadow: 0 2px 10px rgba(0,189,253,0.27)`
   - **Slider thumb:** `box-shadow: 0 0 8px rgba(124,77,255,0.55), 0 0 2px rgba(0,0,0,0.4)`
   - **Dropdown open (focus ring):** `box-shadow: 0 0 0 3px rgba(124,77,255,0.18)`
   - **Dropdown меню:** `box-shadow: 0 10px 32px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.07)`
   - **hours-big (текстовая тень):** `text-shadow: 0 0 18px rgba(205,189,255,0.25)`
   - **Primary button:** `box-shadow: 0 4px 14px rgba(124,77,255,0.45), inset 0 1px 0 rgba(255,255,255,0.18)`
   - **Primary button hover:** `box-shadow: 0 6px 18px rgba(124,77,255,0.55)`
   - Все свечения реализовывать через `QGraphicsDropShadowEffect` или кастомный `paintEvent` с QPainter (box-shadow прямого аналога в QSS нет — использовать эффекты или SVG-обёртки).

11. **Паритет BLE и USB:** Любой функционал, реализованный через BLE, **обязан работать идентично через USB** (и наоборот). Новая команда, настройка, уведомление — всегда реализуются в **обоих транспортах** (`BLETempSender` и `USBTempSender`) одновременно. Асимметрия BLE/USB недопустима.

12. **Потокобезопасность GUI:** Обновление виджетов из BLE/USB-потоков — **только через Signal/Slot** или `QTimer`. Прямые вызовы Qt из не-GUI треда запрещены.

13. **Бинарный протокол:** Все пакеты собирать через `struct.pack('<...')` (little-endian). Никакого текстового протокола.

14. **LHM зависимость:** `LibreHardwareMonitor.exe` читается через CSV-лог. При добавлении новых метрик — обновлять `_pick_cpu_index()` / `_pick_gpu_index()` и проверять формат лога.

15. **config.json и curves.json:** Всегда читать через `try/except` с fallback на дефолты. Никогда не падать при отсутствии или повреждении файла.

---

## Правила безопасности (аппаратная часть)

16. **Защита контура (loop protection):** Перед командой PG/ST всегда проверять `g_loop_ok` если `g_loopprot_enabled`. Логика запрета — в прошивке, дублировать в UI не нужно.

17. **WATER_TEMP_CRIT_C=50°C:** При достижении — err6 на OLED. Добавление аппаратной аварийной логики (принудительный стоп) требует отдельного согласования.

---

## Правила документирования

18. **`PROEKT1 tree.md`** — единственный источник правды о структуре проекта. Обновлять при каждом PR/коммите.

19. **Комментарии в коде:** Критичные места (ISR, NVS-ключи, GPIO-числа, calibration constants) — **всегда** с комментарием почему именно это значение.
