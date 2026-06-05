# Стабильное окно PySide6 + QWebEngineView

Дата фикса: 2026-06-06.

Эта заметка фиксирует рабочий способ, который убрал зависания, серые поля, простреливание кликов, мерцание при смене масштаба интерфейса, входе/выходе из fullscreen и смене масштаба в fullscreen.

## Симптомы

- После смены масштаба интерфейс визуально оставался на экране, но клики проходили сквозь приложение в окна под ним.
- После переходов 100% -> 150% -> 100% часть контролов была живая, а часть селекторов и кнопок становилась недоступной.
- Иногда приложение выглядело замороженным: ESP32 и фоновые данные работали, но UI больше не принимал мышь.
- При переносе между экранами и fullscreen-переходах появлялись серые поля, сдвиги, двойные рамки или краткие блинки.

## Причина

Главное окно было полупрозрачным на уровне Windows: `WA_TranslucentBackground` приводил к top-level HWND с `WS_EX_LAYERED`.

Для обычных QWidget это терпимо, но `QWebEngineView` рисует содержимое через native child HWND. Получалась плохая комбинация:

- пользователь видит WebEngine-интерфейс;
- Windows hit-test смотрит на alpha/top-level surface;
- центральная web-область может считаться прозрачной;
- `WindowFromPoint` иногда возвращает окно под приложением, например `ConsoleWindowClass`, а не PROEKT1;
- после смены масштаба, fullscreen или DPI-переходов это состояние могло закрепляться.

То есть проблема была не в React/HTML и не в кривой мыши, а в конфликте per-pixel alpha top-level окна с native surface WebEngine.

## Рабочий способ

Главное правило: главное окно должно быть непрозрачной hit-test поверхностью. Скругления надо делать не через прозрачный top-level alpha, а через native region mask.

1. Главное окно `MainWindow` не должно включать `WA_TranslucentBackground`.

   Рабочие атрибуты:

   ```python
   self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
   self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)
   self.setAutoFillBackground(True)
   self.setStyleSheet("QMainWindow#mainWindow { background: #121431; border: none; }")
   ```

2. После создания окна, showEvent, смены темы, смены масштаба и применения rounded mask надо закреплять opaque hit surface.

   В реализации это делает:

   ```python
   _set_main_window_opaque_hit_surface(reason)
   ```

   Она:

   - выключает `WA_TranslucentBackground`;
   - выключает `WA_NoSystemBackground`;
   - включает `autoFillBackground`;
   - задает фон главного окна цветом backing surface;
   - очищает опасные WinAPI стили `WS_EX_TRANSPARENT` и `WS_EX_LAYERED`;
   - пишет в лог `window.hit_surface.opaque`.

3. Если Windows снова поставил `WS_EX_LAYERED`, его надо снять через WinAPI и обновить frame style:

   ```python
   _clear_native_layered_style(hwnd_int, reason)
   ```

   Ожидаемое состояние в логе после фикса:

   ```text
   window.hit_test.clear_layered_style ... "after":"0x0"
   window.hit_surface.opaque ... "exStyle":"0x0"
   ```

4. Скругление окна делается через region, а не через прозрачность.

   Рабочая схема:

   - `SetWindowRgn` на главный HWND;
   - `SetWindowRgn` на native HWND WebEngine;
   - `WA_TranslucentBackground` у main window остается `False`;
   - `WA_TranslucentBackground` у web view тоже остается `False`;
   - web page получает непрозрачный backing color через `--proekt1-window-bg`.

5. `_reapply_translucent_window()` больше не должен возвращать прозрачность.

   Он оставлен только как compatibility shim и должен вызывать opaque guard:

   ```python
   self._set_main_window_opaque_hit_surface("reapply_translucent_window.compat")
   ```

6. Для mixed-DPI и fullscreen переходов нельзя лечить проблему пересозданием WebEngine при каждом подозрительном событии.

   Рабочая тактика:

   - во время drag и screen transition не делать агрессивный rebuild;
   - во время удержания ЛКМ делать только мягкую проверку и position-only pin;
   - после release применять финальную геометрию и region;
   - не дергать top-level размер мелкими nudges;
   - сохранять активную вкладку через session state.

## Здоровые признаки в логе

Хороший лог после фикса выглядит так:

```text
window.hit_surface.opaque ... "translucent":false ... "exStyle":"0x0"
window.rounded_mask.apply ... "windowRgn":"COMPLEXREGION"
web.native_surface.verify ... "hitRoot":"<mainHwnd>" ... "webRootOk":true ... "ok":true
```

Важная оговорка: старый диагностический флаг `hitOk:false` может появиться, если `WindowFromPoint` попал в главный HWND, а не прямо в child HWND WebEngine. Это не click-through, если одновременно верно:

```text
hitRoot == mainHwnd
webRootOk == true
posDelta == 0
sizeDelta == 0
ok == true
```

То есть после opaque-hit-surface фикса правильным владельцем клика может быть main HWND. Это нормально.

## Плохие признаки в логе

Если баг вернется, сначала искать:

```text
"exStyle":"0x80000"
WS_EX_LAYERED
WS_EX_TRANSPARENT
ConsoleWindowClass
"hitRoot" != "mainHwnd"
renderProcessTerminated
surface_recovery.defer_recreate
web.recreate
Unable to set geometry
```

Особенно опасно, если `WindowFromPoint` в центре видимого интерфейса возвращает окно под приложением. Это означает, что top-level снова стал прозрачным для hit-test.

## Чего нельзя возвращать

- Не включать `WA_TranslucentBackground=True` на `MainWindow`.
- Не делать скругление через прозрачный top-level alpha.
- Не оставлять `WS_EX_LAYERED` на главном HWND после смены масштаба или fullscreen.
- Не чинить серые поля пересозданием WebEngine на каждый drag/resize tick.
- Не делать size nudge после fullscreen как универсальное лекарство.
- Не очищать rounded region у нормального visible WebEngine, иначе вернутся углы/рамки.

## Где реализация

Основная реализация находится в `appPROEKT1/PROEKT1.py`:

- `_set_main_window_opaque_hit_surface(reason)`
- `_clear_native_layered_style(hwnd_int, reason)`
- `_set_web_view_opaque_input_surface(reason)`
- `_apply_rounded_mask()`
- `_reapply_translucent_window()`
- `_apply_interface_scale(...)`

Этот способ подтвержден вручную: приложение осталось стабильным при смене размеров интерфейса, входе и выходе из fullscreen, а также при смене размера интерфейса внутри fullscreen.
