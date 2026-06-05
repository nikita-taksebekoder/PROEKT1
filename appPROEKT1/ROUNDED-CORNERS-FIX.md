# Решение: чистые скруглённые углы в PySide6 + QWebEngineView на Windows

Задача: фреймлесс-окно `QMainWindow` с `WA_TranslucentBackground` и `QWebEngineView` внутри должно иметь чёткие скруглённые углы 24px — и до, и после любого числа циклов веб-fullscreen.

---

## Итоговое решение (слои, работающие вместе)

### 1. MainWindow: только Qt рисует силуэт, DWM отключён

`_RoundedWindowFrame.paintEvent` рисует антиалиасинговый `QPainterPath` с `fillPath` радиусом 24px. Пиксели за пределами пути имеют alpha=0 — MainWindow прозрачна там.

Обязательно:
```python
self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
self.setAutoFillBackground(False)
self.setWindowFlags(Qt.WindowType.FramelessWindowHint | ...)
```

DWM **всегда** принудительно отключён от скругления:
```python
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_DONOTROUND = 1
dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, byref(c_int(1)), sizeof(c_int))
```
Без этого DWM накладывает свой ~8px радиус поверх Qt 24px, и между ними видна прозрачная «корона».

---

### 2. Chromium-HWND: hardware-клип через SetWindowRgn ← **это финальный ключ**

> 2026-06-03 update: после проверки live-drag логов HRGN нельзя очищать у видимого normal-mode `QWebEngineView`: прямоугольный Chromium backing сразу проявляется как «уголки» до отпускания ЛКМ. Стабильная реализация держит `SetWindowRgn(CreateRoundRectRgn)` на верхнем WebView HWND и во время native drag/mixed-DPI переноса; внутренние Chromium child-HWND по-прежнему не клипуются.

> 2026-06-03 mixed-DPI update: при переносе DPR=2 → DPR=1 `screenChanged` может прийти раньше, чем Windows обновит native client rect WebView. В логе это выглядело как `logical=1088×752`, `dpi=96`, но `native=2176×1504`; такой stale rect делает HRGN слишком большим и углы видны на первом экране до release. Перед `SetWindowRgn` нужно сверять scale Win32-rect с текущим DPR: если `GetDpiForWindow()` уже доступен, верить ему раньше Qt DPR; при несовпадении брать размер из logical WebView × current DPR.

> 2026-06-03 smooth-drag update: `SetWindowRgn`/HRGN можно и нужно переустанавливать live во время удержания ЛКМ, но Win32 `SetWindowPos` для native-chain WebEngine во время того же drag запрещён. Лог показал, что live pin смешивал физические и логические размеры: WebView мог стать `2200×1520` на DPR=2 или `550×380` внутри окна `1100×760` после возврата на DPR=1. Native-chain pin выполняется после release/verify, а логическая база для расчётов берётся из `centralWidget().rect()`, не из уже дрейфующего `web_view.width()/height()`.

> 2026-06-03 high-DPI live-position update: свежий лог показал, что live resize-pin нельзя возвращать даже guarded: после `screen.changed.live_high_dpi` WebEngine разгонялся `1375×950 → 2750×1900 → 5500×3800`, интерфейс мерцал и уезжал влево. Разрешён только position-only repair (`SWP_NOSIZE`, `x=0,y=0`) для DPR>1, а HRGN во время такого drag берёт фактический текущий `GetClientRect()`, если Chromium ещё не перешёл на physical-size. DPR=1 по-прежнему ждёт release.

> 2026-06-05 compositor-blink update: после долгой проверки редактора кривых подтверждено, что диагональные/ступенчатые/полные блинки интерфейса были не JS-крэшем и не `renderProcessTerminated`, а повреждением аппаратного Chromium compositor-layer внутри прозрачного frameless `QWebEngineView`. Надёжное решение — запускать WebEngine в software compositing: `QTWEBENGINE_CHROMIUM_FLAGS` должен содержать `--disable-gpu --disable-gpu-compositing --disable-gpu-rasterization --disable-zero-copy --disable-accelerated-2d-canvas --disable-webgl`, а `QWebEngineSettings` должен выключать `WebGLEnabled` и `Accelerated2dCanvasEnabled`. После этого пользователь подтвердил: блинки исчезли полностью.

`QWebEngineView` создаёт несколько вложенных нативных HWND (GPU compositor, render widget, input). Chromium рисует в них **opaque-пиксели в прямоугольных границах**. Qt per-pixel alpha их не трогает — они пробиваются сквозь скруглённый силуэт, особенно накапливая GPU-кэш после fullscreen.

Решение — `SetWindowRgn(CreateRoundRectRgn(...))` на верхний `web_view` HWND. Внутренние Chromium child-HWND не клипуются:

```python
def _apply_web_view_native_round_rgn(self):
    w, h = web_view.width(), web_view.height()
    radius_diam = 48  # 2 * 24px

    gdi32.CreateRoundRectRgn.argtypes = [c_int, c_int, c_int, c_int, c_int, c_int]
    gdi32.CreateRoundRectRgn.restype = c_void_p
    user32.SetWindowRgn.argtypes = [HWND, c_void_p, BOOL]

    def apply_to(hwnd_int, cw, ch):
        rgn = gdi32.CreateRoundRectRgn(0, 0, cw + 1, ch + 1, radius_diam, radius_diam)
        if rgn:
            user32.SetWindowRgn(HWND(hwnd_int), rgn, True)  # SetWindowRgn owns the rgn

    top_hwnd = int(web_view.winId())
    apply_to(top_hwnd, w, h)
```

Это **hardware-клип** — работает независимо от GPU-состояния, сбрасывает накопленный Chromium-кэш.

Вызывается в `resizeEvent` и внутри `_reset_web_view_clip` (потому что `clearMask()` может сбросить region).

---

### 3. Веб-fullscreen: только через setGeometry, без showFullScreen

`showFullScreen()` / `showNormal()` на Windows **пересоздают нативный HWND** → Qt теряет `WS_EX_LAYERED` → per-pixel alpha пропадает навсегда. Повторный `setAttribute(WA_TranslucentBackground)` не возвращает его.

Правильный путь:
```python
# Вход во fullscreen:
self._web_fs_restore_geometry = self.geometry()
screen_geom = self.screen().geometry()
self.setGeometry(screen_geom)          # окно просто расширяется до экрана

# Выход:
self.setGeometry(self._web_fs_restore_geometry)  # возвращается назад
```
Window state не меняется → `WS_EX_LAYERED` сохраняется → per-pixel alpha жива через любое число циклов.

---

### 4. Фоновые слои: только transparent в нормальном режиме

html, body и `page().setBackgroundColor` **обязаны быть прозрачными** в нормальном режиме. Любой opaque-цвет там создаёт прямоугольный подслой, видный за пределами Qt-силуэта.

Тёмный фон только в fullscreen:
```css
body.proekt1-runtime.fullscreen { background: #0a0b20 !important; }
```

---

### 5. ctypes на 64-bit Windows: всегда argtypes

Без явного `argtypes` ctypes считает все параметры `c_int` и усекает 64-bit HWND из `int(widget.winId())` до 32-bit. API возвращает успех, но действует на случайный HWND. Всегда:
```python
user32.SetWindowPos.argtypes = [HWND, HWND, c_int, c_int, c_int, c_int, UINT]
user32.SetWindowPos.restype = BOOL
```

---

### 6. WebEngine compositor: software mode обязателен

Для прозрачного frameless `QWebEngineView` аппаратный Chromium compositor может повреждать кадр без крэша процесса: тёмный диагональный слой, серая «лесенка», краткий полный blink или зависший фрагмент до следующего repaint. Это особенно проявляется при быстром hover в редакторе кривых, при reset/max-points и после restore из minimized.

Стабильный режим:
```python
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join([
    "--disable-gpu",
    "--disable-gpu-compositing",
    "--disable-gpu-rasterization",
    "--disable-zero-copy",
    "--disable-accelerated-2d-canvas",
    "--disable-webgl",
])

settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, False)
settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, False)
```

Флаги должны выставляться **до импорта/создания WebEngine**. В `ui-debug.log` при старте должна быть строка `webengine.flags`. Для restore/minimize дополнительно нужен paint-only recovery (`_recover_web_view_after_show()`): stable geometry, HRGN, native redraw, resize event в странице, без reload и без изменения размеров окна.

---

## Хронология попыток (что не сработало и почему)

| Попытка | Что сделано | Почему не помогло |
|---|---|---|
| 1 | Увеличить Qt-радиус до 36px | Обнажил прямоугольный Chromium backing в нормальном режиме |
| 2 | Прозрачный html/body + page background | Убрал прямоугольный слой в нормальном режиме, но fullscreen не починил |
| 3 | DWMWCP_DONOTROUND | Убрал DWM-радиус, но Chromium-HWND остался прямоугольным |
| 4 | `_reapply_translucent_window()` после showNormal | Qt не может вернуть WS_EX_LAYERED на существующий HWND |
| 5 | Geometry-only fullscreen | Сохранило per-pixel alpha, но Chromium GPU-кэш всё равно пробивался |
| 6 | `SetWindowPos(SWP_FRAMECHANGED)` + `RedrawWindow` | ctypes без argtypes → 64-bit HWND усечён, вызовы уходили в никуда |
| 7 | Добавлены argtypes + 1px geometry nudge | Помогло при первом выходе, но не стабильно при повторных циклах |
| **8** | **SetWindowRgn(CreateRoundRectRgn) на верхнем web_view HWND** | **✅ Аппаратный клип, независим от GPU-кэша, работает всегда; HRGN нельзя очищать во время visible drag** |

---

## Файлы

- `appPROEKT1/PROEKT1.py` — реализация:
  - `_apply_web_view_native_round_rgn()` — hardware-клип верхнего WebView HWND
  - `_force_native_redraw()` — форс DWM recomposition (SetWindowPos + RedrawWindow, с argtypes)
  - `_force_geometry_nudge()` — legacy 1px nudge helper; после 2026-06-03 не планируется на fullscreen exit, потому что top-level resize виден как скачок frame
  - `_on_web_fullscreen_requested()` — geometry-only fullscreen
  - `_RoundedWindowFrame` — Qt 24px antialiased rounded silhouette
  - `apply_windows_backdrop()` — DWMWCP_DONOTROUND + COLOR_NONE border
