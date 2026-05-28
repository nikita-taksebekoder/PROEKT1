# PROEKT1 — Полное дерево проекта с разметкой

> **Назначение проекта:** Контроллер системы жидкостного охлаждения ПК на базе ESP32 (ESP-IDF 5.3+, NimBLE).
> Управляет вентиляторами, помпой, клапаном продувки, WS2812 LED-подсветкой, OLED-дисплеем (SSD1312),
> датчиком температуры воды (DS18B20) и защитой контура (петля целостности шланга).
> Связь с ПК: BLE (NimBLE) и USB/UART. На стороне ПК — приложение PySide6 (Windows).

**Изменения:**

- 2026-05-28 (DPI-aware WebEngine на масштабах Windows 125/150/175%): UI — `appPROEKT1/PROEKT1.py`. Исправлена обрезка интерфейса при системном масштабе Windows выше 100%: `_apply_web_view_native_round_rgn()` больше не строит `SetWindowRgn(CreateRoundRectRgn(...))` по логическим `QWidget.width()/height()`, а берёт фактический Win32 client rect через `GetClientRect(HWND)` и масштабирует радиус 24px по отношению native/logical размеров. Иначе на 150% регион получался меньше реальной Chromium-поверхности, WebEngine рисовался только в левом верхнем углу, а справа/снизу была видна подложка `_RoundedWindowFrame`. Добавлены сигналы смены DPI/геометрии экрана (`logicalDotsPerInchChanged`, `geometryChanged`, `availableGeometryChanged`) с переустановкой WebEngine region, а до создания `QApplication` выставлена `HighDpiScaleFactorRoundingPolicy.PassThrough`.

- 2026-05-26 (нативное hardware-клипование Chromium-HWND через SetWindowRgn): UI — `appPROEKT1/PROEKT1.py`. Добавлен `_apply_web_view_native_round_rgn()`: на каждом `resizeEvent` и после выхода из fullscreen ставит `CreateRoundRectRgn(0,0,w+1,h+1,48,48)` через `SetWindowRgn` на HWND QWebEngineView И на все его дочерние нативные окна (Chromium GPU/render/input — обходим через `EnumChildWindows`). Корневая причина: Qt per-pixel alpha скругляет только MainWindow, а Chromium-композитор рендерит OPAQUE-пиксели в прямоугольные границы своего HWND, которые после fullscreen-циклов накапливают GPU-кэш и видны как «второй слой углов». `SetWindowRgn` — hardware-клип, не зависит от GPU-состояния. Лёгкая зубчатость HRGN маскируется антиалиасингом `_RoundedWindowFrame` поверх. `_reset_web_view_clip()` теперь после `clearMask()` повторно применяет region.

- 2026-05-26 (фикс ctypes argtypes + 1px geometry-nudge): UI — `appPROEKT1/PROEKT1.py`. `_force_native_redraw()` ранее молча падал на 64-bit Windows, потому что `SetWindowPos`/`RedrawWindow`/`InvalidateRect` без явных `argtypes` усекали HWND до 32-bit и вызовы шли в неверное окно. Добавлены `argtypes/restype` (`wintypes.HWND`, `c_void_p`, `wintypes.UINT/BOOL`). Дополнительно введён `_force_geometry_nudge()`: на 1 пиксель растягиваем `setGeometry`, на следующем тике возвращаем — гарантированно триггерит Qt resizeEvent + Chromium GPU surface rebuild + DWM recomposition, что окончательно сбрасывает «застрявшие» углы после выхода из fullscreen. Запускается на 80 и 260 мс таймерах в `_on_web_fullscreen_requested`.

- 2026-05-26 (форсированная рекомпозиция DWM после fullscreen): UI — `appPROEKT1/PROEKT1.py`. Добавлен `_force_native_redraw()` (Win32: `SetWindowPos(SWP_FRAMECHANGED)` + `RedrawWindow(RDW_INVALIDATE|RDW_FRAME|RDW_ALLCHILDREN|RDW_UPDATENOW|RDW_ERASE)`). На выходе из веб-fullscreen вызывается синхронно и затем по таймерам 0/60/180/400 мс. Чинит «застывшие углы» после первого выхода: DWM держал в кэше прежний фрейм, и без внешней рекомпозиции (которая ранее срабатывала только от Win+Shift+S) углы виднелись до следующего цикла. Теперь приложение само инициирует ту же рекомпозицию сразу после выхода.

- 2026-05-26 (fullscreen без потери layered-alpha): UI — `appPROEKT1/PROEKT1.py`. Полностью убраны вызовы `showFullScreen()`/`showNormal()` для веб-fullscreen — на Windows они пересоздавали нативный HWND и Qt терял `WS_EX_LAYERED`, после чего ни `setAttribute(WA_TranslucentBackground)`, ни `apply_windows_backdrop()` уже не возвращали per-pixel alpha → снаружи 24px Qt-силуэта появлялась «полноценная» рамка с DWM-радиусом. Теперь `_on_web_fullscreen_requested` входит во «fullscreen» простым `setGeometry(screen.geometry())` (window state не трогается), а выходит обратным `setGeometry(restore_geom)`. Frameless + per-pixel alpha сохраняются непрерывно, MainWindow остаётся `DWMWCP_DONOTROUND`, артефактов «вторых углов» нет. Метод `_reapply_translucent_window()` (была попытка восстановить layered постфактум) удалён из вызовов, но сам по-прежнему доступен для подстраховки в showEvent.

- 2026-05-26 (восстановление per-pixel alpha после fullscreen — заменено): UI — `appPROEKT1/PROEKT1.py`. После `showNormal()` Qt на Windows сбрасывал `WS_EX_LAYERED` и DWM возвращал стандартное скругление углов MainWindow → снаружи Qt-24px-пути проявлялись «полноценные углы» (рамка с другим радиусом). Добавлен `_reapply_translucent_window()`: повторно ставит `WA_TranslucentBackground` / `WA_NoSystemBackground` на MainWindow и central, вызывает `apply_windows_backdrop(self)` (заново форсит `DWMWCP_DONOTROUND` и `DWMWA_BORDER_COLOR=COLOR_NONE`). Вызывается из `_on_web_fullscreen_requested` сразу после `showNormal()/showMaximized()` и далее по таймерам `0/60/180/400 ms`, чтобы перекрыть момент, когда Qt сам пересоздаёт нативный HWND.

- 2026-05-26 (истинная причина «язычков» в углах — конфликт DWM/Qt радиусов): UI — `appPROEKT1/PROEKT1.py`. Найдена настоящая причина видимых «прозрачных язычков» и «окрашенных подложек с другим радиусом» по углам: `_apply_rounded_mask()` вызывал `_set_native_corner_preference(not self.isFullScreen())`, что ставило `DWMWCP_ROUND` на MainWindow в обычном режиме. Windows 11 вырезал нативный ~8px внешний силуэт вокруг фрейма, а Qt-путь `_RoundedWindowFrame` вырезал внутри 24px — между этими двумя обводами оставалось угловое кольцо alpha=0 («язычок со вторым радиусом»), а после fullscreen Chromium-backing порой перекрашивал его в градиент. Решение: MainWindow теперь всегда `DWMWCP_DONOTROUND` (форма определяется только Qt per-pixel alpha 24px); аргумент `rounded` в `_set_native_corner_preference` оставлен для совместимости, но игнорируется.

- 2026-05-26 (чистые углы — убран лишний слой backing): UI — `appPROEKT1/PROEKT1.py`. Найдена причина «второго радиуса» в углах: WebEngine рисовал непрозрачный прямоугольный фон страницы (через `page().setBackgroundColor('#121431')` и `html, body { background: gradient }`) под HTML `.app-window` с радиусом 24px. Прямоугольник торчал из-под скругления `.app-window`, а Qt-фрейм с тем же 24px-радиусом срезал его снаружи — отсюда видимая «подложка с другим радиусом» и до, и после fullscreen. Решение: в обычном режиме `setBackgroundColor(0,0,0,0)`, runtime-CSS `html, body.proekt1-runtime { background:transparent !important }`, а `_refresh_web_view_surface()` после выхода из fullscreen возвращает прозрачные `documentElement/body` и больше не навешивает inline `border-radius/overflow/clip-path` на `#app-window` (свойства уже зафиксированы в runtime-CSS). Тёмный fullscreen-backdrop `#0a0b20` сохранён только в правиле `body.proekt1-runtime.fullscreen`. В итоге снаружи скруглённого `.app-window` пиксели полностью прозрачные, а под ним сглаженный Qt-фрейм с тем же 24px — края совпадают, лишних «язычков» нет.

- 2026-05-26 (откат увеличенного радиуса углов): UI — `appPROEKT1/PROEKT1.py`. Временный хак с радиусом 36px показал прямоугольный backing/слой под WebEngine уже в обычном режиме. Видимый радиус возвращён к макету 24px для `_RoundedWindowFrame`, `_RoundedSidebar`, runtime-CSS `.app-window` и repaint-helper (`border-radius:24px` / `clip-path:inset(0 round 24px)`). Это сохраняет исходную схему из MD: прозрачное верхнее окно, антиалиасный Qt-фон и без пиксельных `QRegion`-масок.

- 2026-05-26 (увеличенный радиус HTML-углов — заменено): UI — `appPROEKT1/PROEKT1.py`. После отказа от пиксельного `QRegion`-клиппинга внешний край WebEngine стал гладким через DWM, но на HTML-радиусе оставался небольшой compositor-стык. Промежуточно радиус видимого окна увеличивался с 24px до 36px, но это стало постоянно раскрывать прямоугольный слой под HTML-окном; решение заменено откатом к 24px.

- 2026-05-26 (гладкие углы после fullscreen): UI — `appPROEKT1/PROEKT1.py`. Убран пиксельный `QRegion`-клиппинг WebEngine/MainWindow, который убирал чёрные углы, но давал ступенчатое/рваное скругление после выхода из fullscreen. Вместо этого обычный режим включает сглаженное DWM-скругление верхнего HWND (`DWMWCP_ROUND`), а fullscreen временно возвращает `DWMWCP_DONOTROUND`. `QWebEngineView` и `MainWindow` теперь очищают QWidget/Win32 region-mask, чтобы Chromium не резался пиксельной маской; helper `_refresh_web_view_surface()` после выхода из fullscreen повторно выставляет фон страницы и форсирует DOM/compositor repaint без скрытия окна.

- 2026-05-26 (native-mask главного окна для WebEngine — заменено): UI — `appPROEKT1/PROEKT1.py`. Промежуточная попытка с `QRegion`-маской для `QWebEngineView`/`MainWindow` убирала чёрные квадратные углы Chromium после fullscreen, но давала ступенчатое скругление. В текущей реализации эта логика удалена и заменена DWM-скруглением (`DWMWCP_ROUND`/`DWMWCP_DONOTROUND`) плюс `_refresh_web_view_surface()`.

- 2026-05-26 (чёрные углы WebEngine после fullscreen — заменено): UI — `appPROEKT1/PROEKT1.py`. Первичный фикс с `_apply_web_view_clip()` и `QRegion`-маской для `QWebEngineView` оказался недостаточным для Chromium HWND-поверхности и позже был удалён. Текущий подход: не использовать пиксельные Qt-маски, а сглаженно клиповать верхнее окно через DWM и в обычном режиме заполнять WebEngine backing градиентом окна, чтобы повторные циклы fullscreen не показывали чёрные углы.

- 2026-05-26 (восстановление масштаба после fullscreen): UI — `appPROEKT1/PROEKT1.py`. Исправлен баг после выхода из fullscreen WebEngine: Qt-окно возвращалось из `showFullScreen()`, но DOM мог оставаться в состоянии `body.fullscreen`, из-за чего интерфейс сохранял `scale(1.2)` и обрезался в сжатом окне. Добавлен `_sync_web_fullscreen_state()`, который принудительно синхронизирует класс fullscreen и иконку кнопки с Qt-состоянием; runtime-CSS обычного режима теперь явно задаёт `.app-window` `left:0`, `top:0`, `transform:none` при размере `100vw/100vh`.

- 2026-05-26 (нативный fullscreen WebEngine): UI — `appPROEKT1/PROEKT1.py`. Найдена причина, почему HTML-кнопка fullscreen масштабировала интерфейс только внутри текущего окна: `requestFullscreen()` внутри `QWebEngineView` требует включённого `FullScreenSupportEnabled` и принятия сигнала `fullScreenRequested`; без этого Qt не переводит родительское окно на весь монитор. Добавлен обработчик `_on_web_fullscreen_requested()`, который принимает запрос Chromium, вызывает `showFullScreen()`/возврат к прежней геометрии, а runtime-CSS теперь в режиме fullscreen возвращает `.app-window` к 1100×760, центрирует и масштабирует на 20% поверх полноэкранного фона `#0a0b20`.

- 2026-05-26 (фикс утечки RMT-каналов WS2812): Прошивка — `main/main.c`, `managed_components/espressif__led_strip/src/led_strip_rmt_dev.c`. Исправлен сценарий восстановления LED-strip после зависания RMT: перед `rmt_del_channel()` драйвер теперь пытается выключить RMT-канал через `rmt_disable()`, а `led_task` больше не сбрасывает `g_led_strip` в `NULL`, если `led_strip_del()` фактически не освободил ресурс. Это устраняет накопление занятых TX-каналов и повторяющиеся ошибки `rmt_tx_register_to_group: no free tx channels` / `led_strip_new_rmt_device failed: 261`.

- 2026-05-26 (видимый экран завершения поверх WebEngine): UI — `appPROEKT1/PROEKT1.py`. Исправлен случай, когда при клике по HTML-крестику не был виден shutdown-loader: перед показом `_LifecycleOverlay.show_shutdown()` теперь скрывается `QWebEngineView`, потому что Chromium/native surface на Windows может перекрывать обычные QWidget-слои даже после `raise_()`. Overlay принудительно `repaint()`-ится и получает короткую гарантированную паузу 260 мс перед graceful cleanup, чтобы экран завершения был заметен даже при быстром закрытии. BLE/USB-протокол не менялся.

- 2026-05-26 (минимальный theme-aware загрузчик): UI — `appPROEKT1/PROEKT1.py`. `_LifecycleSpinner` упрощён: вместо орбитальных точек/двух дуг теперь рисуется компактное тонкое кольцо с одной вращающейся дугой, маленькой точкой-индикатором и знаком проекта в центре. `_LifecycleOverlay` стал theme-aware: фон, текст, акцентная линия и spinner берут цвета из активной темы (`violet`/`graphite`/`light`). Тема применяется при startup-экране, после чтения `config.json`, при смене темы из WebEngine/старого SettingsDialog и перед показом shutdown-экрана. Экран закрытия сохранён и вызывается перед graceful teardown.

- 2026-05-26 (startup/shutdown overlay без видимого старого UI): UI — `appPROEKT1/PROEKT1.py`. Старый QWidget-dashboard оставлен только как скрытый compatibility-layer для существующих Python-атрибутов, сигналов и мостовой логики, поэтому он больше не мелькает при запуске до загрузки `QWebEngineView`. Добавлен полнооконный `_LifecycleOverlay` с анимированным `_LifecycleSpinner`: при старте показывает инициализацию минимум ~1.4с до готовности HTML-интерфейса, при закрытии показывает экран закрытия перед STOP/sync/teardown. `closeEvent` переведён на двухфазный сценарий: сначала отрисовывается overlay, затем cleanup выполняется с короткой прокачкой Qt events при ожиданиях потоков/процесса, чтобы окно не выглядело зависшим. BLE/USB-протокол не менялся.

- 2026-05-26 (баги тултипа кривой + кнопка подтверждения): UI — `appDESIGN/design-preview.html`, `appPROEKT1/PROEKT1.py`. Исправлены три бага в тултипе редактора кривых: (1) Backspace/Delete в инпуте тултипа больше не удаляет контрольную точку кривой — в `PROEKT1.py` добавлена проверка `tagName === 'INPUT'` в обработчик `plot.keydown`, в обоих файлах добавлен `e.stopPropagation()` для этих клавиш в обработчик `keydown` инпута; (2) двойной клик по тексту в тултипе больше не добавляет новую точку — добавлена проверка `event.target.closest('#curve-tooltip')` в обработчик `dblclick`; (3) добавлена кнопка-галочка `#curve-tt-confirm` слева от числовых полей тултипа: появляется (с CSS-переходом) при вводе с клавиатуры (`input`-событие → класс `has-edit` на тултипе), по клику применяет введённые значения и скрывает тултип; `placeTooltip`/`placeCurveTooltip` сбрасывают класс `has-edit` при перемещении на новую точку; при фокусе инпута отменяется авто-скрытие тултипа, при блюре — запускается.
- 2026-05-26 (плавное движение точек кривой): UI — `appDESIGN/design-preview.html`, `appPROEKT1/PROEKT1.py`. В редакторе кривых оборотов устранена задержка курсора/точки при preview и drag: геометрия SVG-графика кэшируется вместо повторного `getBoundingClientRect()` на каждом движении мыши, обработка `pointermove` сведена к одному обновлению за кадр через `requestAnimationFrame`, координаты точки теперь float с точностью до 0.01 (без ступенчатого `Math.round()` на каждом движении), а округление осталось только для текста в label/tooltip и ручного ввода. Курсор-точка перемещается через CSS transform-переменные, тултип позиционируется без `transform`, по целым `left/top` после кэшируемого измерения размера, чтобы текст не размывался и не было layout read на каждом кадре. Во время drag и при захвате точки не пересоздаются SVG-точки через `innerHTML`: live-render обновляет только `d` активного path и атрибуты существующих circle, без полного rebuild обоих SVG-слоёв. Для снижения paint/compositing cost во время движения отключаются SVG `drop-shadow`, dash-анимация preview, pulse-анимация курсора и `backdrop-filter` тултипа; текст cursor-label обновляется только при изменении округлённого значения. Глобальный JS-tooltip безопасно игнорирует не-Element event targets, чтобы не ловить `e.target.closest is not a function`.

- 2026-05-25 (undo/redo/сброс для кривых): UI — `appDESIGN/design-preview.html`, `appPROEKT1/PROEKT1.py`. В редакторе кривых оборотов добавлена система истории изменений: Ctrl+Z — отменить, Ctrl+Y / Ctrl+Shift+Z — повторить (до 40 состояний на каждый режим). Рядом с переключателем «Насосы / Вентиляторы» появились три иконки-кнопки: `←` (отмена), `→` (повторить), `↺` (сброс кривой к 4 точкам по умолчанию с inline-подтверждением «Сбросить? ✓✗»). История независима для pump- и fan-кривой; стек redo сбрасывается при любом новом действии; дубликаты не записываются. `pushHistory()` вызывается перед: добавлением точки, началом drag, удалением точки, ручным вводом в tooltip. Кнопки автоматически приобретают disabled-стиль при пустом стеке.

- 2026-05-25 (интерактивный preview добавления точки кривой): UI — `appDESIGN/design-preview.html`, `appPROEKT1/PROEKT1.py`. В график `view-curves` добавлен отдельный SVG-слой `curve-preview-layer` с двумя анимированными пунктирными отрезками будущей кривой: при движении курсора показываются только сегмент до новой точки и сегмент после неё, без превращения всей многоточечной кривой в пунктир. Левый клик по пустому месту графика добавляет точку, выбирает её и показывает интерактивный тултип; клик/drag по существующей точке сохраняет прежнее поведение. Runtime-JS в PySide6 синхронизирован с HTML-тултипом: поля °C/% больше не перетираются текстом, tooltip можно закреплять, редактировать и удалять точку без ухода ниже двух точек.

- 2026-05-25 (тултип кривой без сжатия): UI — `appDESIGN/design-preview.html`. Для графика `view-curves` разрешён выход тултипа за пределы фрейма графика (`overflow: visible`, без paint containment у `curve-main`), внутри тултипа запрещён перенос строки (`white-space: nowrap`, `max-content`). Зернистость стеклянной подложки заменена с крупных radial-точек на мелкий SVG turbulence-noise grain.

- 2026-05-25 (две кривые на SVG-графике): UI — `appDESIGN/design-preview.html`, `appPROEKT1/PROEKT1.py`. График вкладки `view-curves` теперь одновременно отображает кривую помпы голубым `#8bd5ff` и кривую вентиляторов розовым `#ff85c2`; выбранная радиокнопкой кривая остаётся активной для перетаскивания/двойного клика, вторая остаётся видимой фоном. Тултип точки показывается только во время drag, позиционируется строго по центру над перетаскиваемой точкой с отступом 20 px, получил 50% прозрачную стеклянную подложку с зернистостью.

- 2026-05-25 (убраны лишние функции точек кривой): UI — `appDESIGN/design-preview.html`, `appPROEKT1/PROEKT1.py`. Из вкладки `view-curves` удалены правый блок «Точки кривой» с кнопкой `+`/числовым списком точек и нижняя кнопка «редактор точек», открывавшая старый `FanPumpCurveDialog`. Вычищены связанные CSS-правила и runtime-JS обработчики `curve-points-list`, `btn-curve-add-point`, `btn-curves-editor`. Прямое редактирование кривой на SVG-графике и сохранение/отправка текущих `FC`/`PC` пакетов сохранены.

- 2026-05-25 (минималистичная шапка графика кривых): UI — `appDESIGN/design-preview.html`, `appPROEKT1/PROEKT1.py`. Во вкладке `view-curves` удалены отдельный заголовок `curve-title` и блок `curve-summary`; график теперь начинается сразу под подписью «Обороты ... %». Переключатель «Помпа / Вентиляторы» заменён с крупного segmented-control на компактную пару радиокнопок с сохранением `data-curve-mode`, поэтому выбранная радиокнопка по-прежнему определяет, какая кривая редактируется и отправляется. Визуал `curve-plot` упрощён: слабее сетка/фон, тоньше линия, меньше свечение точек.

- 2026-05-25 (WebEngine кривые стали редактируемыми): UI — `appDESIGN/design-preview.html`, `appPROEKT1/PROEKT1.py`. Вкладка `view-curves` теперь редактирует точки кривых прямо внутри WebEngine-интерфейса: точки можно выбирать и перетаскивать на SVG-графике, добавлять двойным кликом/кнопкой `+`, удалять из списка и менять через числовые поля температуры/процента. `QWebChannel`-payload `applyCurves()` расширен полями `fanCurve`/`pumpCurve`; Python валидирует 2..16 точек, сохраняет их в `curves.json`/пресет и переиспользует существующую отправку бинарных пакетов `FC`/`PC` через общую BLE/USB-очередь. Прошивочный протокол не изменялся.

- 2026-05-25 (упорядочена вкладка настроек оборотов): UI — `appDESIGN/design-preview.html`, `appPROEKT1/PROEKT1.py`. Вкладка `view-curves` переразложена в две стабильные зоны: слева основная карточка кривой с полноширинным переключателем «Помпа / Вентиляторы», заголовком, единой строкой статусов и графиком; справа единая панель «Параметры кривой» вместо разрозненных карточек, с секциями источника датчика, профиля/гистерезиса и времени отклика. Сохранены существующие id/data-атрибуты для WebEngine/QWebChannel-логики. Служебные блоки HTML-превью `legend` и `names-panel` скрыты по умолчанию, чтобы не засорять обычный просмотр макета; в runtime скрываются оба блока.

- 2026-05-25 (отключена внешняя подложка вкладок): UI — `appDESIGN/design-preview.html`. Для WebEngine-вкладок `dashboard-card`, `settings-card` и `curves-card` отключены общий фон, рамка, скругление и внутренний padding — рабочие элементы теперь лежат напрямую на фоне main-area без лишней большой карточки. Освободившееся место перераспределено: увеличены внутренние Metric/Fan/Info-карточки и TriStateSwitch на dashboard, расширены отступы и gap сетки настроек, увеличены область графика и правая панель вкладки «Настройки оборотов»; графитовая и светлая темы больше не возвращают внешнюю подложку.

- 2026-05-25 (WebEngine вкладка настроек оборотов): UI — `appDESIGN/design-preview.html`, `appPROEKT1/PROEKT1.py`. Пункт сайдбара «Настройка помпы» переименован в «Настройки оборотов» и теперь открывает встроенную HTML-вкладку `view-curves` вместо немедленного модального `FanPumpCurveDialog`. В макет добавлена структура редактора кривых оборотов по температуре на основе Stitch без переноса его бокового меню: сегмент «Помпа / Вентиляторы», график кривой, активный профиль, источник CPU/GPU/MAX, гистерезис и задержки включения/выключения. Через `QWebChannel` добавлены `curvesAction()` и `applyCurves()`: вкладка синхронизируется с `curves.json`, сохраняет источник/гистерезис/задержки, отправляет текущие пакеты `FC`/`PC` в BLE/USB-очередь, а старый точный редактор точек доступен кнопкой «редактор точек».

- 2026-05-25 (WebEngine settings подключены к логике): UI — `appPROEKT1/PROEKT1.py`. Вкладка HTML `view-settings` теперь работает как настоящие настройки: через `QWebChannel` добавлены bridge-методы `applySettings()` и `settingsAction()`, runtime-JS помечает toggles/dropdowns/sliders и отправляет черновик по кнопке «сохранить». К Python-логике привязаны транспорт BLE/USB, автозагрузка Windows (HKCU Run `PROEKT1`), запуск свёрнутым, продувка после выключения, защита гидролинии (`LP`), подсветка без соединения (`LK`), яркость LED (`LX` brightness-only), яркость OLED (`OB`), язык OLED (`DL`), тема оформления и сохранение в `config.json`; «отмена» возвращает DOM к текущему сохранённому состоянию. Кнопка «настроить» открывает существующий LED-редактор, «ЛОГИ» открывает `LogWindow`, а блок моточасов HTML синхронизируется из `pump_hours_base`/накопителей.

- 2026-05-25 (WebEngine settings без старого окна): UI — `appPROEKT1/PROEKT1.py`. В обработчике `_on_web_nav_clicked("settings")` отключён вызов старого PySide `SettingsDialog`: клик по HTML-кнопке «Настройки» теперь остаётся внутри `QWebEngineView` и показывает встроенную вкладку `view-settings` из `appDESIGN/design-preview.html`, без модального окна поверх интерфейса.

- 2026-05-25 (переход UI на QWebEngineView): UI — `appPROEKT1/PROEKT1.py`, `appPROEKT1/PROEKT1.spec`. В приложение добавлен Chromium-рендер через `QWebEngineView`: видимый главный интерфейс теперь загружает `appDESIGN/design-preview.html` напрямую, скрывает служебную легенду макета и растягивает `.app-window` на окно приложения, чтобы дизайн рисовался тем же HTML/CSS-движком, что и макет. Добавлен `QWebChannel`-мост `_WebUiBridge`: клики HTML `tri-switch` возвращаются в существующий Python-обработчик `on_switch_state_changed()`, кнопки окна вызывают свернуть/закрыть, nav-пункты открывают существующие функциональные диалоги. Старый QWidget/QPainter dashboard остаётся как compatibility-слой для BLE/USB/таймеров, но live-значения CPU/GPU/Вода, RPM, связь, профиль, гидролинии и состояние `TriStateSwitch` синхронно отправляются в DOM. В `PROEKT1.spec` добавлен HTML-макет в `datas` и скрытые импорты `PySide6.QtWebEngineWidgets`, `PySide6.QtWebEngineCore`, `PySide6.QtWebChannel` для сборки.

- 2026-05-25 (dashboard icon/baseline parity): UI — `appPROEKT1/PROEKT1.py`. Fill-иконки секций (`thermo_fill`, `fan_blade`, `info_fill`, `bolt`) теперь рисуются по фактической геометрии SVG 12×12 из `appDESIGN/design-preview.html`, без общего внутреннего `pad=15%`, из-за которого они выглядели мельче макета. Иконка вентилятора в 44×44 круге сохраняет SVG-размер 26×26, но лопасти заполняют viewBox как в HTML. Value-row в `MetricCard` и `FanCard` переведён с `AlignBottom` на `AlignBaseline`, чтобы `°C` и `RPM` не проваливались ниже границы цифр и визуально совпадали с макетом.

- 2026-05-25 (dashboard typography parity): UI — `appPROEKT1/PROEKT1.py`. Добавлен helper `apply_label_typography()` для точного применения `Inter`, размера в pt, веса `QFont.Weight` и абсолютного `letter-spacing` к QLabel, потому что Qt/QSS не всегда одинаково интерпретирует числовые `font-weight`. На dashboard программно закреплены веса/размеры из HTML-макета: `metric-cap`/`fan-cap`/`info-cap` = 8pt/700 с spacing 1.5px, `metric-val` = 22pt/700, `fan-val` = 20pt/600, `fan-unit` = 8pt/700, `link-badge` = 9pt/700, nav/header/section-caption также получили точные веса и spacing. `FanCard` теперь всегда показывает подписи капсом (`ВЕНТИЛЯТОР 1`, `ВЕНТИЛЯТОР 2`) как в `appDESIGN/design-preview.html`; alarm-суффикс тоже переводится в верхний регистр.

- 2026-05-25 (шрифт приложения приведён к HTML-макету): UI — `appPROEKT1/PROEKT1.py`. Добавлены `APP_FONT_FAMILY="Inter"`, fallback `Segoe UI`, загрузчик `_load_design_font_family()` и `apply_design_font(app)`: приложение теперь явно подхватывает `Inter*.ttf/otf` из `appPROEKT1/fonts`, `appPROEKT1/fonts/Inter` или `%WINDIR%/Fonts`, затем ставит этот шрифт через `QApplication.setFont()`. `apply_app_theme()` вызывает применение шрифта до QSS, поэтому inline-styles наследуют Inter так же, как HTML `font-family: "Inter", "Segoe UI", sans-serif`. В `QPainter`-отрисовке заменены явные `Arial` на `design_font_family()`, а `TriStateSwitch` берёт Inter из фактического семейства приложения.

- 2026-05-25 (дожато соответствие dashboard HTML-макету): UI — `appPROEKT1/PROEKT1.py`. Панель управления дополнительно выровнена с `appDESIGN/design-preview.html`: `TriStateSwitch` теперь рисует трек ровно в геометрии CSS `height:48px / padding:4px`, активные сегменты имеют радиус 11px и фон `rgba(10,11,37,0.63)`; header убрал лишний левый отступ и дополнительный gap перед `· онлайн`; вертикальный разделитель сайдбара ослаблен до `rgba(255,255,255,0.055)`; внешний `_RoundedWindowFrame` рисует тонкую рамку `rgba(255,255,255,0.12)` по скруглённому контуру окна; подписи секций приведены к SVG 12×12, `8pt`, `letter-spacing:2px`; nav-иконки используют stroke 1.4; статус `Гидролинии: норма` снова считается нормальным состоянием и окрашивается голубым, как в макете.

- 2026-05-25 (сайдбар больше не прозрачный): UI — `appPROEKT1/PROEKT1.py`. В `_RoundedSidebar` отключён `WA_TranslucentBackground`, убрана очистка `CompositionMode_Clear` из `paintEvent()` и фон сайдбара теперь заливается непрозрачным `QColor(18,19,46,255)` вместо alpha 180. Внешние левые углы по-прежнему рисуются антиалиасным `QPainterPath`, но desktop/wallpaper и градиент подложки больше не просвечивают через боковое меню.

- 2026-05-25 (убраны белые/пиксельные углы главного окна): UI — `appPROEKT1/PROEKT1.py`. Win32 `CreateRoundRectRgn/SetWindowRgn` больше не используется для скругления главного окна, потому что region-mask на Windows даёт зубчатые пиксельные углы. Правильный способ для этого проекта сохранён здесь: включить `WA_TranslucentBackground` + `WA_NoSystemBackground`, сделать `QMainWindow#mainWindow` прозрачным, рисовать внешний фон отдельным антиалиасным `_RoundedWindowFrame` через `QPainterPath.addRoundedRect`, а сайдбар — отдельным `_RoundedSidebar` со скруглением только левых внешних углов; `_apply_rounded_mask()` должна только сбрасывать native/Qt-маску, а не ставить новую. В `apply_windows_backdrop()` добавлены DWM-флаги `DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND` (нативные сглаженные углы Windows 11) и `DWMWA_BORDER_COLOR = DWMWA_COLOR_NONE` (отключает белую системную обводку вокруг frameless-окна). Корневой `glassRoot` больше не использует QSS-фон/обводку, чтобы дочерние прямоугольники не проявлялись в углах.

- 2026-05-25 (дожаты белые уголки главного окна): UI — `appPROEKT1/PROEKT1.py`. Для `mainWindow` в `apply_windows_backdrop()` теперь отключается DWM-скругление (`DWMWCP_DONOTROUND`) и полностью пропускается Mica/Acrylic backdrop: главный экран скругляется только Qt per-pixel alpha, иначе DWM оставляет светлую подложку в углах. `_RoundedWindowFrame.paintEvent()` перед заливкой делает `CompositionMode_Clear` по всему rect, чтобы backing-store гарантированно очищался в прозрачность за пределами радиуса. Добавлен `MainWindow.showEvent()` с повторным применением DWM-настроек и сбросом native region после показа окна, потому что часть DWM-атрибутов стабильно применяется только после появления HWND.

- 2026-05-25 (точечные правки макета: win-btn, иконки секций, цвет цифр °C, разделитель сайдбара): UI — `appPROEKT1/PROEKT1.py`. **WindowControlButton** переписан под CSS `.win-btn` из макета: размер 27×27 (был 34×34 круг), `border-radius: 8px` — скруглённый квадрат, граница `rgba(255,255,255,22)`, фон `rgba(255,255,255,14)`, hover-border `rgba(205,189,255,72)`. Вместо растровой иконки теперь текстовые глифы — `«—»` для `minus`, `«✕»` для `close` (как в HTML). **Иконки секций** заменены на заполненные варианты, точно соответствующие SVG-путям макета: добавлены ключи `thermo_fill` (вертикальная капсула + колба-круг, заполнено), `fan_blade` (4 заполненные лепестковые лопасти + центральный диск), `info_fill` (заполненный диск с «вырезанным» белым `i` через `Qt.FillRule.OddEvenFill`), `bolt` (заполненная молния по пути `M7 1 L3 7 H6 L5 11 L9 5 H6 Z`). В `_section_caption` четыре вызова переключены: thermo→thermo_fill, cyclone→fan_blade, info→info_fill, power→bolt. **Цвет цифр температуры**: `MetricCard.setValue` для `°C` теперь синхронно перекрашивает `value_lbl` и `unit_lbl` в `_temp_bar_color(num)` — так же, как бар (соответствует CSS `.metric-val { color: var(--bar-color) }`). **Вертикальный разделитель сайдбара** ослаблен: `border-right` опущен с alpha 14 до 8 (макет: 0.055 — едва заметная линия).

- 2026-05-25 (иконки сайдбара + формат «ЦЕЛИ» + «Гидролинии: норма» по макету): UI — `appPROEKT1/PROEKT1.py`. **Иконки**: в `_icon_pixmap` добавлены 3 новых ключа — `sparkle` (✦ — четырёхлучевая звезда с вогнутыми гранями, заполненная — соответствует CSS `.logo-icon::after`), `led_sun` (круг + 8 лучей — для пункта «Подсветка»), `settings_sliders` (3 горизонтальных слайдера с круглыми ручками — для пункта «Настройки»). Логотип в сайдбаре теперь рисуется иконкой `sparkle` (был `spark` — простой крест). `nav_items` обновлён: `("led", "led_sun", ...)` и `("settings", "settings_sliders", ...)` — раньше использовались `spark` и `gear`. **Формат «ЦЕЛИ» в `InfoCard`**: вместо `"Цели: 🌀 40% 💧 40% (ориентир: MAX)"` теперь выводится `"CPU"` / `"GPU"` / `"CPU + GPU → Макс"` (зависит от `self.source_mode`) — соответствует тексту `#targets-lbl` в макете. Фактические проценты вывода вентиляторов/помпы теперь во всплывающей подсказке (`tooltip`) у `info_card.targets_lbl`, чтобы не терять данные. Fallback при `--` обновлён на `"Цели: —"`. **Текст статуса гидролиний**: в `mapping` кода LP1/3/4 заменены на «норма» (было «подключены»), 2 → «разрыв» (было «отключены») — соответствует `#loop-lbl` макета.

- 2026-05-25 (Dashboard → структурное соответствие макету 100%): UI — `appPROEKT1/PROEKT1.py` приведён к структуре `appDESIGN/design-preview.html` (вкладка `view-dashboard`). **Реструктуризация layout дашборда**: убрана двухколоночная сетка (`grid` 7/5) — теперь один столбец (`left_wrap`), внутри последовательно: ТЕМПЕРАТУРЫ (CPU/GPU/ВОДА в строку), ОБОРОТЫ ВЕНТИЛЯТОРОВ (fan1/fan2 в строку), СОСТОЯНИЕ (info_card). Под ними — тонкий горизонтальный разделитель (rgba(255,255,255,18), 1px). Снизу — секция «⚡ РЕЖИМ РАБОТЫ» с `TriStateSwitch` во всю ширину (`setMetrics(height_px=62, text_pt=12)` — в макете это крупный pill-switch). Раньше tri-switch был справа узким столбиком — отсюда обрезка «ПРОДУВКА». **Удалена нижняя полоса** `btn_settings + transport_combo + btn_curve` — в макете её нет (доступ через сайдбар-навигацию «Настройки» / «Настройка помпы»). Виджеты сохранены как атрибуты (`self.btn_settings`/`self.transport_combo`/`self.btn_curve`) с `setVisible(False)` — сигналы и существующий код работают без изменений. **Сайдбар**: удалён nav-пункт «Температуры» (в макете 4 пункта: Панель управления / Настройка помпы / Подсветка / Настройки). Скрыты `btn_purge_system` и `btn_log` (в макете отсутствуют) — функционал сохранён: продувка доступна через сегмент TriStateSwitch, логи — через хоткей **Ctrl+L** (`QShortcut(QKeySequence("Ctrl+L"))`). **Цвет бара температур** теперь плавно интерполируется по значению (`_temp_bar_color(v)` — модульный хелпер): ≤30°C — голубой #8bd5ff; 30–45°C — голубой→розовый; 45–65°C — розовый #ff85c2; 65–85°C — розовый→красный #ff2828 — соответствует JS-логике `tempColor()` в design-preview.html. `MetricCard.setValue` вызывает `self._bar.setAccent(_temp_bar_color(num))` для единицы `°C`.
- 2026-05-25 (панель управления → 100% соответствие макету): UI — `appPROEKT1/PROEKT1.py` доработан под `appDESIGN/design-preview.html` для главной панели управления (фиолетовая тема). **Импорты**: добавлены `QRadialGradient`, `QLinearGradient`, `QTransform`. **`TriStateSwitch.paintEvent`**: исправлен баг геометрии сегментов — раньше `seg_w = (track_w - gap*2) / 3`, что не учитывало 2 внутренних зазора между плитками; теперь `seg_w = (track_w - gap*4) / 3`. Из-за этого активная плитка/последняя подпись «ПРОДУВКА» обрезались — устранено. Удалена дублирующая строка вычисления `slot_x`. **`_GlassCard`** переписан: больше не использует QSS (`background-color`), а отрисовывается через `paintEvent`: базовый цвет → набор радиальных «блобов» (стек `QRadialGradient`) → тонкая верхняя «глянцевая» полоска → обводка. Принимает `blobs: list[(cx_frac, cy_frac, r_frac, color, alpha)]`. Добавлены публичные `setBlobs/setBaseColor/setBorderColor` для динамики (alarm-стейт). Введены модульные константы `_BLOBS_CPU/_BLOBS_GPU/_BLOBS_WAT/_BLOBS_FAN1/_BLOBS_FAN2/_BLOBS_INFO` — 1:1 с CSS `#cpu-card`/`#gpu-card`/`#water-card`/`#fan1-card`/`#fan2-card`/`#info-card`. **`MetricCard`** автоматически подбирает блобы по подписи (cpu/gpu/вода/water); бар-прогресс вынесен в новый виджет **`_MetricBar`** (`paintEvent`): фон-полоса с alpha-цветом акцента, заливка градиентом + светящаяся точка (radial halo + сама точка) — соответствует CSS `.metric-bar-fill::after`. **`FanCard`**: статичная иконка заменена на **`_FanSpinIcon`** (QWidget, `paintEvent` + `QTimer 30 FPS`), полный оборот за 1.8 с — соответствует CSS-анимации `fan-spin 1.8s linear infinite`. `setRpm(0)` останавливает вращение; `setAlarm(True)` тоже останавливает и перекрашивает иконку в #ffaf56. `fan2_card` создаётся с зеркальным блобом `_BLOBS_FAN2`. **`InfoCard`**: блобы `_BLOBS_INFO`. **Разделитель** в нижней части дашборда: убран `setFrameShape(HLine)` (мешал QSS), теперь plain `QFrame` с прозрачным фоном rgba(255,255,255,18). Функциональность всех виджетов (методы `setValue/setAccent/setRpm/setAlarm/setTargets/setProfile/setLink/setLoop/setText`) сохранена — обратной совместимости не нарушено.
- 2026-05-24 (перенос дизайн-макета в приложение): UI — в `appPROEKT1/PROEKT1.py` добавлена инфраструктура переключения тем оформления по 3 вариантам из `appDESIGN/design-preview.html`: `Фиолетовый` (по умолчанию, текущий стиль), `Графит` (тёмный нейтральный), `Белый` (светлый). Введены глобальные `THEMES` (палитра-словарь на каждую тему: bg/surface/accent/text/border + rgba-компоненты), `palette()`, `current_theme_name()`, `set_active_theme()`. Шаблон `QSS_TEMPLATE` параметризован токенами палитры; `DEFAULT_THEME_QSS` теперь автогенерируется из violet-палитры. `apply_app_theme(app, theme_name=None)` теперь умеет принимать имя темы или читать его из `config.json` (ключ `theme`); для `violet` по-прежнему используется внешний `theme.qss` (если есть). В `MainWindow.load_app_config` добавлено чтение `theme` (фолбэк `violet`), в `save_app_config` — запись. В `SettingsDialog` добавлен новый параметр конструктора `theme="violet"`, верхний `QComboBox` «Тема оформления» (Фиолетовый/Графит/Белый) и метод `get_theme()`. `show_settings_dialog` пробрасывает текущую тему в диалог. `_apply_settings_from_dialog` при смене темы вызывает `apply_app_theme(QApplication.instance(), new_theme)` и показывает информационное сообщение о необходимости перезапуска для полного применения (значительная часть виджетов использует inline-стили). Ключ `theme` сохраняется в `appPROEKT1/config.json`. **Параметр конструктора SettingsDialog `theme` не обязателен (имеет дефолт), обратная совместимость сохранена.**
- 2026-05-13 (фикс QSS + редизайн): UI — устранены ошибки «Could not parse stylesheet of object WindowControlButton» (использование `}}` в обычной (не f-string) части склеивания QSS приводило к двойной фигурной скобке в финальном CSS — Qt не парсил его). Перешли на безопасный шаблон `.replace("__TOKEN__", value)` в `WindowControlButton` и `MainWindow._update_log_btn`. Добавлен общий хелпер `_parse_color()` — `_icon_pixmap` теперь корректно принимает строки `rgba(r,g,b,a)`/`rgb(...)`, hex и `QColor`. Полировка дизайна главного окна: фон — мягкий диагональный `qlineargradient` (#161735→#0d0f28); sidebar сужен до 244px, шапка переделана: цветной квадрат-логотип (искра в фиолетовой подложке) + «ПРОЕКТ 1» + подзаголовок «v2.4 · STABLE»; пункт навигации `SidebarNavButton` получил левую цветную полоску-индикатор активного состояния (3px #cdbdff), сам активный фон — мягкая фиолетовая полупрозрачная плашка (без жёсткой обводки), текст активного — чисто-белый/700; «ПРОДУВКА СИСТЕМЫ» — добавлен мягкий заполненный hover-фон; «ЛОГИ» — компактнее (28px высотой, кегль 8pt). Window-controls (`WindowControlButton`) уменьшены до 34×34, плоские (rgba(255,255,255,14)), мягкая обводка, без тёмной заливки; иконки 14px. В шапке main_area появился заголовок страницы «ПАНЕЛЬ УПРАВЛЕНИЯ · онлайн». Стеклянная карта дашборда: радиус 24, отступы 34/30, тень `blur=80, y=22, alpha=130`. Bottom-bar: `btn_settings` стал 12-радиус-плашкой со стеклянным фоном, `transport_combo` приведён к тому же стилю, `btn_curve` слегка уменьшен (40px высотой, паддинг 28px) — образует визуально согласованный ряд.
- 2026-05-13 (полировка макета): UI — добавлена векторная иконосистема `_icon_pixmap(key,size,color,stroke)` + хелпер `_icon_label(...)` (рисует иконки QPainter'ом без зависимости от Material Symbols/эмодзи-шрифтов). Поддерживаемые ключи: dashboard, drop, spark, thermo, gear, cyclone, info, power, terminal, minus, close, verified. Заменены: глифы боковой навигации (▦◐✦🌡⚙ → dashboard/drop/spark/thermo/gear), `WindowControlButton` (—/✕ → minus/close, размер 40×40, радиус 20), пиктограммы `_section_caption` (🌡/⟳/ⓘ/⏻ → thermo/cyclone/info/power), иконка `FanCard` (◉/⚠ → cyclone/info), нижняя ⚙ кнопка (`btn_settings`) и кнопка «ЛОГИ» (`btn_log` теперь с иконкой terminal). `TriStateSwitch` перерисован под трёхсегментный пилль-стиль из макета: тёмный glass-трек с тонким border-radius=14, активный сегмент-плитка ровно 1/3 ширины со свечением и собственным цветом, неактивные подписи (СТОП/РАБОТА/ПРОДУВКА) рендерятся внутри своих сегментов уменьшенным трекинг-капсом. Удалён правый плейсхолдер «ДАННЫЕ В РЕАЛЬНОМ ВРЕМЕНИ». Сигнатура `SidebarNavButton.__init__(icon_key, label)` и `WindowControlButton.__init__(icon_key, hover_color)` принимают ключ иконки; иконка боковой навигации переключается в `_refresh_icon` по сигналу `toggled` (активный — #cdbdff, неактивный — rgba(202,195,216,200)).
- 2026-05-13: UI — главный экран переведён на компоновку с боковым меню (по макету «NEBULA CONTROL Dashboard»): окно безрамочное (`FramelessWindowHint`), `MainWindow` примешивает `FramelessWindowMixin`. Слева — `sidebar` (248px) с заголовком «ПРОЕКТ1 v2.4 / STATUS: STABLE», навигацией (Панель управления / Настройка помпы / Подсветка / Температуры / Настройки), кнопкой «ПРОДУВКА СИСТЕМЫ» (переводит tri-switch в состояние 2) и пунктом «ЛОГИ» (открывает `LogWindow`). Справа — `main_area`: верхняя строка с круглыми кнопками «свернуть/закрыть» (`WindowControlButton`), `QStackedWidget` со страницей-дашбордом (стеклянная карта `dashboardCard`) — слева 7/12 колонок (TEMPERATURES → CPU/GPU/Вода `MetricCard`, FAN RPM → `FanCard`×2, СОСТОЯНИЕ → `InfoCard`), справа 5/12 (РЕЖИМ РАБОТЫ — `TriStateSwitch`, плейсхолдер «Данные в реальном времени»). Нижняя полоса карточки: `btn_settings` (⚙) + `transport_combo` (BLE/USB), справа — `btn_curve` («НАСТРОИТЬ ОБОРОТЫ»). Перетаскивание окна — через `DragHandle` (sidebar и шапка main_area; двойной клик — maximize). Старый `TopBar` выведен из MainWindow (атрибут `self.top_bar=None` для совместимости). Добавлены классы: `SidebarNavButton`, `WindowControlButton`, `DragHandle`. Новые методы MainWindow: `_section_caption`, `_sidebar_placeholder`, `_on_sidebar_purge_clicked`, `_toggle_maximize`. Сохранены все прежние атрибуты (`self.cpu_card/gpu_card/water_card`, `self.fan1_card/fan2_card`, `self.info_card`, `self.tri_switch`, `self.transport_combo`, `self.btn_log`) и шимы (`cpu_label`, `gpu_label`, `water_label`, `fan1_val`, `fan2_val`, `info_label`, `loop_label`). Минимальный размер окна — 960×660. Импорт расширен `QStackedWidget`.
- 2026-05-06: UI — редизайн «NEBULA CONTROL»: добавлен глобальный `appPROEKT1/theme.qss` (тёмная glass-morphism тема, Inter, палитра background=#0f112b, surface-container=#1c1d38, primary=#cdbdff, primary-container=#7c4dff, secondary=#8bd5ff); включён `ENABLE_GLASS_BACKDROP=True` (Mica/Acrylic на Windows 11/10); обновлены inline-стили MainWindow (заголовок «NEBULA CONTROL», glass-карты CPU/GPU/Вода/RPM, info_label/loop_label, кнопки «настроить обороты»/⚙/transport_combo); перекрашен `TriStateSwitch` (track=glass, пилюли: пауза=#B43C46, работа=#7C4DFF, продувка=#00BDFD); fallback `DEFAULT_THEME_QSS` приведён к новой палитре. theme.qss задаёт стили для QPushButton/QComboBox/QLineEdit/QSpinBox/QSlider/QCheckBox/QRadioButton/QGroupBox/QMenu/QToolTip/QTableWidget/QScrollBar.
- 2026-03-05: Прошивка — статус «ЗАЩИТА» (err5, разрыв петли) заменён на бегущую строку «ПОДКЛЮЧИТЕ ГИДРОЛИНИИ» / «CONNECT HYDROLINES» (pixel-marquee, без чередования с ПАУЗА/РАБОТА); при подключении к приложению слева отображается иконка и тип соединения (БТ/ЮСБ); приоритет — наивысший среди всех статусных сообщений (выше ОЖИДАЮ ЦЕЛЕВЫЕ ТЕМПЕРАТУРЫ и ошибок err1–err4/err6).
- 2026-03-02: UI — настройки задержки включения/выключения вентиляторов и насосов перенесены из «Настройки приложения» (SettingsDialog) в окно «Настройки кривых» (FanPumpCurveDialog); задержки теперь сохраняются в curves.json (с обратной совместимостью загрузки из config.json); удалены delay_on/delay_off из SettingsDialog, get_delay_on/get_delay_off, параметры конструктора и чтение из _apply_settings_from_dialog.
- 2026-03-02: Прошивка + UI — добавлен селектор языка дисплея (RU/ENG): в настройках приложения добавлен комбобокс «Язык дисплея» (RU/ENG); новая команда протокола `DL` + 1 байт (0=RU, 1=EN) отправляется через BLE (CTRL 0xFFE9) и UART; ESP32 сохраняет выбранный язык в NVS (`oled`/`lang`) и при загрузке восстанавливает; все надписи OLED-дисплея (ЦП→CPU, ГП→GPU, ВОДА→WATER, ЗАГРУЗКА→LOADING, ПРОДУВКА→PURGING, НАПОЛНЯЮ→FILLING, ПОДКЛЮЧАЮ→CONNECT, ЗАЩИТА→PROTECT, ОШИБКА→ERROR, ГОТОВ→READY, ПАУЗА→PAUSE, РАБОТА→ACTIVE, ПУСК→START, БТ→BT, ЮСБ→USB) переключаются по `g_display_lang`; настройка сохраняется в `config.json` и переотправляется при переподключении.
- 2026-03-02: Прошивка + UI — исправлена ложная активация НАПОЛНЕНИЕ (RAMP) после авто-рестарта при восстановлении петли: убран `g_start_pending=true` из auto-rearm (он вызывал NVS boost check и армирование рампы помпы); добавлен `g_pump_boost_armed=false` в обработчик разрыва петли для сброса стояло-от-продувки-вооружение; RAMP теперь срабатывает строго только после цикла «продувка → стоп → старт». В приложении убрана отправка дублирующей команды 'ST' из countdown `_on_autostart_tick` (ESP32 сам делает auto-rearm и присылает LOOP:4).
- 2026-03-02: Прошивка + UI — UART-паритет для LOOP-статуса и синхронизация auto-rearm: добавлен UART-пакет `LS` (Loop Status, 3 байта: 'L','S',code) — ESP32 теперь отправляет loop status (break/restore/auto-start) по USB наравне с BLE notify; добавлен code=4 (auto-started) — при окончании 5с отсчёта на ESP32 отправляется LOOP:4, приложение мгновенно ставит кнопку в РАБОТА; в приложении добавлен `_parse_ls_buffer()` в USBTempSender; обработчик LOOP:4 в UI отменяет свой countdown и форсирует `system_running=True`.
- 2026-03-02: Прошивка + UI — синхронизация кнопки приложения с ESP32 при авто-рестарте после восстановления петли: ESP32 теперь отправляет LOOP notify code=3 (петля восстановлена + система была в РАБОТА) вместо code=1; приложение на LOOP:3 немедленно переключает кнопку в зелёный режим «работа» и запускает 5-секундный countdown «работаю через N», синхронизированный с OLED «ПУСК N»; устранены гонки — удалены `_was_running_before_loop_block` и сложная логика `_prev_loop_status_code` для автостарта; решение принимает ESP32 (авторитетный источник) и сообщает его атомарным кодом; при LOOP:1 (был на паузе) — просто снимается блокировка; при ручной смене состояния пользователем во время countdown — отсчёт отменяется.
- 2026-03-02: UI — усилена надёжность записи `_was_running_before_loop_block`: теперь проверяется `tri_switch.state() != 0 OR system_running` (оба обработчика — update_link_status и update_ui), что устраняет гонку, когда update_ui сбрасывает switch в 0 до прихода сигнала LOOP:2; `system_running = False` ставится безусловно при LOOP:2.
- 2026-03-02: Прошивка — добавлен авто-рестарт ESP32 после восстановления петли: по истечении LP_REARM_SECS (5с) ESP32 сама ставит `g_system_running=true` и очищает `g_lp_restore_ms`; ранее ESP32 только показывала «ПУСК N» на OLED, но не перезапускала систему (зависала на «ПУСК 1»); рестарт происходит только если система была в РАБОТА до разрыва.
- 2026-03-02: Прошивка + UI — исправлена логика автостарта при размыкании/замыкании петли защиты: (1) устранена гонка update_ui/update_link_status — оба обработчика теперь корректно записывают `_was_running_before_loop_block`; (2) добавлен флаг `g_was_running_before_loop_break` на ESP32 — OLED показывает «ПУСК N» только если система была в РАБОТА до разрыва; при паузе обратный отсчёт и рестарт не происходят.
- 2026-03-02: Прошивка — устранён паразитный 1-секундный запуск вентиляторов/помпы при переподключении (BLE/USB): `g_system_running` теперь сбрасывается в `false` при каждом подключении; ESP32 стоит в STOP до получения ST/SP от приложения (~200мс).
- 2026-03-02: Прошивка — автоматическое восстановление LED-ленты (WS2812) при залипании RMT-канала: добавлен счётчик `g_led_invalid_state_cnt`, после 10 подряд `ESP_ERR_INVALID_STATE` ставится `g_led_need_reinit` и RMT-канал пересоздаётся; подавлены повторяющиеся RMT/led_strip_rmt логи ошибок во время recovery.
- 2026-03-02: UI — исправлено обращённое поведение ST/SP при переподключении: `_sync_run_state` теперь смотрит `tri_switch.state()` вместо `system_running`; добавлена явная синхронизация `system_running` во всех местах с `setState(external=True)` (LOOP:2 stop, autostart, update_ui lock, purge auto-return), чтобы флаг не расходился с визуальным состоянием переключателя.
- 2026-03-02: UI — автозапуск при восстановлении петли теперь учитывает намерение пользователя: добавлен флаг `_was_running_before_loop_block`; автостарт (LOOP 2→1) срабатывает ТОЛЬКО если кнопка была в «работа» до разрыва; если пользователь сам стоял на паузе — ESP32 не запускается; оба флага сбрасываются при реконнекте.
- 2026-03-02: UI — исправлен ложный автозапуск после переподключения ESP32 в режиме «пауза»: автозапуск по LOOP-статусу теперь срабатывает только при переходе петли из «разорвана»(2) в «подключена»(1), а не при любом получении code=1; добавлено отслеживание `_prev_loop_status_code` с обнулением при реконнекте.
- 2026-03-02: Прошивка — устранено мерцание яркости OLED при смене статуса (ЗАЩИТА↔ПАУЗА): ошибка теперь показывается постоянно (мигает только треугольник-иконка, ~12 пикселей), что исключает перераспределение тока charge pump SSD1312; добавлена иконка подключения (БТ/ЮСБ) в строку ошибки; размер I2C-чанка увеличен с 16 до 128 байт для ускорения записи GDDRAM.
- 2026-03-02: Прошивка — исправлена кодировка кириллицы на OLED: PowerShell Set-Content при LEDC-миграции записал main.c в CP1251 вместо UTF-8, что привело к double-encoding строковых литералов (ЗАЩИТА, ОШИБКА, ЦП, ГП, ВОДА, ПАУЗА, РАБОТА, ГОТОВ, ПОДКЛЮЧАЮ и др.); выполнена байтовая замена сломанных последовательностей (d0 a0 c2 98 → d0 98 для И и аналогичные); все 11 кириллических строк проверены.
- 2026-03-02: Прошивка — I2C bus recovery для OLED: перед созданием I2C шины выполняется bit-bang восстановление (9× прокрутка SCL + STOP) для разблокировки залипшего SDA после крашей; добавлена повторная попытка probe с i2c_master_bus_reset (до 3 раз).
- 2026-03-02: Прошивка — LEDC переведён с LOW_SPEED_MODE на HIGH_SPEED_MODE: устранён бут-луп из-за зависания para_up busy-wait в ledc_channel_config/ledc_stop/ledc_update_duty; добавлен periph_module_reset(PERIPH_LEDC_MODULE) при загрузке; ESP_ERROR_CHECK заменён на безопасное логирование во всех LEDC-функциях (fan, pump, valve); удалены ledc_timer_rst + vTaskDelay.
- 2026-03-02: Прошивка — исправлена подсветка без подключения к ПК: добавлен сброс reinit в disconnected-ветке led_task; принудительный сброс профиля в LED_MODE_OFF; g_led_dirty не ставится безусловно; UART RX flush при загрузке; диагностический лог LED при старте.
- 2026-03-01: Прошивка — исправлена работа насоса после продувки: убрано авто-армирование boost в purge_task и control_task; добавлен флаг g_start_pending для одноразовой проверки NVS при старте; boost теперь срабатывает только после полного цикла STOP→START.
- 2026-03-01: Прошивка — исправлен бут-луп/зависание при переходе «продувка→стоп→работа»: safe_ledc_attach и boost-логика перенесены из BLE/UART callback'ов в control_task; добавлены проверки g_pwm_attached в PWM-функциях; ESP_ERROR_CHECK заменён на безопасное логирование; purge_stop() вызывается при SP.
- 2026-02-21: Документация — в `PROEKT1 rools.md` добавлено правило: при внесении изменений в функционал остальные функции не должны страдать; в спорных случаях требуется ЯВНОЕ предупреждение перед применением.
- 2026-02-21: UI — ограничена минимальная яркость LED-ленты до 10% в `appPROEKT1/PROEKT1.py`.
- 2026-02-21 (вторая правка): UI — изменено поведение ползунка: сохранён 5% минимальный полезный уровень, при крайнем положении `0` лента полностью гаснет.

---

## ОГЛАВЛЕНИЕ

1. [Корневые файлы (сборка и конфигурация ESP-IDF)](#1-корневые-файлы)
2. [main/ — Прошивка ESP32 (C, FreeRTOS)](#2-main--прошивка-esp32)
   - [main.c — основной файл прошивки (3764 строки)](#mainc--основной-файл-прошивки)
   - [gatt_svr.c — пример GATT-сервиса NimBLE](#gatt_svrc)
   - [bleprph.h — заголовок BLE-периферии](#bleprphh)
3. [appPROEKT1/ — Windows-приложение (Python/PySide6)](#3-appproekt1--windows-приложение)
4. [components/ — Внешние компоненты ESP-IDF](#4-components--внешние-компоненты)
5. [third_party/ — Сторонние библиотеки](#5-third_party)
6. [tools/ — Утилиты калибровки](#6-tools--утилиты-калибровки)
7. [build/ — Артефакты сборки](#7-build--артефакты-сборки)
8. [Протокол обмена (BLE + UART)](#8-протокол-обмена)
9. [Карта GPIO](#9-карта-gpio)
10. [NVS-пространства имён](#10-nvs-пространства-имён)
11. [FreeRTOS-задачи](#11-freertos-задачи)

---

## 1. Корневые файлы

```
PROEKT1/
│
├── CMakeLists.txt              # Главный CMake: cmake 3.16+, project(PROEKT1), custom partitions.csv
├── partitions.csv              # Таблица разделов: nvs(24K) + phy(4K) + factory(1M) + littlefs(1M)
├── sdkconfig                   # Текущая конфигурация menuconfig (BT NimBLE ON, 4MB flash)
├── sdkconfig.defaults          # Базовые defaults: BT_NIMBLE_ENABLED=y, flash 4MB
├── sdkconfig.defaults.esp32c2  # Defaults для ESP32-C2 (отдельный таргет)
├── sdkconfig.defaults.esp32c6  # Defaults для ESP32-C6 (отдельный таргет)
├── sdkconfig.old               # Предыдущая версия sdkconfig
├── requirements.txt            # Python-зависимости: click, pyserial
├── dependencies.lock           # Lock-файл ESP-IDF component manager
├── README.md                   # Описание проекта
├── PROEKT1 tree.md             # ★ Полное аннотированное дерево проекта (этот файл)
├── PROEKT1 rools.md            # ★ Правила работы над проектом (для AI и разработчиков)
├── PROEKT1.code-workspace      # VS Code workspace
├── .clang-format               # Форматирование C-кода
├── .clangd                     # Clangd LSP config
├── .gitignore                  # Git ignore
├── .github/
│   └── copilot-instructions.md # ★ Автоинструкции для GitHub Copilot (подключаются к каждому чату)
├── appDESIGN/                  # ★ Дизайн-макеты UI (скриншоты Figma, CSS-свойства, SVG-иконки)
│   └── design-preview.html     # ★ HTML-превью главного окна со всеми вкладками (Dashboard + Settings как stack)
├── .vscode/
│   ├── settings.json           # VS Code project settings
│   └── c_cpp_properties.json   # IntelliSense конфигурация
└── .venv/                      # Python виртуальное окружение (pyserial, bleak и т.д.)
```

### Что за что отвечает:
| Файл | Роль |
|------|------|
| `CMakeLists.txt` | Точка входа CMake, подключает ESP-IDF toolchain, задаёт custom partition table |
| `partitions.csv` | NVS (настройки/калибровки), PHY (радиочасть), Factory (прошивка), LittleFS (файловая система) |
| `sdkconfig.defaults` | BLE NimBLE включён, Bluedroid выключен, flash 4MB |
| `requirements.txt` | Зависимости для Python-утилит (click, pyserial) |

---

## 2. main/ — Прошивка ESP32

```
main/
├── main.c                 # ★ ГЛАВНЫЙ ФАЙЛ (3764 строки) — вся логика контроллера
├── gatt_svr.c             # Пример GATT-сервиса (из NimBLE bleprph sample), НЕ используется основной логикой
├── bleprph.h              # Заголовок BLE (объявления gatt_svr_init/register_cb)
├── CMakeLists.txt         # Компонент main: SRCS main.c, зависит от bt, led_strip, u8g2_port, ledc, uart, gpio, i2c
├── idf_component.yml      # Зависимости компонента: idf>=5.3.0, espressif/led_strip ^2.5.0
├── Kconfig.projbuild      # Пустой (нет кастомных menuconfig-опций)
└── PROEKT1.code-workspace # Дубликат workspace-файла
```

---

### main.c — Основной файл прошивки

**Файл:** `main/main.c` (3764 строк)

Монолитный файл, содержащий ВСЮ логику контроллера. Ниже — подробная карта по секциям и строкам.

#### РАЗДЕЛ A: Включения и определения (строки 1–155)

| Строки | Содержимое |
|--------|-----------|
| 1–52 | `#include` — стандартные, ESP-IDF (gpio, ledc, uart, FreeRTOS, led_strip, u8g2, i2c) |
| 53–72 | `#include` — NimBLE (nimble_port, ble_hs, ble_gap, gatt, etc.), условная компиляция `CONFIG_BT_NIMBLE_ENABLED` |
| 78 | Определение `M_PI` |
| 80–82 | `TAG` для логов, `own_addr_type` |
| 84–87 | Включение/выключение логов RPM (`RPM_LOG_ENABLE`, `RPM_CAL_LOG`) |
| 88–100 | **BLE UUID (16-bit)**: FAN_SERVICE `0xFFE0`, TEMP `0xFFE1`, FAN_CFG `0xFFE2`, LED `0xFFE3`, PUMP_CFG `0xFFE4`, RPM `0xFFE5`, HOURS `0xFFE6`, WATER `0xFFE7`, CTRL `0xFFE9`, LOOP_STAT `0xFFEA` |
| 101–110 | **GPIO**: LED=2, FAN_PWM=16, PUMP_PWM=17, VALVE=25, TACH1=18, TACH2=19, DS18B20=13 |
| 111–140 | **Тахометр**: TACH_PULSES_PER_REV=2, калибровочные масштабы (g_rpm_scale1/2), RPM_MAX=1800, RPM_FAULT_MIN=100 |
| 141–145 | **WS2812**: GPIO=27, LED_STRIP_LENGTH=20, разрешение RMT=10MHz, яркость по умолчанию=64 |
| 146–148 | **Loop protection GPIO**: LOOP_OUT=26, LOOP_IN=33 |
| 149–155 | **Диапазоны температур**: TEMP_MIN=30°C, TEMP_MAX=110°C, WATER_TEMP_CRIT=50°C, SPEED 0..100%, макс. 16 точек кривой |

#### РАЗДЕЛ B: PWM-конфигурация (строки 155–230)

| Строки | Содержимое |
|--------|-----------|
| 155–162 | LEDC: FAN_FREQ=25kHz, PUMP_FREQ=25kHz, VALVE_FREQ=30kHz, разрешение 10 бит (1023 max) |
| 163–167 | Pump boost профиль: PHASE1=2с (0→100%), HOLD=3с (100%), PHASE2=2с (100→target) |
| 168–175 | Режимы: DEF_INTERP=spline, DEF_SOURCE=MAX(CPU,GPU), RC_TAU=1.5с, HYST=5%, STALE=5с |
| 177–200 | **Калибровка помпы** — маппинг % → напряжение: PUMP_SUPPLY=11.3V, PUMP_V_LIMIT=5V, target/drive точки при 30% и 100% |
| 201–213 | Функции `pump_target_voltage_from_percent()`, `pump_drive_voltage_from_percent()` — пересчёт % в напряжение |

#### РАЗДЕЛ C: Типы данных (строки 230–285)

| Строки | Содержимое |
|--------|-----------|
| 232–235 | `src_sel_t` — выбор источника температуры: CPU / GPU / MAX |
| 236–237 | `interp_mode_t` — режим интерполяции кривой: LINEAR / SPLINE |
| 238–239 | `curve_point_t` — точка кривой {температура, скорость} |
| 240–250 | `curve_cfg_t` — полная конфигурация кривой: версия, source, interp, count, tau, hyst, pts[16] |
| 252–263 | `led_mode_t` — режимы LED: SOLID, OFF, BLINK, BREATHE, CUSTOM, GRADIENT_ANIM |
| 264–278 | `led_profile_t` — профиль LED: mode, rgb, brightness, custom_colors[20][3], gradient start/end, speed |

#### РАЗДЕЛ D: Глобальные переменные (строки 280–400)

| Строки | Содержимое |
|--------|-----------|
| 280–310 | BLE: conn_handle, g_ble_connected, g_usb_connected, handle для каждой характеристики |
| 311–325 | Температура: g_cpu_temp_c, g_gpu_temp_c, g_water_temp_c, timestamps, ошибки (err_ble_hw, err_uart_hw) |
| 326–340 | Кривые: g_fan, g_pump (curve_cfg_t), фильтрованные/применённые значения |
| 341–355 | LED: g_led_strip, g_led_prof, g_led_task, g_led_dirty, g_led_mtx (mutex) |
| 356–375 | RPM: g_rpm_scale1/2, g_tach1/2_edges, g_rpm1/2 (калиброванные), флаги аварий |
| 376–395 | Purge: g_purge_active/cancel/task, g_purge_completed_since_last_stop |
| 395–400 | Stop/Boost: g_system_running, g_pump_boost_armed/active/start_ms/target |

#### РАЗДЕЛ E: NVS — сохранение/загрузка настроек (строки 340–400, 820–930)

| NVS Namespace | Ключ | Что хранится |
|---------------|------|-------------|
| `"fan"` | `"cfg_v1"` | curve_cfg_t — кривая вентиляторов |
| `"pump"` | `"cfg_v1"` | curve_cfg_t — кривая помпы |
| `"led"` | `"prof_v1"` | led_profile_t — LED-профиль |
| `"led"` | `"keep_on"` | uint8 — флаг «держать LED без подключения» |
| `"hours"` | `"v1"` | pump_hours_t — наработка помпы |
| `"sys"` | `"boost_pending"` | uint8 — флаг «нужен буст помпы после продувки» |
| `"sys"` | `"loopprot"` | uint8 — флаг «защита контура включена» |
| `"cal"` | `"rpm1_scale"` / `"rpm2_scale"` | float — калибровочные коэффициенты тахометра |
| `"oled"` | `"bright"` | uint8 — яркость OLED-дисплея |
| `"oled"` | `"lang"` | uint8 — язык дисплея (0=RU, 1=EN) |

#### РАЗДЕЛ F: Forward-декларации и утилиты (строки 407–450)

- `fan_pwm_init()`, `fan_pwm_set_percent()`, `pump_pwm_set_percent()`
- `control_task()`, `led_task()`, `oled_task()`, `uart_rx_task()`
- `tach_init()`, `tach_sample_and_publish()`
- `ds18b20_task()`, `ds18b20_read_celsius()`, `onewire_*()` — DS18B20
- `rpm_scale_load/save()`, `rpm_autocalibrate()`
- `loopprot_task()` — мониторинг петли защиты

#### РАЗДЕЛ G: OLED-драйвер (строки 450–815)

| Строки | Содержимое |
|--------|-----------|
| 450–465 | GPIO/адрес OLED: SDA=21, SCL=22, I2C addr=0x3C, Portrait 64×128 |
| 466–555 | `oled_i2c_init()` — инициализация I2C master bus (IDF5 API), probe OLED |
| 555–600 | `oled_send_cmd()`, `oled_send_data()` — отправка команд/данных по I2C |
| 600–650 | `oled_init()` — полная последовательность инициализации SSD1312 (charge pump, orientation, contrast, precharge) |
| 650–680 | Framebuffer: `oled_fb_clear()`, `oled_fb_set_pixel()`, `oled_fb_fill_rect()` |
| 680–740 | **Шрифт 5×7** — встроенный побитовый шрифт: ASCII (0-9, A-Z, a-z, знаки) + **кириллица** (А-Щ, Ю, а-ш) |
| 740–770 | `font5x7_get()`, `utf8_next_cp()`, `utf8_charlen()` — UTF-8 парсер |
| 770–815 | `oled_draw_char()`, `oled_draw_text()`, `oled_flush()` — рисование текста и отправка FB на дисплей |

#### РАЗДЕЛ H: Математика / интерполяция / кривые (строки 815–870)

| Строки | Содержимое |
|--------|-----------|
| 815–820 | `clampf()`, `clampu8()` — ограничение значений |
| 820–830 | `fan_apply_min_floor()` — минимальный порог включения вентилятора (30%) |
| 830–835 | `sort_points_by_temp()` — сортировка точек кривой |
| 835–845 | `catmull_rom()` — Catmull-Rom сплайн для плавной интерполяции |
| 845–865 | `eval_curve()` — вычисление целевой скорости по температуре (linear/spline, clamping, OFF ниже первой точки) |
| 865–870 | `lp_update()` — RC-фильтр нижних частот (сглаживание) |

#### РАЗДЕЛ I: NVS load/save для FAN, PUMP, LED, HOURS (строки 870–960)

| Функция | Что делает |
|---------|-----------|
| `fan_set_defaults()` | Кривая по умолчанию: [30°→50%, 50°→50%, 70°→100%, 110°→100%] |
| `fan_load_from_nvs()` / `fan_save_to_nvs()` | Чтение/запись blob из NVS |
| `pump_set_defaults()` | Кривая: [30°→0%, 55°→25%, 75°→60%, 110°→100%] |
| `pump_load_from_nvs()` / `pump_save_to_nvs()` | Чтение/запись blob |
| `led_prof_set_defaults()` / `led_prof_load()` / `led_prof_save()` | LED-профиль |
| `hours_load_from_nvs()` / `hours_save_to_nvs()` | Наработка помпы |

#### РАЗДЕЛ J: LED-управление (строки 960–1100)

| Функция | Что делает |
|---------|-----------|
| `scale_bright()` | Масштабирование яркости r/g/b |
| `led_refresh_safe()` | Безопасный refresh с антидребезгом (мин. 17мс) и retry |
| `leds_apply_rgb()` | Окрашивание всех 20 LED одним цветом |
| `leds_apply_solid()` | Моно-цвет с масштабом яркости |
| `leds_apply_custom()` | Кастомные цвета для каждого LED |
| `leds_off()` | Выключение LED (clear + refresh) |
| `leds_init()` | Инициализация RMT WS2812 (GPIO 27, 20 LED, 512 symbol buffer, no DMA) |

#### РАЗДЕЛ K: Парсеры команд (строки 1100–1320)

| Функция | Формат | Назначение |
|---------|--------|-----------|
| `apply_lx_bytes()` | `LX` + ver + mode + brightness + [rgb\|custom\|gradient] | LED-профиль (универсальный) |
| `parse_curve_bytes_into()` | `FC`/`PC` + ver + source + mode + count + [hyst] + points | Парсинг кривой fan/pump |
| `apply_fc_bytes()` | Обёртка FC | Применить кривую FAN |
| `apply_pc_bytes()` | Обёртка PC | Применить кривую PUMP |

#### РАЗДЕЛ L: Тахометр (строки 1320–1630)

| Функция | Что делает |
|---------|-----------|
| `tach_isr()` (IRAM) | ISR на NEGEDGE — счёт импульсов с антидребезгом (5мс мин. интервал) |
| `tach_init()` | Настройка GPIO 18/19 INPUT + PULLUP, ISR на NEGEDGE |
| `tach_sample_and_publish()` | Каждую секунду: считать edges → raw RPM → *scale → clamp к 1800 max → проверка аварий (45с stall) → отправка BLE/UART |
| `rpm_notify_ble()` | BLE notify: {rpm1, rpm2, flags} packed 12 bytes |
| `rpm_autocalibrate()` | Раскрутка 100% 15с → замер → вычисление scale = 1800/raw → NVS |

#### РАЗДЕЛ M: DS18B20 (температура воды) (строки 1530–1630)

| Функция | Что делает |
|---------|-----------|
| `ow_drive_low()`, `ow_release_bus()`, `delay_us()` | Битбанг 1-Wire на GPIO 13 |
| `onewire_reset()`, `onewire_write_byte()`, `onewire_read_byte()` | 1-Wire протокол |
| `ds18b20_crc8()` | CRC8 Dallas проверка scratchpad |
| `ds18b20_read_celsius()` | Полный цикл: reset → SKIP ROM → CONVERT T (900мс) → READ SCRATCHPAD → CRC → °C |
| `ds18b20_task()` | FreeRTOS задача: каждую 1с читает DS18B20 → обновляет g_water_temp_c → UART/BLE notify |

#### РАЗДЕЛ N: BLE GATT callbacks (строки 1630–2050)

| Callback | UUID | Операция |
|----------|------|---------|
| `temp_write_cb()` | 0xFFE1 | Write: принимает пару {cpu,gpu} int32 (8 байт) |
| `fan_cfg_write_cb()` | 0xFFE2 | Write: парсит FC-пакет (кривая вентиляторов) |
| `led_write_cb()` | 0xFFE3 | Write: LX-пакет или простой RGB(A) |
| `pump_cfg_write_cb()` | 0xFFE4 | Write: парсит PC-пакет (кривая помпы) |
| `rpm_read_cb()` | 0xFFE5 | Read: {rpm1, rpm2, flags} 12 байт |
| `hours_access_cb()` | 0xFFE6 | Read/Write: pump_hours_t blob |
| `water_read_cb()` | 0xFFE7 | Read: int32 температура воды |
| `ctrl_write_cb()` | 0xFFE9 | Write: команды PG/ST/SP/LK/LP/OB/DL (2–3 байта) |
| `loop_stat_read_cb()` | 0xFFEA | Read: 1 байт (0=off, 1=ok, 2=broken) |

#### РАЗДЕЛ O: GAP, Advertising, BLE Init (строки 2050–2155)

| Функция | Что делает |
|---------|-----------|
| `gap_event()` | Обработка connect / disconnect / adv_complete; управление LED, PWM при дисконнекте |
| `start_advertising()` | Запуск BLE advertising: имя «PROEKT1», UUID 0xFFE0, undirected connectable |
| `on_sync()` | Настройка адреса, запуск рекламы |
| `ble_stack_init_manual()` | Инициализация NimBLE (Legacy VHCI или полный контроллер путь) |

#### РАЗДЕЛ P: UART-парсер (строки 2155–2550)

Потоковый парсер бинарных команд по UART0 (115200 бод).

| Команда | Формат | Описание |
|---------|--------|---------|
| `TT` | `TT` + int32×2 (10 байт) | Температуры CPU + GPU от ПК |
| `FC` | `FC` + ver + src + mode + N + [hyst] + N×3 | Кривая вентиляторов |
| `PC` | `PC` + ver + src + mode + N + [hyst] + N×3 | Кривая помпы |
| `LX` | `LX` + ver + mode + br + [rgb\|custom\|gradient] | LED-профиль |
| `LK` | `LK` + byte | Флаг «LED без подключения» (0/1) |
| `LP` | `LP` + byte | Флаг «защита контура» (0/1) |
| `HR` | `HR` + op(`R`/`W`/`F`) + [blob] | Чтение/запись часов помпы |
| `PG` | `PG` (2 байта) | Запуск продувки |
| `ST` | `ST` (2 байта) | Старт системы → нормальное управление |
| `SP` | `SP` (2 байта) | Стоп → всё выключить, guard 1.5с |
| `OB` | `OB` + byte | Яркость OLED (0–255) |
| `OD` | `OD` (2 байта) | Диагностика OLED (шахматный паттерн) |

**Исходящие пакеты (ESP→ПК):**

| Команда | Формат | Описание |
|---------|--------|---------|
| `RP` | `RP` + int32×2 + uint32 (14 байт) | Калиброванные RPM fan1, fan2, flags |
| `WT` | `WT` + int32 (6 байт) | Температура воды |
| `HR` | `HR` + pump_hours_t blob | Ответ на запрос часов |

#### РАЗДЕЛ Q: Control task (строки 2550–2640)

Основной контур управления, выполняется каждые 200мс:

1. Проверка USB timeout (5с без TT → disconnect)
2. Если калибровка или продувка — пропуск
3. **Pump boost** (после продувки): 3 фазы (ramp up→hold→ramp down)
4. Если нет свежих температур — PWM=0%
5. Если STOP — PWM=0%
6. Нормальный режим: `pick_source_temp()` → `eval_curve()` → RC-фильтр → гистерезис → PWM
7. Каждую 1с: `tach_sample_and_publish()` — замер RPM

#### РАЗДЕЛ R: LED task (строки 2640–2780)

FreeRTOS задача с шагом ~80мс:

- Проверяет подключение (BLE/USB) или флаг keep_on
- Режимы: OFF, SOLID (одноцветный), CUSTOM (поадресный), BLINK, BREATHE (синус), **GRADIENT_ANIM** (волна подсветки)
- Безопасная переинициализация RMT при ошибках
- Mutex-защита операций

#### РАЗДЕЛ S: Продувка / Purge (строки 2780–2880)

Последовательность продувки контура воздухом:

1. Стоп вентиляторов и помпы
2. Плавное открытие клапана (40%→100% за 3с)
3. Пауза 1с + воздушная пауза 1с
4. Помпа: ramp 40→100% (1с) → hold 100% (7с) → ramp 100→40% (1с)
5. Стоп, деактивация клапана
6. Установка флага boost_pending (NVS-персистентный)

#### РАЗДЕЛ T: app_main() — точка входа (строки 2880–3060)

Последовательность инициализации:

1. **КРИТИЧНО**: pin FAN/PUMP GPIO LOW (чтобы не раскрутились при старте)
2. NVS flash init (с fallback erase)
3. Загрузка кривых fan/pump из NVS
4. Загрузка часов помпы
5. Очистка флага boost
6. Загрузка флага keep_on для LED
7. Создание LED mutex + init LED
8. Инициализация LEDC (PWM) для fan/pump/valve
9. Инициализация тахометра
10. Инициализация Loop protection (GPIO + NVS + задача)
11. UART init + задача
12. DS18B20 задача
13. **BLE init** (NimBLE, GATT-сервисы, advertising)
14. Запуск задач: control_task, led_task, oled_task

#### РАЗДЕЛ U: RPM-калибровка (строки 3060–3140)

- `rpm_scale_load()` — загрузка масштабных коэффициентов из NVS
- `rpm_scale_save()` — сохранение
- `rpm_autocalibrate()` — автокалибровка: 100% PWM 15с → замер → scale = 1800/raw

#### РАЗДЕЛ V: OLED task (строки 3140–3764)

Отрисовка интерфейса на OLED-дисплее (64×128 portrait):

| Элемент | Описание |
|---------|---------|
| **3 секции температур** | ЦП, ГП, ВОДА — каждая: метка 1× + число 2× масштаб + °C |
| **Статус-бар** (нижние 20px) | Иконки + текст: ЗАГРУЗКА → ПОДКЛЮЧАЮ → БТ/ЮСБ/ГОТОВ |
| **Анимации** | Побуквенное появление: ЗАГРУЗКА (2 цикла, 94мс), ПОДКЛЮЧАЮ (2×11 фрейма, 125мс), ПРОДУВКА (цикличная) |
| **Ошибки** | Мигание 1Гц: err1=стал вентилятора, err2=BLE HW, err3=UART HW, err4=DS18B20 dead, err5=ЗАЩИТА, err6=перегрев воды |
| **Screen timeout** | 10 мин без подключения → fade-out (3с), на подключение → fade-in (3с) |
| Сглаживание | `oled_smooth_region()` — заполнение «ступенек» между пикселями при масштабировании |

#### РАЗДЕЛ W: Клапан PWM (строки 3690–3740)

- `valve_pwm_init()` — LEDC TIMER_2, CHANNEL_2, GPIO 25, 30kHz
- `valve_pwm_set_percent()` — управление ШИМ клапана (0% = вода, 100% = воздух)

#### РАЗДЕЛ X: Loop protection monitor (строки 3740–3764)

- `loopprot_task()` — задача 20Гц: переключает LOOP_OUT, считает edges на LOOP_IN
- Окно 10 тактов (500мс): >=8 edges → «петля ОК», <=1 → «обрыв»
- При обрыве: принудительный STOP, BLE notify
- При восстановлении: BLE notify

---

### gatt_svr.c

**Файл:** `main/gatt_svr.c` (262 строки) — пример GATT-сервиса из NimBLE bleprph sample. Содержит demo-характеристику с 128-bit UUID. **Не участвует в основной логике** — основные GATT-сервисы определены в `main.c` (массив `gatt_svcs[]`).

### bleprph.h

**Файл:** `main/bleprph.h` — заголовок: экспортирует `gatt_svr_init()` и `gatt_svr_register_cb()`. Включает определения UUID для Alert Notification Service (не используется в PROEKT1).

---

## 3. appPROEKT1/ — Windows-приложение

```
appPROEKT1/
├── PROEKT1.py                  # ★ ГЛАВНЫЙ ФАЙЛ (4452 строки) — GUI + логика Windows-приложения
├── config.json                 # Пользовательские настройки (autostart, transport, led_profiles, oled_brightness)
├── curves.json                 # Кривые fan/pump + пресеты + hysteresis
├── PROEKT1.spec                # PyInstaller спецификация для сборки .exe
├── rocket.ico                  # Иконка приложения
├── cmd запуска.txt             # Справка по запуску
├── PROEKT1_log                 # Файл лога приложения
├── curve_graph.png             # Скриншот/превью графика кривой
│
├── LibreHardwareMonitor.exe    # Утилита для чтения температур CPU/GPU
├── LibreHardwareMonitor.config # Конфигурация LHM
├── LibreHardwareMonitor.exe.config # .NET config LHM
├── LibreHardwareMonitorLib.dll # Библиотека LHM (загружается через pythonnet/clr)
├── LibreHardwareMonitorLib.xml # XML документация LHM
├── LibreHardwareMonitor.sys    # Старый WinRing0 driver (не используется новой DLL)
├── LibreHardwareMonitor.sys.bak # Backup driver
├── PawnIO.sys                  # PawnIO kernel driver (для CPU temp через LHM)
├── PawnIO.cat                  # Каталог подписи PawnIO
├── pawnio.inf                  # INF для PawnIO
├── PawnIO_setup.exe            # Самодостаточный установщик PawnIO (используется для авто-установки)
│
├── Aga.Controls.dll            # Зависимость LHM (UI)
├── Aga.Controls.pdb            # Debug symbols
├── HidSharp.dll                # USB HID библиотека
├── Microsoft.Win32.TaskScheduler.dll # Планировщик задач
├── Newtonsoft.Json.dll         # JSON для .NET
├── OxyPlot.dll                 # Графики (LHM)
├── OxyPlot.WindowsForms.dll    # Графики WinForms
├── System.CodeDom.dll          # .NET CodeDom
│
├── __pycache__/                # Python bytecode cache
├── build/                      # PyInstaller build artifacts
└── .github/                    # CI/CD (если есть)
```

### PROEKT1.py — Подробная карта

| Строки | Класс / Функция | Назначение |
|--------|-----------------|-----------|
| 1–100 | Импорты + тема | PySide6, serial, struct, psutil, ctypes. Тёмная тема (QSS), Mica/Acrylic backdrop |
| 100–170 | `FramelessWindowMixin` | Mixin для перетаскивания безрамочных окон + тень |
| 170–280 | Backend init | `ensure_serial_backend()` — динамическая загрузка pyserial + bleak |
| 280–350 | Глобальные переменные | RPM lock, water temp, loop status, BLE UUID-ы (совпадают с прошивкой) |
| 348–540 | `BLETempSender` | Thread: BLE-подключение к ESP32, отправка TT, приём notify (RPM, Water, LoopStat), команды FC/PC/LX/PG/ST/SP |
| 541–870 | `USBTempSender` | Thread: USB/Serial подключение, бинарный протокол TT/FC/PC/LX/ST/SP/PG/HR/LK/LP/OB/DL, парсер RP/WT/LS |
| 873–1085 | `ConsoleReporter` | Thread: периодический вывод в консоль (температуры, RPM, статус) |
| 900–1065 | Чтение температур | `find_latest_log()` → LibreHardwareMonitor CSV → `read_libre_temps()` → `_pick_cpu_index()` / `_pick_gpu_index()` → `get_current_temps()` |
| 1068–1085 | `start_lhm()` | Запуск LibreHardwareMonitor.exe с CSV-логированием |
| 1086–1305 | `CurveEditor` (QWidget) | Визуальный редактор кривой: рисование точек, drag-and-drop, Catmull-Rom preview, правая кнопка — удалить |
| 1307–1605 | `FanPumpCurveDialog` | Диалог настройки кривых Fan/Pump: два CurveEditor + интерполяция + source + hysteresis + пресеты |
| 1606–2030 | `ColorPalette` (QFrame) | Виджет палитры цветов для LED: цветовое колесо, RGB-ползунки, выбор цвета |
| 2033–2300 | `LEDCustomDialog` | Диалог кастомной подсветки: 20 LED × RGB, градиент, яркость, скорость анимации |
| 2303–2635 | `SettingsDialog` | Настройки: autostart, transport (BLE/USB), purge on shutdown/sleep, часы помпы, loop protection, OLED яркость |
| 2637–2923 | `TriStateSwitch` (QWidget) | Кастомный ползунок 3 позиции (OFF / AUTO / ON) с анимацией |
| 2925–4452 | `MainWindow` | Главное окно: |
| | | — Отображение температур CPU/GPU/Water |
| | | — RPM вентиляторов |
| | | — Кнопки: настройки кривых, LED, настройки, продувка |
| | | — Статус подключения (BLE/USB) |
| | | — System tray (сворачивание) |
| | | — Обработка shutdown/sleep (продувка перед выключением) |
| | | — Управление LibreHardwareMonitor |

### config.json — Настройки приложения

```json
{
  "autostart": false,          // Автозапуск с Windows
  "minimized": false,          // Запуск свёрнутым
  "keep_led_on_disconnected": false,  // LED без ПК
  "loop_protection": true,     // Защита контура
  "purge_on_shutdown": true,   // Продувка при выключении
  "purge_on_sleep": true,      // Продувка при сне
  "brightness": 7,             // Яркость LED (0-10 или 0-255)
  "transport": "BLE",          // Транспорт: "BLE" или "USB"
  "led_profiles": { ... },     // Сохранённые LED-профили
  "oled_brightness": 5,        // Яркость OLED (0-10)
  "delay_on_seconds": 0,       // Задержка включения
  "delay_off_seconds": 10      // Задержка выключения
}
```

### curves.json — Кривые управления

```json
{
  "fan_curve": [[t1,s1], [t2,s2], ...],      // Точки [°C, %] для вентиляторов
  "pump_curve": [[t1,s1], [t2,s2], ...],     // Точки [°C, %] для помпы
  "source_mode": 2,                           // 0=CPU, 1=GPU, 2=MAX
  "presets": { "name": { fan_curve, pump_curve } },
  "selected_preset": "Стандарт",
  "hyst_fan": 5,                              // Гистерезис fan (%)
  "hyst_pump": 5                              // Гистерезис pump (%)
}
```

---

## 4. components/ — Внешние компоненты

```
components/
├── esp_littlefs/                  # Компонент LittleFS для ESP-IDF (файловая система на flash)
│   ├── CMakeLists.txt
│   ├── include/                   # Заголовки esp_littlefs.h
│   ├── src/                       # Реализация VFS + LittleFS core
│   ├── Kconfig                    # Menuconfig опции
│   └── ...
│
└── u8g2_port/                     # Порт библиотеки U8g2 для ESP-IDF (OLED-графика)
    ├── CMakeLists.txt
    ├── u8g2_espidf_port.c         # SW I2C реализация (битбанг SDA/SCL)
    ├── u8g2_espidf_port.h         # API: set_pins(), probe(), callbacks для U8g2
    └── README.md
```

> **Примечание:** В текущей прошивке OLED управляется напрямую через I2C master (без U8g2), однако компонент u8g2_port подключён в CMakeLists.txt и заголовок включён.

---

## 5. third_party/

```
third_party/
└── u8g2/                          # Полная библиотека U8g2 (универсальная графика для OLED/LCD)
    └── (исходники u8g2)
```

---

## 6. tools/ — Утилиты калибровки

```
tools/
├── README.md                      # Документация по использованию утилит
├── calibrate_fans.py              # CLI-утилита калибровки RPM (USB/BLE/AUTO)
├── calibrate_gui.py               # GUI для калибровки (PySide6)
├── calibrate.ps1                  # PowerShell-скрипт быстрой USB-калибровки
└── send_curve_v2.ps1              # PowerShell-скрипт отправки кривой на устройство
```

**Примечание:** Калибровка по UART (`VC` команда) удалена из основной прошивки. Утилиты могут использовать BLE (write to 0xFFE8) или устаревший UART-путь.

---

## 7. build/ — Артефакты сборки

```
build/                             # CMake + Ninja build output
├── flasher_args.json              # Аргументы для esptool (flash адреса, файлы)
├── project_description.json       # Описание проекта ESP-IDF
├── compile_commands.json          # Для clangd/IDE
├── bootloader/                    # Bootloader build
├── partition_table/               # Скомпилированная partition table
├── esp-idf/                       # Скомпилированные компоненты ESP-IDF
└── config/                        # sdkconfig.h и cmake-кеш config

managed_components/
└── espressif__led_strip/          # Скачанный компонент led_strip (WS2812 RMT driver)

bin/1/                             # Пустая папка (видимо, для бинарных артефактов)

build_check/                       # Проверочная сборка (CMakeCache)
```

---

## 8. Протокол обмена (BLE + UART)

### BLE Service UUID: 0xFFE0, Device Name: "PROEKT1"

| Характеристика | UUID | Тип | Описание |
|----------------|------|-----|---------|
| Temperature | 0xFFE1 | Write | {cpu_temp, gpu_temp} — 2×int32 LE |
| Fan Config | 0xFFE2 | Write | FC-пакет (кривая вентиляторов) |
| LED | 0xFFE3 | Write | LX-пакет или RGB(A) 3–4 байта |
| Pump Config | 0xFFE4 | Write | PC-пакет (кривая помпы) |
| RPM | 0xFFE5 | Read+Notify | {rpm1, rpm2, flags} — 12 байт |
| Hours | 0xFFE6 | Read+Write | pump_hours_t blob |
| Water Temp | 0xFFE7 | Read+Notify | int32 (°C) |
| Control | 0xFFE9 | Write | PG/ST/SP/LK/LP/OB/DL — 2-3 байта |
| Loop Status | 0xFFEA | Read+Notify | 1 байт (0=disabled, 1=ok, 2=broken, 3=restored+was running, 4=auto-started) |

### UART Бинарный протокол (115200 бод, UART0)

Двунаправленный потоковый парсер, все данные бинарные (не текст).

**ПК → ESP32:**
`TT`, `FC`, `PC`, `LX`, `LK`, `LP`, `HR`, `PG`, `ST`, `SP`, `OB`, `OD`, `DL`

**ESP32 → ПК:**
`RP`, `WT`, `HR`, `LS`

---

## 9. Карта GPIO

| GPIO | Назначение | Режим | Частота PWM |
|------|-----------|-------|-------------|
| 2 | Встроенный LED (статус) | OUTPUT | — |
| 13 | DS18B20 (температура воды) | OPEN-DRAIN (1-Wire) | — |
| 16 | FAN PWM | LEDC CH0 / TIMER0 | 25 kHz |
| 17 | PUMP PWM | LEDC CH1 / TIMER1 | 25 kHz |
| 18 | TACH1 (тахометр вентилятора 1) | INPUT PULLUP, ISR NEGEDGE | — |
| 19 | TACH2 (тахометр вентилятора 2) | INPUT PULLUP, ISR NEGEDGE | — |
| 21 | OLED SDA (I2C) | I2C Master | 400 kHz |
| 22 | OLED SCL (I2C) | I2C Master | 400 kHz |
| 25 | Соленоидный клапан (продувка) | LEDC CH2 / TIMER2 | 30 kHz |
| 26 | Loop protection OUT | OUTPUT | — |
| 27 | WS2812 LED strip (20 LED) | RMT TX | 10 MHz RMT |
| 33 | Loop protection IN | INPUT PULLDOWN | — |

---

## 10. NVS-пространства имён

| Namespace | Key | Тип | Описание |
|-----------|-----|-----|---------|
| `fan` | `cfg_v1` | blob | curve_cfg_t — кривая вентиляторов |
| `pump` | `cfg_v1` | blob | curve_cfg_t — кривая помпы |
| `led` | `prof_v1` | blob | led_profile_t — LED-профиль |
| `led` | `keep_on` | u8 | Флаг «LED без подключения» |
| `hours` | `v1` | blob | pump_hours_t — наработка помпы |
| `sys` | `boost_pending` | u8 | Флаг «буст помпы после продувки» |
| `sys` | `loopprot` | u8 | Флаг «защита контура» |
| `cal` | `rpm1_scale` | blob(float) | Калибровочный коэффициент тахо 1 |
| `cal` | `rpm2_scale` | blob(float) | Калибровочный коэффициент тахо 2 |
| `oled` | `bright` | u8 | Яркость OLED (0–255) |
| `oled` | `lang` | u8 | Язык дисплея (0=RU, 1=EN) |

---

## 11. FreeRTOS-задачи

| Задача | Стек | Приоритет | Файл | Что делает |
|--------|------|-----------|------|-----------|
| `fan_pump_ctrl` | 4096 | 5 | main.c `control_task()` | Основной контур ПИД: каждые 200мс считывает температуры, вычисляет кривые, управляет PWM, pump boost, tach sampling |
| `led_task` | 3072 | 4 | main.c `led_task()` | Обновление WS2812 LED по профилю: solid/blink/breathe/gradient анимация, 80мс шаг |
| `oled_task` | 4096 | 3 | main.c `oled_task()` | OLED экран: 3 секции температуры + статус-бар, анимации, ошибки, screen timeout |
| `usb_uart_rx` | 3072 | 5 | main.c `uart_rx_task()` | Приём и парсинг UART-команд от ПК |
| `ds18b20` | 3072 | 4 | main.c `ds18b20_task()` | Чтение DS18B20 каждую 1с, отправка WT по UART/BLE |
| `loopprot` | 2048 | 5 | main.c `loopprot_task()` | Мониторинг целостности шланга (20Гц toggle) |
| `purge` | 3072 | 6 | main.c `purge_task()` | Последовательность продувки (создаётся и удаляется по запросу) |
| `BLE host` | — | — | NimBLE | Стек NimBLE (nimble_port_freertos_init) |

---

## Быстрый поиск по функциональности

| Хочу найти... | Где искать |
|---------------|-----------|
| Управление вентилятором | `main.c`: `fan_pwm_set_percent()`, `eval_curve(&g_fan,...)`, `control_task()` |
| Управление помпой | `main.c`: `pump_pwm_set_percent()`, `pump_drive_voltage_from_percent()`, pump boost (РАЗДЕЛ Q) |
| LED-подсветку | `main.c`: `led_task()`, `leds_apply_*()`, `apply_lx_bytes()`, `led_prof_*()` |
| OLED-дисплей | `main.c`: `oled_task()`, `oled_init()`, `oled_draw_text()`, `oled_flush()`, шрифт k_font5x7 |
| BLE-команды | `main.c`: callbacks (`temp_write_cb`, `ctrl_write_cb`, ...), `gatt_svcs[]` |
| UART-протокол | `main.c`: `sp_feed()`, `sp_try_tt/fc/pc/lx/st/sp/pg/hr/lk/lp/ob()` |
| Продувку (purge) | `main.c`: `purge_task()`, `purge_start()`, `purge_stop()`, valve PWM |
| DS18B20 (вода) | `main.c`: `ds18b20_task()`, `ds18b20_read_celsius()`, 1-Wire битбанг |
| Тахометр (RPM) | `main.c`: `tach_isr()`, `tach_sample_and_publish()`, калибровка `rpm_autocalibrate()` |
| Защиту контура | `main.c`: `loopprot_task()`, LOOP_OUT/LOOP_IN GPIO, g_loop_ok |
| NVS-персистенцию | `main.c`: fan/pump/led _save/_load, hours_*, rpm_scale_*, boost_flag_* |
| GUI-приложение ПК | `appPROEKT1/PROEKT1.py`: `MainWindow`, `BLETempSender`, `USBTempSender` |
| Настройки пресетов | `appPROEKT1/curves.json` + `FanPumpCurveDialog` |
| LED-кастомизацию (ПК) | `appPROEKT1/PROEKT1.py`: `ColorPalette`, `LEDCustomDialog` |
| Чтение температур ПК | `appPROEKT1/PROEKT1.py`: `read_libre_temps()`, `get_current_temps()`, LibreHardwareMonitor |
