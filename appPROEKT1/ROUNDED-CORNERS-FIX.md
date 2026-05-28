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

`QWebEngineView` создаёт несколько вложенных нативных HWND (GPU compositor, render widget, input). Chromium рисует в них **opaque-пиксели в прямоугольных границах**. Qt per-pixel alpha их не трогает — они пробиваются сквозь скруглённый силуэт, особенно накапливая GPU-кэш после fullscreen.

Решение — `SetWindowRgn(CreateRoundRectRgn(...))` на web_view HWND и на **все его нативные дети** через `EnumChildWindows`:

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

    def enum_cb(child_hwnd, _):
        r = RECT()
        if user32.GetClientRect(child_hwnd, byref(r)):
            cw_w = r.right - r.left
            cw_h = r.bottom - r.top
            if cw_w >= w - 4 and cw_h >= h - 4:  # только full-size дети
                apply_to(int(child_hwnd), cw_w, cw_h)
        return True

    EnumChildProc = WINFUNCTYPE(BOOL, HWND, LPARAM)
    user32.EnumChildWindows(HWND(top_hwnd), EnumChildProc(enum_cb), 0)
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
| **8** | **SetWindowRgn(CreateRoundRectRgn) на web_view HWND + EnumChildWindows** | **✅ Аппаратный клип, независим от GPU-кэша, работает всегда** |

---

## Файлы

- `appPROEKT1/PROEKT1.py` — реализация:
  - `_apply_web_view_native_round_rgn()` — hardware-клип Chromium HWNDs
  - `_force_native_redraw()` — форс DWM recomposition (SetWindowPos + RedrawWindow, с argtypes)
  - `_force_geometry_nudge()` — 1px nudge для принудительного resizeEvent
  - `_on_web_fullscreen_requested()` — geometry-only fullscreen
  - `_RoundedWindowFrame` — Qt 24px antialiased rounded silhouette
  - `apply_windows_backdrop()` — DWMWCP_DONOTROUND + COLOR_NONE border
