#include <string.h>
#include <math.h>
#include <assert.h>
#include <stdbool.h>
#include <stdlib.h>

#include "sdkconfig.h"

#include "esp_log.h"
#include "esp_err.h"
#include "esp_attr.h"
#include "nvs_flash.h"
#include "nvs.h"

#include "esp_idf_version.h"

#include "driver/gpio.h"
#include "driver/ledc.h"
#include "driver/uart.h"
#include "esp_private/periph_ctrl.h" /* periph_module_reset */
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "led_strip.h"  // WS2812
#include "esp_timer.h"  // esp_timer_get_time for microsecond delays
#include "esp_check.h"   // ESP_RETURN_ON_ERROR
/* U8g2 graphics library */
#include "u8g2.h"
#include "u8g2_espidf_port.h"
/* OLED (SSD1312/SSD1306 compatible over I2C - minimal driver)
 * Prefer new I2C master API on IDF5 to avoid old-driver warnings.
 */
#if defined(__has_include)
#  if __has_include("driver/i2c_master.h")
#    include "driver/i2c_master.h"
#    define HAVE_NEW_I2C 1
#  elif __has_include("esp_driver_i2c.h")
#    include "esp_driver_i2c.h"
#    define HAVE_NEW_I2C 1
#  elif __has_include("driver/i2c.h")
#    include "driver/i2c.h"
#    define HAVE_LEGACY_I2C 1
#  else
#    warning "No I2C header found"
#  endif
#else
#  include "driver/i2c.h"
#  define HAVE_LEGACY_I2C 1
#endif

#if CONFIG_BT_NIMBLE_ENABLED
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "host/ble_gap.h"
#include "host/util/util.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"
#include "os/os_mbuf.h"
#include "esp_bt.h"          // BT controller mem release (we do not enable in Legacy VHCI)
#if !CONFIG_BT_NIMBLE_LEGACY_VHCI_ENABLE
#include "esp_nimble_hci.h"  // HCI for NimBLE (non-legacy)
#endif
/* NimBLE store helpers (forward declarations for some builds) */
void ble_store_config_init(void);
struct ble_store_status_event;
int ble_store_util_status_rr(struct ble_store_status_event *event, void *arg);
#endif

#ifndef M_PI
#define M_PI 3.14159265358979323846f
#endif

/* ===== Settings / UUIDs ===== */
static const char *TAG = "NimBLE_FAN_PUMP";
#if CONFIG_BT_NIMBLE_ENABLED
static uint8_t own_addr_type;
#endif

/* Enable/disable logs */
#define RPM_LOG_ENABLE   1  /* Печатаем рассчитанные RPM (калиброванные) каждые ~1с */
#define RPM_CAL_LOG      1  /* Печатаем «raw» и «cal» RPM для отладки калибровки */
/* BLE UUIDs (16-bit, custom profile) */
#define FAN_SERVICE_UUID     0xFFE0
#define TEMP_CHAR_UUID       0xFFE1
#define FAN_CFG_CHAR_UUID    0xFFE2
#define LED_CHAR_UUID        0xFFE3
#define PUMP_CFG_CHAR_UUID   0xFFE4
#define RPM_CHAR_UUID        0xFFE5  /* RPM read/notify */
#define HOURS_CHAR_UUID      0xFFE6  /* pump hours total (read/write) */
#define WATER_CHAR_UUID      0xFFE7  /* water temp (read/notify) */
#define CTRL_CHAR_UUID       0xFFE9  /* control plane: ST/SP/PG/etc (write) */
#define LOOP_STAT_CHAR_UUID  0xFFEA  /* loop protection status (read/notify) */
#define LED_GPIO             2
#define FAN_PWM_GPIO         16
#define PUMP_PWM_GPIO        17
/* Solenoid valve: inactive=water, active=air purge */
/* Moved off strap pin GPIO15 to avoid boot interference; use a safe GPIO */
#define VALVE_GPIO           25

/* Tachometer GPIOs */
#define TACH1_GPIO           18
#define TACH2_GPIO           19

/* DS18B20 temperature sensor */
#define DS18B20_GPIO         13

/* Tachometer model:
   - Мы считаем только спадающие фронты (NEGEDGE).
   - Для типичных PC-вентиляторов 2 импульса на оборот. Но в реальности счётчик может завышать из-за «дребезга».
   - Поэтому ниже добавлена КАЛИБРОВКА по коэффициенту (scale) и ограничение max, чтобы не превышать паспортные значения. */
#define TACH_PULSES_PER_REV  2

/* Калибровка и ограничения: целимся в 1800 RPM при 100% PWM.
   Физическая формула верна при SCALE=1.0 (2 имп/оборот), сверху ограничиваем 1800. */
#define FAN1_RPM_SCALE   (g_rpm_scale1)
#define FAN2_RPM_SCALE   (g_rpm_scale2)
#define FAN1_RPM_MAX     1800
#define FAN2_RPM_MAX     1800
/* По желанию можно добавить нижнюю границу отображения (паспорт 150), но мы НЕ будем «подтягивать» вверх,
   чтобы видеть реальные низкие значения. Поэтому MIN оставим 0. */
#define FAN1_RPM_MIN     0
#define FAN2_RPM_MIN     0

/* Порог аварии (после калибровки) */
#define RPM_FAULT_MIN        100  /* если подаём >1%, а RPM ниже 100 — считаем «авария» */

/* WS2812 */
#define LED_STRIP_GPIO       27
#define LED_STRIP_LENGTH     20
#define LED_STRIP_RES_HZ     (10 * 1000 * 1000)
#define LED_BRIGHT_DEF       64

/* Loop protection GPIOs (hose presence) */
#define LOOP_OUT_GPIO        26  /* output: drives test level */
#define LOOP_IN_GPIO         33  /* input: reads returned level */

/* Ranges */
#define TEMP_MIN_C           30.0f
#define TEMP_MAX_C           110.0f
/* Water temperature threshold above which err 6 is raised on the OLED status bar */
#define WATER_TEMP_CRIT_C    50
#define SPEED_MIN_PCT        0.0f
#define SPEED_MAX_PCT        100.0f
#define CURVE_POINTS_MAX     16

/* Control and PWM */
#define CTRL_PERIOD_MS         200
/* Use separate LEDC timers for FAN and PUMP to allow different PWM frequencies */
#define LEDC_FAN_FREQ_HZ       25000
/* Raise pump PWM above audible range to make it quiet; adjust if your pump prefers 20 kHz */
#define LEDC_PUMP_FREQ_HZ      25000
#define LEDC_TIMER_RES         LEDC_TIMER_10_BIT
#define LEDC_DUTY_MAX          ((1U << 10) - 1)
/* Solenoid valve PWM (use silent 25 kHz as well to avoid coil whine) */
#define LEDC_VALVE_FREQ_HZ     30000

/* Pump boost profile after purge->stop sequence: durations in ms */
#define PUMP_BOOST_PHASE1_MS   2000  /* 0% -> 100% */
#define PUMP_BOOST_HOLD_MS     3000  /* hold at 100% */
#define PUMP_BOOST_PHASE2_MS   2000  /* 100% -> target */

/* Defaults */
#define DEF_INTERP_MODE      1        /* 0=linear, 1=spline */
#define DEF_SOURCE_MODE      2        /* 0=CPU, 1=GPU, 2=MAX */
#define DEF_RC_TAU_SEC       1.5f
#define DEF_HYST_PCT         5.0f
#define STALE_MS             5000

/* Fan specifics */
#define FAN_MIN_ON_PCT       30.0f
#define PUMP_MIN_ON_PCT      30.0f
#define OFF_BELOW_FIRST_PT

/* Pump control mapping: desired vs. drive calibration
     Desired targets (user's request):
         - 100% command -> 5.0 V average on pump
         - 30%  command -> 2.0 V average on pump
         - 0%   command -> 0.0 V
     Drive calibration (empirical), to better match measured results:
         Measured with previous drive equal to desired: 100% -> 8.0 V, 30% -> 4.6 V.
         To compensate, we scale the "drive" voltage so that:
             - at 30% the drive is ~0.87 V (2.0 * 2.0/4.6)
             - at 100% the drive is ~3.125 V (5.0 * 5.0/8.0)
     We compute duty from DRIVE voltage, not desired.
*/
/* Measured/assumed pump supply under load (adjust if needed) */
#define PUMP_SUPPLY_V       11.3f
#define PUMP_V_LIMIT        5.0f
#define PUMP_V_AT30         2.0f
#define PUMP_SPLIT_PCT      30.0f

/* Calibrated drive voltages to aim closer to desired measured output */
#define PUMP_DRV_V_AT30     0.87f     /* volts at 30% command (scaled to yield ~2.0V measured average) */
#define PUMP_DRV_V_AT100    3.125f    /* volts at 100% command (scaled to yield ~5.0V measured average) */

/* Forward declaration: used before full definition further below */
static inline float clampf(float x, float a, float b);

static inline float pump_target_voltage_from_percent(float pct){
    float p = clampf(pct, 0.0f, 100.0f);
    float v;
    if (p <= PUMP_SPLIT_PCT) {
        v = (PUMP_V_AT30 / PUMP_SPLIT_PCT) * p; /* linear 0..30% */
    } else {
        float slope = (PUMP_V_LIMIT - PUMP_V_AT30) / (100.0f - PUMP_SPLIT_PCT);
        v = PUMP_V_AT30 + slope * (p - PUMP_SPLIT_PCT);
    }
    if (v < 0.0f) v = 0.0f;
    if (v > PUMP_V_LIMIT) v = PUMP_V_LIMIT;
    return v;
}

/* Convert percent to DRIVE voltage using calibrated points (0%->0V, 30%->PUMP_DRV_V_AT30, 100%->PUMP_DRV_V_AT100) */
static inline float pump_drive_voltage_from_percent(float pct){
    float p = clampf(pct, 0.0f, 100.0f);
    float v;
    if (p <= PUMP_SPLIT_PCT) {
        v = (PUMP_DRV_V_AT30 / PUMP_SPLIT_PCT) * p;
    } else {
        float slope = (PUMP_DRV_V_AT100 - PUMP_DRV_V_AT30) / (100.0f - PUMP_SPLIT_PCT);
        v = PUMP_DRV_V_AT30 + slope * (p - PUMP_SPLIT_PCT);
    }
    if (v < 0.0f) v = 0.0f;
    /* We deliberately DO NOT clamp to PUMP_V_LIMIT here because this is drive voltage */
    return v;
}

/* Diagnostics */
#define FAN_PWM_INVERT       0
#define FAN_PWM_SELFTEST     0

/* UART (USB) — shared with IDF logging (UART0) */
#define UART_PORT            UART_NUM_0
#define UART_BAUD            115200
#define UART_RX_BUF_HW       2048
#define UART_TX_BUF_HW       0
#define UART_TASK_STACK      3072
#define UART_TASK_PRIO       5

/* ===== Types ===== */
typedef enum { SRC_CPU=0, SRC_GPU=1, SRC_MAX=2 } src_sel_t;
typedef enum { IM_LINEAR=0, IM_SPLINE=1 } interp_mode_t;

typedef struct { float t; float s; } curve_point_t;

typedef struct {
    uint8_t version;      /* 1 */
    uint8_t source_mode;  /* SRC_* */
    uint8_t interp_mode;  /* IM_* */
    uint8_t count;        /* 2..16 */
    float   rc_tau_sec;   /* s */
    float   hyst_pct;     /* pp */
    curve_point_t pts[CURVE_POINTS_MAX];
} curve_cfg_t;

typedef enum {
    LED_MODE_SOLID   = 0,
    LED_MODE_OFF     = 1,
    LED_MODE_BLINK   = 2,
    LED_MODE_BREATHE = 3,
    LED_MODE_CUSTOM  = 4,
    LED_MODE_GRADIENT_ANIM = 5,
} led_mode_t;

typedef struct {
    uint8_t version;     /* 1 */
    uint8_t mode;        /* led_mode_t */
    uint8_t r, g, b;
    uint8_t brightness;  /* 0..255 */
    uint8_t custom_colors[LED_STRIP_LENGTH][3]; /* RGB for each LED */
    uint8_t start_r, start_g, start_b;
    uint8_t end_r, end_g, end_b;
    uint8_t anim_speed; /* seconds */
} led_profile_t;

/* ===== Globals ===== */
#if CONFIG_BT_NIMBLE_ENABLED
static uint16_t g_conn_handle = 0;
static volatile bool g_ble_connected = false;
static volatile bool g_usb_connected = false;
static uint32_t g_last_usb_ms = 0;
/* System startup timestamp (ms) */
static volatile uint32_t g_system_startup_ms = 0;
/* Timestamp (ms) when a connection (BLE or USB) was established; used for post-connection grace */
static volatile uint32_t g_conn_start_ms = 0;
/* Timestamps (ms) of the moment BLE/USB first connected — used to show "ПОДКЛЮЧАЮ" animation */
static volatile uint32_t g_ble_conn_since_ms = 0;
static volatile uint32_t g_usb_conn_since_ms = 0;
static uint16_t g_temp_val_handle = 0;
static uint16_t g_fan_cfg_val_handle = 0;
static uint16_t g_pump_cfg_val_handle = 0;
static uint16_t g_rpm_val_handle = 0; /* RPM notify/read */
static uint16_t g_water_val_handle = 0; /* WATER notify/read */
static uint16_t g_loop_stat_val_handle = 0; /* LOOP status read/notify */
#endif

static volatile int32_t g_cpu_temp_c = -1000;
static volatile int32_t g_gpu_temp_c = -1000;
static volatile uint32_t g_last_temp_ms = 0;
/* Water temperature (DS18B20) */
static volatile int32_t g_water_temp_c = -1000;
static volatile uint32_t g_last_water_ms = 0;
static volatile bool g_err_ble_hw    = false;  /* err 2: BLE hardware/stack init failed */
static volatile bool g_err_uart_hw   = false;  /* err 3: UART/USB hardware init failed */

static curve_cfg_t g_fan;
static curve_cfg_t g_pump;

static float g_fan_last_filt  = NAN;
static float g_fan_last_appl  = NAN;
static float g_pump_last_filt = NAN;
static float g_pump_last_appl = NAN;

/* LED */
static led_strip_handle_t g_led_strip = NULL;
static led_profile_t g_led_prof;
static TaskHandle_t g_led_task = NULL;
static volatile bool g_led_dirty = false;
static volatile bool g_led_need_reinit = false; /* request safe reinit of RMT device */
static volatile uint8_t g_led_refresh_errs = 0;
static volatile uint8_t g_led_invalid_state_cnt = 0; /* consecutive INVALID_STATE errors */
/* When true, keep LEDs on based on saved profile even without active PC connection */
static volatile bool g_led_allow_disconnected = false;
/* Synchronization for LED operations */
static SemaphoreHandle_t g_led_mtx = NULL;

/* RPM calibration scales (mutable, persisted in NVS) */
/* Калибровка вентиляторов по данным пользователя:
    100% PWM: raw1=3400 -> 1800, raw2=4800 -> 1800 => scale1=0.5294, scale2=0.3750 */
static float g_rpm_scale1 = 1800.0f/3400.0f; /* ≈0.5294 */
static float g_rpm_scale2 = 1800.0f/4800.0f; /* 0.3750 */
static bool  g_rpm_scale_has1 = false;
static bool  g_rpm_scale_has2 = false;

/* Tachometer */
static volatile uint32_t g_tach1_edges = 0;
static volatile uint32_t g_tach2_edges = 0;
/* Храним уже КАЛИБРОВАННЫЕ RPM (после scale и clamp) */
static int32_t g_rpm1 = 0, g_rpm2 = 0;
#define CAL_FLAG_ACTIVE 0x80000000u /* internal */
static uint32_t g_rpm_flags = 0; /* bit0: fan1 fault, bit1: fan2 fault, bit2: purge */
#define RPM_FLAG_F1 0x01
static volatile bool g_calibrating = false;
#define RPM_FLAG_F2 0x02
#define RPM_FLAG_PURGE 0x04
/* Purge (air flush) control */
static volatile bool g_purge_active = false;
static volatile bool g_purge_cancel = false;
static TaskHandle_t g_purge_task = NULL;
/* Valve/pump ramp (short fill) indicator shown on OLED as "НАПОЛНЯЮ" */
/* ramp indicator removed; use g_pump_boost_active for post-purge filling display */
/* Remember that a purge sequence has completed; used to arm the next-start boost only after STOP */
static volatile bool g_purge_completed_since_last_stop = false;
/* Remember that a purge command was seen since last stop (covers manual cancel cases) */
static volatile bool g_purge_seen_since_last_stop = false;
/* Простейшая анти-дребезг фильтрация: игнорируем импульсы, идущие чаще заданного интервала */
#define TACH_MIN_EDGE_US    5000  /* импульсы чаще 5 мс считаем помехой (~макс ≈6000 RPM при 2 имп./об), реальный 1800 RPM ~16.7 мс */
static volatile uint32_t g_tach1_last_us = 0;
static volatile uint32_t g_tach2_last_us = 0;

/* System run/stop control */
static volatile bool g_system_running = true; /* true = normal control; false = force stop (fans/pump off) */
static volatile bool g_start_pending = false; /* one-shot: set by ST, consumed by control_task to check NVS boost */
static volatile bool g_stop_pending  = false; /* one-shot: set by SP/break, consumed by control_task to kill HW */
static volatile bool g_waiting_for_temps = false; /* explicit flag from app: waiting for target temps before spinning */

/* Pump boost state (only after purge->stop -> next start) */
static volatile bool g_pump_boost_armed = false;    /* armed by purge followed by stop */
static volatile bool g_pump_boost_active = false;   /* currently running boost sequence */
static volatile uint32_t g_pump_boost_start_ms = 0; /* timestamp of boost start */
static float g_pump_boost_target = 0.0f;            /* frozen target percent from curve at boost start */

/* NVS namespaces */
#define NVS_NS_FAN   "fan"
#define NVS_KEY_FAN  "cfg_v1"
#define NVS_NS_PUMP  "pump"
#define NVS_KEY_PUMP "cfg_v1"
#define NVS_NS_LED   "led"
#define NVS_KEY_LED  "prof_v1"

/* Persisted boost pending flag (set after purge completion to survive power loss) */
#define NVS_NS_SYS   "sys"
#define NVS_KEY_BOOST "boost_pending"

/* Helpers to set/take persisted boost flag */
static void boost_flag_set_pending(bool v){
    nvs_handle_t h; if (nvs_open(NVS_NS_SYS, NVS_READWRITE, &h) == ESP_OK){
        (void)nvs_set_u8(h, NVS_KEY_BOOST, v ? 1 : 0);
        (void)nvs_commit(h); nvs_close(h);
    }
}
/* Atomically read and clear pending flag; returns true if it was set */
static bool boost_flag_take_pending(void){
    uint8_t val = 0; bool was = false; nvs_handle_t h;
    if (nvs_open(NVS_NS_SYS, NVS_READWRITE, &h) == ESP_OK){
        if (nvs_get_u8(h, NVS_KEY_BOOST, &val) == ESP_OK && val != 0){
            was = true; (void)nvs_set_u8(h, NVS_KEY_BOOST, 0); (void)nvs_commit(h);
        }
        nvs_close(h);
    }
    return was;
}

/* Pump hours storage */
#define NVS_NS_HOURS "hours"
#define NVS_KEY_HOURS "v1"
/* Calibration namespace */
#define NVS_NS_CAL   "cal"
#define NVS_KEY_RPM1 "rpm1_scale"
#define NVS_KEY_RPM2 "rpm2_scale"
/* OLED brightness persistence */
#define NVS_NS_OLED  "oled"
#define NVS_KEY_OLED_BR "bright"
#define NVS_KEY_OLED_LANG "lang"    /* Display language: 0=RU, 1=EN */

/* ===== Forward decls ===== */
static void fan_pwm_init(void);
static void fan_pwm_set_percent(float pct);
static void pump_pwm_set_percent(float pct);

static void control_task(void *arg);
static void led_task(void *arg);
static void oled_task(void *arg);
static void uart_rx_task(void *arg);
static void uart_init(void);
static void ensure_ledc_init_once(void);

static void tach_init(void);
static void tach_sample_and_publish(uint32_t interval_ms);

static void uart_send_rp(int32_t rpm1, int32_t rpm2, uint32_t flags); /* UART RP TX */
static void uart_send_wt(int32_t water_c);
static void loopprot_task(void *arg);
static int sp_try_lp(const uint8_t* d,size_t l,size_t* used);

/* DS18B20 */
static void ds18b20_task(void *arg);
static bool ds18b20_read_celsius(int32_t *out_c);
static bool onewire_reset(void);
static void onewire_write_byte(uint8_t v);
static uint8_t onewire_read_byte(void);

/* RPM scale persistence and calibration */
static void rpm_scale_load(void);
static void rpm_scale_save(void);
static void rpm_autocalibrate(void);

/* Forced-stop guard window to suppress any PWM glitches after STOP/port close */
static volatile uint32_t g_forced_stop_deadline_ms = 0;
static bool g_pwm_fan_attached = false;
static bool g_pwm_pump_attached = false;
static bool g_pwm_valve_attached = false;

/* ===== Loop protection (hose presence) ===== */
static volatile bool g_loopprot_enabled = false;   /* configurable flag (persisted) */
static volatile bool g_loop_ok = true;             /* current physical continuity state */
static volatile bool g_was_running_before_loop_break = false; /* was system in РАБОТА when loop broke? */
static volatile uint8_t g_loop_mismatch_ctr = 0;   /* debounce counters */
static volatile uint8_t g_loop_match_ctr = 0;
static volatile bool g_loop_last_drive = false;    /* last driven level on LOOP_OUT */
static volatile uint32_t g_lp_restore_ms = 0;      /* tick when loop restored (0=not set); drives OLED countdown */
#define LP_REARM_SECS 5                             /* countdown seconds after loop restoration */

/* ===== OLED (SSD1312) driver ===== */
/* SSD1312 controller: 128 segments × 64 COM.
 * Display is mounted vertically (portrait): 64px wide, 128px tall.
 * Framebuffer uses portrait coordinates; oled_flush rotates 90° to match controller. */
#define OLED_SDA_GPIO      21
#define OLED_SCL_GPIO      22
#define OLED_ADDR          0x3C
/* Portrait dimensions (what we draw in) */
#define OLED_WIDTH         64
#define OLED_HEIGHT        128
#define OLED_PAGES         (OLED_HEIGHT/8)  /* 16 pages in our framebuffer */
/* Controller dimensions */
#define OLED_HW_COLS       128
#define OLED_HW_PAGES      8
/* Optional hardware reset pin (tie your OLED RST to this GPIO). Set to -1 to disable. */
#define OLED_RST_GPIO      -1
/* Runtime-adjustable params for diagnostics */
static uint8_t g_oled_seg_remap = 1; /* 1 -> 0xA1 (remapped) */
static uint8_t g_oled_com_scan = 0; /* 0 -> 0xC0 (normal scan) */
static uint8_t g_oled_display_offset = 0; /* 0..127 via 0xD3 */
/* OLED display brightness (0=off .. 255=max), persisted in NVS */
static volatile uint8_t g_oled_brightness = 0xCF; /* default contrast */
/* Display language: 0=RU (Cyrillic), 1=EN (English), persisted in NVS */
static volatile uint8_t g_display_lang = 0;

static uint8_t g_oled_fb[OLED_WIDTH * OLED_PAGES]; /* page-major: page*WIDTH + x */
static bool g_oled_inited = false;
#ifdef HAVE_NEW_I2C
static i2c_master_bus_handle_t g_i2c_bus = NULL;
static i2c_master_dev_handle_t g_oled_devs[6] = {0};
static uint8_t g_oled_dev_count = 0;
#endif

static esp_err_t oled_i2c_init(void){
#ifdef HAVE_NEW_I2C
    /* ---- I2C bus recovery (bit-bang SCL to release stuck SDA) ----
     * After a WDT/crash the OLED controller may still be holding SDA LOW
     * in the middle of an unfinished byte.  Toggling SCL 9+ times lets the
     * slave finish its current bit and release SDA so we can issue STOP. */
    {
        gpio_config_t scl_cfg = {
            .pin_bit_mask = (1ULL << OLED_SCL_GPIO),
            .mode         = GPIO_MODE_OUTPUT_OD,
            .pull_up_en   = GPIO_PULLUP_ENABLE,
            .pull_down_en = GPIO_PULLDOWN_DISABLE,
            .intr_type    = GPIO_INTR_DISABLE,
        };
        gpio_config_t sda_cfg = {
            .pin_bit_mask = (1ULL << OLED_SDA_GPIO),
            .mode         = GPIO_MODE_INPUT_OUTPUT_OD,
            .pull_up_en   = GPIO_PULLUP_ENABLE,
            .pull_down_en = GPIO_PULLDOWN_DISABLE,
            .intr_type    = GPIO_INTR_DISABLE,
        };
        gpio_config(&scl_cfg);
        gpio_config(&sda_cfg);
        gpio_set_level((gpio_num_t)OLED_SCL_GPIO, 1);
        gpio_set_level((gpio_num_t)OLED_SDA_GPIO, 1);
        esp_rom_delay_us(5);
        /* Clock out up to 9 bits to let slave finish any pending byte */
        for (int i = 0; i < 9; i++) {
            gpio_set_level((gpio_num_t)OLED_SCL_GPIO, 0);
            esp_rom_delay_us(5);
            gpio_set_level((gpio_num_t)OLED_SCL_GPIO, 1);
            esp_rom_delay_us(5);
            if (gpio_get_level((gpio_num_t)OLED_SDA_GPIO)) break;  /* SDA released */
        }
        /* Generate STOP: SDA LOW→HIGH while SCL HIGH */
        gpio_set_level((gpio_num_t)OLED_SDA_GPIO, 0);
        esp_rom_delay_us(5);
        gpio_set_level((gpio_num_t)OLED_SCL_GPIO, 1);
        esp_rom_delay_us(5);
        gpio_set_level((gpio_num_t)OLED_SDA_GPIO, 1);
        esp_rom_delay_us(5);
        /* Release GPIOs so I2C driver can reclaim them */
        gpio_reset_pin((gpio_num_t)OLED_SCL_GPIO);
        gpio_reset_pin((gpio_num_t)OLED_SDA_GPIO);
    }

    i2c_master_bus_config_t bus_cfg = {
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .i2c_port = I2C_NUM_0,
        .sda_io_num = OLED_SDA_GPIO,
        .scl_io_num = OLED_SCL_GPIO,
        .glitch_ignore_cnt = 7,
        .flags = { .enable_internal_pullup = false },  /* external pull-ups required on SDA/SCL */
    };
    esp_err_t bus_err = i2c_new_master_bus(&bus_cfg, &g_i2c_bus);
    if (bus_err != ESP_OK) {
        ESP_LOGE(TAG, "OLED: i2c_new_master_bus FAILED: %s", esp_err_to_name(bus_err));
        return bus_err;
    }
    ESP_LOGI(TAG, "OLED: I2C bus created OK (SDA=%d SCL=%d)", OLED_SDA_GPIO, OLED_SCL_GPIO);

    /* Probe only the known OLED address (0x3C) with retry after bus reset */
    g_oled_dev_count = 0;
    const uint8_t oled_addr = 0x3C;
    esp_err_t probe_err = ESP_FAIL;
    for (int attempt = 0; attempt < 3; attempt++) {
        if (attempt > 0) {
            ESP_LOGW(TAG, "OLED: probe retry %d/3 after bus reset", attempt + 1);
            (void)i2c_master_bus_reset(g_i2c_bus);
            vTaskDelay(pdMS_TO_TICKS(50));
        }
        probe_err = i2c_master_probe(g_i2c_bus, oled_addr, pdMS_TO_TICKS(200));
        if (probe_err == ESP_OK) break;
    }
    if (probe_err != ESP_OK){
        ESP_LOGE(TAG, "OLED: no ACK from 0x%02X after 3 attempts (%s)", (unsigned)oled_addr, esp_err_to_name(probe_err));
        return ESP_FAIL;
    }
    ESP_LOGI(TAG, "OLED: I2C device found at 0x%02X", (unsigned)oled_addr);

    i2c_device_config_t dev_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = oled_addr,
        .scl_speed_hz = 400000,  /* SSD1312 supports up to 400 kHz */
    };
    i2c_master_dev_handle_t h = NULL;
    if (i2c_master_bus_add_device(g_i2c_bus, &dev_cfg, &h) != ESP_OK || h == NULL){
        ESP_LOGE(TAG, "OLED: failed to add device 0x%02X", (unsigned)oled_addr);
        return ESP_FAIL;
    }
    g_oled_devs[g_oled_dev_count++] = h;
    ESP_LOGI(TAG, "OLED: device 0x%02X registered (400 kHz)", (unsigned)oled_addr);
    return ESP_OK;
#else
    return ESP_ERR_NOT_SUPPORTED;
#endif
}

static esp_err_t oled_send_cmd_idx(uint8_t idx, uint8_t cmd);

static esp_err_t oled_send_cmd(uint8_t cmd){
#ifdef HAVE_NEW_I2C
    if (g_oled_dev_count == 0) return ESP_FAIL;
    esp_err_t r = ESP_FAIL;
    for (uint8_t i = 0; i < g_oled_dev_count; ++i){
        esp_err_t t = oled_send_cmd_idx(i, cmd);
        if (i == 0) r = t;
    }
    return r;
#else
    return ESP_ERR_NOT_SUPPORTED;
#endif
}

static esp_err_t oled_send_cmd_idx(uint8_t idx, uint8_t cmd){
#ifdef HAVE_NEW_I2C
    if (idx >= g_oled_dev_count) return ESP_ERR_INVALID_ARG;
    uint8_t buf[2] = {0x00, cmd};
    return i2c_master_transmit(g_oled_devs[idx], buf, sizeof(buf), pdMS_TO_TICKS(200));
#else
    return ESP_ERR_NOT_SUPPORTED;
#endif
}

static inline void oled_apply_orientation(void){
    /* SEG remap */
    oled_send_cmd(g_oled_seg_remap ? 0xA1 : 0xA0);
    /* COM scan direction */
    oled_send_cmd(g_oled_com_scan ? 0xC8 : 0xC0);
}

static inline void oled_apply_display_offset(void){
    oled_send_cmd(0xD3);
    oled_send_cmd((uint8_t)(g_oled_display_offset & 0x7F));
}

static esp_err_t oled_send_data(const uint8_t* data, size_t len){
    #define OLED_I2C_CHUNK 128
    esp_err_t r = ESP_OK;
#ifdef HAVE_NEW_I2C
    static uint8_t buf[1+OLED_I2C_CHUNK]; buf[0] = 0x40;  /* static: saves stack */
    for (uint8_t d = 0; d < g_oled_dev_count; ++d){
        for (size_t off=0; off<len && r==ESP_OK; off+=OLED_I2C_CHUNK){
            size_t n = (len-off>OLED_I2C_CHUNK)?OLED_I2C_CHUNK:(len-off);
            memcpy(&buf[1], data+off, n);
            r = i2c_master_transmit(g_oled_devs[d], buf, 1+n, pdMS_TO_TICKS(200));
        }
    }
    return r;
#else
    return ESP_ERR_NOT_SUPPORTED;
#endif
}

static void oled_flush(void);

static void __attribute__((unused)) oled_init(void){
    if (g_oled_inited) return;
    if (oled_i2c_init()!=ESP_OK){ ESP_LOGE(TAG, "OLED: I2C init failed"); return; }
    vTaskDelay(pdMS_TO_TICKS(50));
    ESP_LOGI(TAG, "OLED: init start (WxH=%dx%d)", OLED_WIDTH, OLED_HEIGHT);
    /* Hardware reset if wired */
#if (OLED_RST_GPIO >= 0)
    gpio_config_t rst = { .pin_bit_mask = (1ULL<<OLED_RST_GPIO), .mode=GPIO_MODE_OUTPUT, .pull_up_en=GPIO_PULLUP_DISABLE, .pull_down_en=GPIO_PULLDOWN_DISABLE, .intr_type=GPIO_INTR_DISABLE };
    gpio_config(&rst);
    gpio_set_level(OLED_RST_GPIO, 0); vTaskDelay(pdMS_TO_TICKS(5));
    gpio_set_level(OLED_RST_GPIO, 1); vTaskDelay(pdMS_TO_TICKS(10));
    ESP_LOGI(TAG, "OLED: HW reset via GPIO %d", OLED_RST_GPIO);
#else
    /* Soft reset (if supported) */
    oled_send_cmd(0xE2);
    vTaskDelay(pdMS_TO_TICKS(10));
#endif
    /* SSD1312 128×64 init sequence */
    oled_send_cmd(0xAE); // display off
    oled_send_cmd(0xD5); oled_send_cmd(0x80); // clock divide ratio & osc freq
    oled_send_cmd(0xA8); oled_send_cmd(0x3F); // multiplex ratio = 63 (64 COM lines)
    oled_send_cmd(0xD3); oled_send_cmd(0x00); // display offset = 0
    oled_send_cmd(0x40); // display start line = 0
    oled_send_cmd(0x8D); oled_send_cmd(0x14); // charge pump enable
    oled_send_cmd(0xAD); oled_send_cmd(0x8B); // SSD1312 DC-DC on
    oled_send_cmd(0x20); oled_send_cmd(0x02); // page addressing mode
    /* Orientation (runtime) */
    oled_apply_orientation();
    oled_send_cmd(0x00); // low column start = 0
    oled_send_cmd(0x10); // high column start = 0
    oled_send_cmd(0xDA); oled_send_cmd(0x12); // COM pins: alternative, no remap
    /* Load persisted OLED brightness from NVS */
    {
        nvs_handle_t h; uint8_t br_val = 0xFF;
        if (nvs_open(NVS_NS_OLED, NVS_READONLY, &h) == ESP_OK){
            if (nvs_get_u8(h, NVS_KEY_OLED_BR, &br_val) == ESP_OK){
                g_oled_brightness = br_val;
                ESP_LOGI(TAG, "OLED: loaded brightness=%u from NVS", (unsigned)br_val);
            }
            uint8_t lang_val = 0;
            if (nvs_get_u8(h, NVS_KEY_OLED_LANG, &lang_val) == ESP_OK){
                g_display_lang = lang_val;
                ESP_LOGI(TAG, "OLED: loaded lang=%u from NVS", (unsigned)lang_val);
            }
            nvs_close(h);
        }
    }
    oled_send_cmd(0x81); oled_send_cmd(g_oled_brightness); // contrast
    oled_send_cmd(0xD9); oled_send_cmd(0xF1); // pre-charge period
    oled_send_cmd(0xDB); oled_send_cmd(0x40); // VCOMH deselect level
    oled_send_cmd(0xA4); // display from RAM
    oled_send_cmd(0xA6); // normal (not inverted)
    oled_send_cmd(0x2E); // deactivate scroll
    oled_send_cmd(0xAF); // display on
    memset(g_oled_fb, 0x00, sizeof(g_oled_fb));
    g_oled_inited = true;
    /* If brightness was persisted as 0, turn display off immediately */
    if (g_oled_brightness == 0) {
        oled_send_cmd(0xAE); /* display off */
    }
    ESP_LOGI(TAG, "OLED: init done (brightness=%u)", (unsigned)g_oled_brightness);
}

static inline void oled_fb_clear(void){ memset(g_oled_fb, 0x00, sizeof(g_oled_fb)); }
static inline void oled_fb_set_pixel(int x, int y, bool on){
    if (x<0||x>=OLED_WIDTH||y<0||y>=OLED_HEIGHT) return;
    int page = y >> 3; int bit = y & 7; size_t idx = (size_t)page * OLED_WIDTH + (size_t)x;
    if (on) g_oled_fb[idx] |= (uint8_t)(1u<<bit); else g_oled_fb[idx] &= (uint8_t)~(1u<<bit);
}

static inline void oled_fb_fill_rect(int x, int y, int w, int h, bool on){
    if (w <= 0 || h <= 0) return;
    for (int yy = y; yy < y + h; ++yy){
        for (int xx = x; xx < x + w; ++xx){
            oled_fb_set_pixel(xx, yy, on);
        }
    }
}

static inline uint8_t bitrev8(uint8_t v){
    v = (uint8_t)(((v & 0xF0u) >> 4) | ((v & 0x0Fu) << 4));
    v = (uint8_t)(((v & 0xCCu) >> 2) | ((v & 0x33u) << 2));
    v = (uint8_t)(((v & 0xAAu) >> 1) | ((v & 0x55u) << 1));
    return v;
}

/* Minimal 5x7 font (ASCII + Cyrillic subset). Each glyph is 5 columns x 7 rows,
 * column-major, bit 0 = top row. Field cp holds a Unicode codepoint (uint16_t). */
typedef struct { uint16_t cp; uint8_t col[5]; } glyph5x7_t;
static const glyph5x7_t k_font5x7[] = {
    {' ', {0x00,0x00,0x00,0x00,0x00}},
    {'-', {0x00,0x08,0x08,0x08,0x00}},
    {'0', {0x3E,0x51,0x49,0x45,0x3E}},
    {'1', {0x00,0x42,0x7F,0x40,0x00}},
    {'2', {0x42,0x61,0x51,0x49,0x46}},
    {'3', {0x21,0x41,0x45,0x4B,0x31}},
    {'4', {0x18,0x14,0x12,0x7F,0x10}},
    {'5', {0x27,0x45,0x45,0x45,0x39}},
    {'6', {0x3C,0x4A,0x49,0x49,0x30}},
    {'7', {0x01,0x71,0x09,0x05,0x03}},
    {'8', {0x36,0x49,0x49,0x49,0x36}},
    {'9', {0x06,0x49,0x49,0x29,0x1E}},
    {'A', {0x7E,0x11,0x11,0x11,0x7E}},
    {'B', {0x7F,0x49,0x49,0x49,0x36}},
    {'C', {0x3E,0x41,0x41,0x41,0x22}},
    {'D', {0x7F,0x41,0x41,0x22,0x1C}},
    {'E', {0x7F,0x49,0x49,0x49,0x41}},
    {'F', {0x7F,0x09,0x09,0x09,0x01}},
    {'G', {0x3E,0x41,0x49,0x49,0x7A}},
    {'H', {0x7F,0x08,0x08,0x08,0x7F}},
    {'I', {0x00,0x41,0x7F,0x41,0x00}},
    {'L', {0x7F,0x40,0x40,0x40,0x40}},
    {'M', {0x7F,0x02,0x0C,0x02,0x7F}},
    {'N', {0x7F,0x04,0x08,0x10,0x7F}},
    {'O', {0x3E,0x41,0x41,0x41,0x3E}},
    {'P', {0x7F,0x09,0x09,0x09,0x06}},
    {'R', {0x7F,0x09,0x19,0x29,0x46}},
    {'S', {0x26,0x49,0x49,0x49,0x32}},
    {'T', {0x01,0x01,0x7F,0x01,0x01}},
    {'U', {0x3F,0x40,0x40,0x40,0x3F}},
    {'V', {0x07,0x18,0x60,0x18,0x07}},
    {'W', {0x3F,0x40,0x38,0x40,0x3F}},
    {'Y', {0x07,0x08,0x70,0x08,0x07}},
    {'a', {0x20,0x54,0x54,0x54,0x78}},
    {'d', {0x38,0x44,0x44,0x48,0x7F}},
    {'e', {0x38,0x54,0x54,0x54,0x18}},
    {'g', {0x08,0x54,0x54,0x54,0x3C}},
    {'i', {0x00,0x44,0x7D,0x40,0x00}},
    {'l', {0x00,0x41,0x7F,0x40,0x00}},
    {'n', {0x7C,0x04,0x04,0x04,0x78}},
    {'o', {0x38,0x44,0x44,0x44,0x38}},
    {'r', {0x7C,0x08,0x04,0x04,0x08}},
    {'y', {0x0C,0x50,0x50,0x50,0x3C}},
    {':', {0x00,0x36,0x36,0x00,0x00}},
    {'.', {0x00,0x60,0x60,0x00,0x00}},
    {'%', {0x62,0x64,0x08,0x13,0x23}},
    {'!', {0x00,0x00,0x5F,0x00,0x00}},  /* exclamation mark */
    /* ---- Cyrillic uppercase ---- */
    {0x0410, {0x7E,0x11,0x11,0x11,0x7E}},  /* А (=A) */
    {0x0411, {0x7F,0x45,0x45,0x45,0x38}},  /* Б — full 7px height: top bar + left vert + mid bar + bump */
    {0x0412, {0x7F,0x49,0x49,0x49,0x36}},  /* В (=B) */
    {0x0413, {0x3F,0x01,0x01,0x01,0x01}},  /* Г */
    {0x0414, {0x61,0x3F,0x21,0x3F,0x61}},  /* Д — top bar + legs */
    {0x0415, {0x7F,0x49,0x49,0x49,0x41}},  /* Е — left vert + top/mid/bottom bars */
    {0x0416, {0x63,0x14,0x7F,0x14,0x63}},  /* Ж — center vert full, K-wings R2+R4, outer legs R0-1+R5-6 */
    {0x0417, {0x00,0x49,0x49,0x49,0x7F}},  /* З */
    {0x0418, {0x7F,0x10,0x08,0x04,0x7F}},  /* И — reversed-N diagonal */
    {0x041A, {0x7F,0x08,0x14,0x22,0x41}},  /* К */
    {0x041B, {0x78,0x04,0x02,0x01,0x7F}},  /* Л — diagonal left leg + right vertical */
    {0x041D, {0x7F,0x08,0x08,0x08,0x7F}},  /* Н */
    {0x041E, {0x3E,0x41,0x41,0x41,0x3E}},  /* О — full 7px height */
    {0x041F, {0x7F,0x01,0x01,0x01,0x7F}},  /* П — full-height verticals R0-R6 */
    {0x0420, {0x7F,0x09,0x09,0x09,0x06}},  /* Р (=P) */
    {0x0421, {0x3E,0x41,0x41,0x41,0x22}},  /* С */
    {0x0422, {0x01,0x01,0x7F,0x01,0x01}},  /* Т — full-height stem R0-R6 */
    {0x0423, {0x43,0x4C,0x30,0x0C,0x03}},  /* У */
    {0x0426, {0x7F,0x40,0x40,0x40,0xFF}},  /* Ц — full verticals R0-R6, bar at R6, tail at R7 (8-row exception) */
    {0x0427, {0x0F,0x08,0x08,0x7F,0x00}},  /* Ч — left arm 1-col rows 0-3, bar at row 3, right vertical */
    {0x0428, {0x7F,0x40,0x7F,0x40,0x7F}},  /* Ш */
    {0x0429, {0x3F,0x20,0x3F,0x20,0x7F}},  /* Щ */
    {0x042F, {0x66,0x19,0x09,0x09,0x7F}},  /* Я — правая вертикаль 0-6, чаша вверх-влево, ножка влево */
    /* ---- Cyrillic lowercase ---- */
    {0x0430, {0x20,0x54,0x54,0x54,0x78}},  /* а (=a) */
    {0x0431, {0x00,0x3F,0x25,0x25,0x18}},  /* б */
    {0x0432, {0x00,0x7E,0x4A,0x4A,0x30}},  /* в */
    {0x0433, {0x7C,0x04,0x04,0x04,0x00}},  /* г */
    {0x0437, {0x00,0x11,0x15,0x15,0x0A}},  /* з */
    {0x0438, {0x3E,0x10,0x08,0x04,0x3E}},  /* и — reversed-N diagonal */
    {0x043A, {0x7C,0x10,0x10,0x28,0x44}},  /* к */
    {0x043E, {0x38,0x44,0x44,0x44,0x38}},  /* о (=o) */
    {0x0440, {0x00,0x7E,0x12,0x12,0x0C}},  /* р */
    {0x0442, {0x04,0x04,0x3C,0x04,0x04}},  /* т */
    {0x0443, {0x0C,0x50,0x50,0x50,0x3C}},  /* у (=y) */
    {0x0448, {0x3E,0x20,0x3E,0x20,0x3E}},  /* ш */
};

/* Wide glyphs: variable columns (6–8) × 8 rows for letters needing extra width. */
typedef struct { uint16_t cp; uint8_t ncols; uint8_t col[8]; } glyph_wide_t;
static const glyph_wide_t k_font_wide[] = {
    {0x041C, 6, {0x7F,0x02,0x04,0x04,0x02,0x7F}},        /* М — 6 cols */
    {0x042B, 7, {0x7F,0x44,0x44,0x44,0x38,0x00,0x7F}},    /* Ы — 7 cols: Ь + gap + I */
    {0x042E, 7, {0x7F,0x08,0x08,0x3E,0x41,0x41,0x3E}},    /* Ю — 7 cols: bar + 2-col connector + 4-col O */
};
/* Lookup wide glyph; returns col data pointer and sets *out_ncols. */
static const uint8_t* font_wide_get(int cp, int* out_ncols){
    size_t n = sizeof(k_font_wide)/sizeof(k_font_wide[0]);
    for (size_t i=0;i<n;++i){
        if ((int)k_font_wide[i].cp==cp){
            if (out_ncols) *out_ncols = k_font_wide[i].ncols;
            return k_font_wide[i].col;
        }
    }
    return NULL;
}
/* Returns number of rendered columns for a codepoint */
static inline int font_ncols(int cp){ int nc; return font_wide_get(cp,&nc) ? nc : 5; }

static const uint8_t* font5x7_get(int cp){
    size_t n = sizeof(k_font5x7)/sizeof(k_font5x7[0]);
    for (size_t i=0;i<n;++i){ if ((int)k_font5x7[i].cp == cp) return k_font5x7[i].col; }
    return k_font5x7[0].col; /* space */
}

/* Decode one UTF-8 codepoint from *s, advance *s past it. Returns 0 at end. */
static uint16_t utf8_next_cp(const char** s){
    const unsigned char* p = (const unsigned char*)*s;
    if (!*p) return 0;
    uint16_t cp;
    if (*p < 0x80) {
        cp = *p++;
    } else if ((*p & 0xE0) == 0xC0 && p[1]) {
        cp = (uint16_t)(((unsigned)*p & 0x1Fu) << 6u) | ((unsigned)p[1] & 0x3Fu);
        p += 2;
    } else {
        cp = (uint16_t)'?';
        p++;
        while (*p && (*p & 0xC0u) == 0x80u) p++;
    }
    *s = (const char*)p;
    return cp;
}

/* Count display characters (codepoints) in a UTF-8 string */
static int utf8_charlen(const char* s){
    int n = 0;
    const char* p = s;
    while (utf8_next_cp(&p)) n++;
    return n;
}

static void oled_draw_char(int x, int y, int cp){
    int ncols = 5;
    const uint8_t* g = font_wide_get(cp, &ncols);
    if (!g) g = font5x7_get(cp);
    for (int dx=0; dx<ncols; ++dx){
        uint8_t col = g[dx];
        for (int dy=0; dy<8; ++dy){
            if ((col >> dy) & 1u)
                oled_fb_set_pixel(x+dx, y+dy, true);
        }
    }
}

static void oled_draw_text(int x, int y, const char* s){
    const char* p = s;
    int xi = x;
    uint16_t cp;
    while ((cp = utf8_next_cp(&p)) != 0){
        oled_draw_char(xi, y, (int)cp);
        xi += font_ncols((int)cp) + 1;  /* glyph width + 1px gap */
    }
}

/* Returns pixel width of a UTF-8 string using the current font (variable-width aware) */
static int text_px_width(const char* s){
    const char* p = s; int w = 0; uint16_t cp;
    while ((cp = utf8_next_cp(&p)) != 0)
        w += font_ncols((int)cp) + 1;
    return w;
}

static void oled_flush(void){
    /* Rotate portrait framebuffer (64w×128h) → SSD1312 hardware (128 cols × 8 pages).
     * Portrait pixel (px, py) → controller col=py, row=(63-px).
     * Controller page = row/8, bit = row%8. */
    uint8_t tx[OLED_HW_COLS];
    for (int hp = 0; hp < OLED_HW_PAGES; ++hp){
        oled_send_cmd((uint8_t)(0xB0 | hp));      /* set page */
        oled_send_cmd(0x00);                       /* lower col = 0 */
        oled_send_cmd(0x10);                       /* upper col = 0 */
        for (int c = 0; c < OLED_HW_COLS; ++c){
            uint8_t byte = 0;
            for (int b = 0; b < 8; ++b){
                /* controller row = hp*8 + b → portrait px = 63 - (hp*8+b) */
                int px = 63 - (hp * 8 + b);
                int py = c;  /* controller col = portrait y */
                if (px >= 0 && px < OLED_WIDTH && py >= 0 && py < OLED_HEIGHT){
                    int fb_page = py >> 3;
                    int fb_bit  = py & 7;
                    if (g_oled_fb[fb_page * OLED_WIDTH + px] & (1u << fb_bit))
                        byte |= (uint8_t)(1u << b);
                }
            }
            tx[c] = byte;
        }
        (void)oled_send_data(tx, OLED_HW_COLS);
    }
}

#if CONFIG_BT_NIMBLE_ENABLED
static void start_advertising(void);
static void on_reset(int reason);
static void on_sync(void);
static void host_task(void *);
static esp_err_t ble_stack_init_manual(void);
static void water_notify_ble(void);
#endif

/* ===== Utils ===== */
static inline float clampf(float x, float a, float b){ if(x<a) return a; if(x>b) return b; return x; }
static inline uint8_t clampu8(int v){ if(v<0) return 0; if(v>255) return 255; return (uint8_t)v; }

static float fan_apply_min_floor(float s){
    if (s > 0.0f && s < FAN_MIN_ON_PCT) return FAN_MIN_ON_PCT;
    return s;
}
static float pump_apply_min_floor(float s){
    if (s > 0.0f && s < PUMP_MIN_ON_PCT) return PUMP_MIN_ON_PCT;
    return s;
}

static void sort_points_by_temp(curve_point_t *pts, uint8_t n){
    for (int i=1;i<n;++i){ curve_point_t key=pts[i]; int j=i-1; while(j>=0 && pts[j].t>key.t){ pts[j+1]=pts[j]; --j; } pts[j+1]=key; }
}

static float catmull_rom(float p0,float p1,float p2,float p3,float u){
    float u2=u*u, u3=u2*u;
    return 0.5f*(2.0f*p1 + (-p0+p2)*u + (2.0f*p0-5.0f*p1+4.0f*p2-p3)*u2 + (-p0+3.0f*p1-3.0f*p2+p3)*u3);
}

static float eval_curve(const curve_cfg_t *cfg, float tC, bool for_fan){
    if (cfg->count==0) return 0.0f;
    const curve_point_t *p0=&cfg->pts[0], *plast=&cfg->pts[cfg->count-1];
#ifdef OFF_BELOW_FIRST_PT
    if (p0->t > TEMP_MIN_C && tC < p0->t) return 0.0f;
#endif
    if (tC<=p0->t){ float s=clampf(p0->s,0,100); return for_fan?fan_apply_min_floor(s):s; }
    if (tC>=plast->t){ float s=clampf(plast->s,0,100); return for_fan?fan_apply_min_floor(s):s; }
    int i=0; for(int k=0;k<cfg->count-1;++k){ if(cfg->pts[k].t<=tC && tC<=cfg->pts[k+1].t){ i=k; break; } }
    const curve_point_t *p1=&cfg->pts[i], *p2=&cfg->pts[i+1];
    float u=(tC-p1->t)/fmaxf(1e-6f,(p2->t-p1->t));
    float s;
    if (cfg->interp_mode==IM_LINEAR || cfg->count<3){
        s=p1->s + (p2->s - p1->s)*u;
    } else {
        const curve_point_t *pm0=(i-1>=0)?&cfg->pts[i-1]:p1;
        const curve_point_t *pm3=(i+2<cfg->count)?&cfg->pts[i+2]:p2;
        s=catmull_rom(pm0->s,p1->s,p2->s,pm3->s,u);
    }
    s=clampf(s,0,100);
    return for_fan ? fan_apply_min_floor(s) : pump_apply_min_floor(s);
}

static float lp_update(float prev, float target, float tau_sec, float dt_sec){
    if (isnan(prev)) return target;
    float alpha = dt_sec/(tau_sec+dt_sec);
    return prev + alpha*(target - prev);
}

/* ===== FAN NVS ===== */
static void fan_set_defaults(curve_cfg_t* c){
    memset(c,0,sizeof(*c));
    c->version=1; c->source_mode=DEF_SOURCE_MODE; c->interp_mode=DEF_INTERP_MODE;
    c->rc_tau_sec=DEF_RC_TAU_SEC; c->hyst_pct=DEF_HYST_PCT; c->count=4;
    c->pts[0]=(curve_point_t){30.0f,50.0f};
    c->pts[1]=(curve_point_t){50.0f,50.0f};
    c->pts[2]=(curve_point_t){70.0f,100.0f};
    c->pts[3]=(curve_point_t){110.0f,100.0f};
}

static esp_err_t fan_load_from_nvs(void){
    size_t len=sizeof(g_fan);
    nvs_handle_t h; esp_err_t err=nvs_open(NVS_NS_FAN,NVS_READONLY,&h); if(err!=ESP_OK) return err;
    err=nvs_get_blob(h,NVS_KEY_FAN,&g_fan,&len); nvs_close(h);
    if (err==ESP_OK && len==sizeof(g_fan) && g_fan.version==1 && g_fan.count>=2 && g_fan.count<=CURVE_POINTS_MAX){
        sort_points_by_temp(g_fan.pts,g_fan.count);
        if (g_fan.hyst_pct < 3.0f) g_fan.hyst_pct = 3.0f; else if (g_fan.hyst_pct > 10.0f) g_fan.hyst_pct = 10.0f;
        ESP_LOGI(TAG,"FAN: %u pts, src=%u, mode=%u, tau=%.2f, hyst=%.2f", g_fan.count,g_fan.source_mode,g_fan.interp_mode,g_fan.rc_tau_sec,g_fan.hyst_pct);
        return ESP_OK;
    }
    return ESP_ERR_INVALID_STATE;
}

static void fan_save_to_nvs(void){
    nvs_handle_t h; if(nvs_open(NVS_NS_FAN,NVS_READWRITE,&h)!=ESP_OK) return;
    nvs_set_blob(h,NVS_KEY_FAN,&g_fan,sizeof(g_fan)); nvs_commit(h); nvs_close(h);
}

/* ===== PUMP NVS ===== */
static void pump_set_defaults(curve_cfg_t* c){
    memset(c,0,sizeof(*c));
    c->version=1; c->source_mode=DEF_SOURCE_MODE; c->interp_mode=DEF_INTERP_MODE;
    c->rc_tau_sec=DEF_RC_TAU_SEC; c->hyst_pct=DEF_HYST_PCT; c->count=4;
    c->pts[0]=(curve_point_t){30.0f, 0.0f};
    c->pts[1]=(curve_point_t){55.0f,25.0f};
    c->pts[2]=(curve_point_t){75.0f,60.0f};
    c->pts[3]=(curve_point_t){110.0f,100.0f};
}

static esp_err_t pump_load_from_nvs(void){
    size_t len=sizeof(g_pump);
    nvs_handle_t h; esp_err_t err=nvs_open(NVS_NS_PUMP,NVS_READONLY,&h); if(err!=ESP_OK) return err;
    err=nvs_get_blob(h,NVS_KEY_PUMP,&g_pump,&len); nvs_close(h);
    if (err==ESP_OK && len==sizeof(g_pump) && g_pump.version==1 && g_pump.count>=2 && g_pump.count<=CURVE_POINTS_MAX){
        sort_points_by_temp(g_pump.pts,g_pump.count);
        if (g_pump.hyst_pct < 3.0f) g_pump.hyst_pct = 3.0f; else if (g_pump.hyst_pct > 10.0f) g_pump.hyst_pct = 10.0f;
        ESP_LOGI(TAG,"PUMP: %u pts, src=%u, mode=%u, tau=%.2f, hyst=%.2f", g_pump.count,g_pump.source_mode,g_pump.interp_mode,g_pump.rc_tau_sec,g_pump.hyst_pct);
        return ESP_OK;
    }
    return ESP_ERR_INVALID_STATE;
}

static void pump_save_to_nvs(void){
    nvs_handle_t h; if(nvs_open(NVS_NS_PUMP,NVS_READWRITE,&h)!=ESP_OK) return;
    nvs_set_blob(h,NVS_KEY_PUMP,&g_pump,sizeof(g_pump)); nvs_commit(h); nvs_close(h);
}

/* ===== LED low-level ===== */
static inline uint8_t scale_bright(uint8_t v, uint8_t br){ return (uint8_t)((uint16_t)v*(uint16_t)br/255U); }

#define LED_REFRESH_ERR_REINIT 3
#define LED_FRAME_DUPLICATE   0
#define LED_REFRESH_MIN_MS    17
static inline esp_err_t led_refresh_safe(void){
    if (!g_led_strip) return ESP_ERR_INVALID_STATE;
    static uint32_t last_ms = 0;
    uint32_t now_ms = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
    if (last_ms != 0 && (now_ms - last_ms) < LED_REFRESH_MIN_MS) {
        return ESP_ERR_INVALID_STATE;
    }
    esp_err_t err = led_strip_refresh(g_led_strip);
    if (err == ESP_OK) {
        last_ms = now_ms;
    }
    if (err == ESP_ERR_INVALID_STATE) {
        vTaskDelay(pdMS_TO_TICKS(2));
        err = led_strip_refresh(g_led_strip);
        if (err == ESP_OK) {
            last_ms = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
        }
    }
    return err;
}
static inline void led_note_refresh_result(esp_err_t err){
    if (err == ESP_OK) {
        g_led_refresh_errs = 0;
        g_led_invalid_state_cnt = 0;
        return;
    }
    if (err == ESP_ERR_INVALID_STATE) {
        /* RMT channel stuck (not in init state).  A single occurrence can be
         * transient (TX still in progress), but after several consecutive
         * failures the channel is permanently jammed and the only recovery
         * is to delete + re-create the RMT device. */
        if (g_led_invalid_state_cnt < 255) g_led_invalid_state_cnt++;
        if (g_led_invalid_state_cnt >= 10) {
            ESP_LOGW(TAG, "LED RMT: %u consecutive INVALID_STATE – scheduling reinit",
                     (unsigned)g_led_invalid_state_cnt);
            g_led_need_reinit = true;
            g_led_invalid_state_cnt = 0;
        }
        return;
    }
    if (g_led_refresh_errs < 255) g_led_refresh_errs++;
    /* Do not auto-reinit to avoid visible flashes; keep running */
}

static void leds_apply_rgb(uint8_t r,uint8_t g,uint8_t b){
    if (g_led_mtx) xSemaphoreTake(g_led_mtx, portMAX_DELAY);
    if (!g_led_strip) { ESP_LOGW(TAG, "LED strip not initialized"); if (g_led_mtx) xSemaphoreGive(g_led_mtx); return; }
    if (g_led_need_reinit) { if (g_led_mtx) xSemaphoreGive(g_led_mtx); return; }
    for(int i=0;i<LED_STRIP_LENGTH;++i) (void)led_strip_set_pixel(g_led_strip,i,r,g,b);
    esp_err_t err = led_refresh_safe();
    if (err != ESP_OK && g_led_invalid_state_cnt <= 1) {
        ESP_LOGE(TAG, "led_strip_refresh failed: %s", esp_err_to_name(err));
    }
    led_note_refresh_result(err);
    if (g_led_mtx) xSemaphoreGive(g_led_mtx);
}

static void leds_apply_solid(uint8_t r,uint8_t g,uint8_t b,uint8_t br){
    ESP_LOGI(TAG, "Applying solid LED: r=%u g=%u b=%u br=%u", r, g, b, br);
    leds_apply_rgb(scale_bright(r,br),scale_bright(g,br),scale_bright(b,br));
}

static void leds_apply_custom(void){
    if (g_led_mtx) xSemaphoreTake(g_led_mtx, portMAX_DELAY);
    if (!g_led_strip) { if (g_led_mtx) xSemaphoreGive(g_led_mtx); return; }
    if (g_led_need_reinit) { if (g_led_mtx) xSemaphoreGive(g_led_mtx); return; }
    for(int i=0;i<LED_STRIP_LENGTH;++i){
        uint8_t r_raw = g_led_prof.custom_colors[i][0];
        uint8_t g_raw = g_led_prof.custom_colors[i][1];
        uint8_t b_raw = g_led_prof.custom_colors[i][2];
        uint8_t r = scale_bright(r_raw, g_led_prof.brightness);
        uint8_t g = scale_bright(g_raw, g_led_prof.brightness);
        uint8_t b = scale_bright(b_raw, g_led_prof.brightness);
        (void)led_strip_set_pixel(g_led_strip,i,r,g,b);
    }
    esp_err_t err = led_refresh_safe();
    if (err != ESP_OK && g_led_invalid_state_cnt <= 1) {
        ESP_LOGE(TAG, "led_strip_refresh(custom) failed: %s", esp_err_to_name(err));
    }
    led_note_refresh_result(err);
    if (g_led_mtx) xSemaphoreGive(g_led_mtx);
}

static bool leds_off(void){
    bool ok = false;
    if (g_led_mtx) xSemaphoreTake(g_led_mtx, portMAX_DELAY);
    if (!g_led_strip) { if (g_led_mtx) xSemaphoreGive(g_led_mtx); return false; }
    if (g_led_need_reinit) { if (g_led_mtx) xSemaphoreGive(g_led_mtx); return false; }
    (void)led_strip_clear(g_led_strip);
    esp_err_t err = led_refresh_safe();
    if (err == ESP_OK) {
        ok = true;
    } else {
        if (g_led_invalid_state_cnt <= 1) {
            ESP_LOGE(TAG, "led_strip_refresh(off) failed: %s", esp_err_to_name(err));
        }
        led_note_refresh_result(err);
    }
    if (g_led_mtx) xSemaphoreGive(g_led_mtx);
    return ok;
}

static void leds_init(void){
    if (g_led_mtx) xSemaphoreTake(g_led_mtx, portMAX_DELAY);
    if (g_led_strip) { if (g_led_mtx) xSemaphoreGive(g_led_mtx); return; }
    led_strip_config_t strip_config={
        .strip_gpio_num=LED_STRIP_GPIO,
        .max_leds=LED_STRIP_LENGTH,
        .led_model=LED_MODEL_WS2812,
        .led_pixel_format=LED_PIXEL_FORMAT_GRB,
        .flags.invert_out=false,
    };
    led_strip_rmt_config_t rmt_config={
        .clk_src=RMT_CLK_SRC_DEFAULT,
        .resolution_hz=LED_STRIP_RES_HZ,
        /* Use all 512 RMT symbols (ESP32 has 8×64=512 total, we use 1 channel).
         * 20 LEDs need 480+1=481 symbols. With 512 the encoder fills
         * everything upfront before TX starts — zero ISR refills,
         * zero risk of BLE/I2C ISR delays causing false WS2812 resets
         * and green glitches on the tail end of the strip. */
        .mem_block_symbols=512,
        /* On ESP32 (IDF target), DMA is not supported by RMT WS2812 driver; use PIO to avoid boot errors */
        .flags.with_dma=false,
    };
    // Create RMT device without DMA to avoid "DMA not supported" errors on ESP32
    esp_err_t err=led_strip_new_rmt_device(&strip_config,&rmt_config,&g_led_strip);
    if (err!=ESP_OK){
        ESP_LOGE(TAG,"led_strip_new_rmt_device failed: %d",err);
        g_led_strip=NULL;
        if (g_led_mtx) xSemaphoreGive(g_led_mtx);
        return;
    }
    // Clear once after init (do not delete handle)
    (void)led_strip_clear(g_led_strip);
    err = led_strip_refresh(g_led_strip);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "led_strip_refresh(init clear) failed: %d", err);
        /* Defer reinit to led_task to avoid deleting while RMT is busy */
        g_led_need_reinit = true;
        if (g_led_mtx) xSemaphoreGive(g_led_mtx);
        return;
    }
    ESP_LOGI(TAG,"LED strip initialized on GPIO %d, leds=%d",LED_STRIP_GPIO,LED_STRIP_LENGTH);
    // ...existing code...
    if (g_led_mtx) xSemaphoreGive(g_led_mtx);
}

/* LED profile */
static void led_prof_set_defaults(void){
    memset(&g_led_prof,0,sizeof(g_led_prof));
    g_led_prof.version=1;
    g_led_prof.mode=LED_MODE_OFF;
    g_led_prof.r=0; g_led_prof.g=0; g_led_prof.b=0; g_led_prof.brightness=0;
    // custom_colors оставляем 0 (черные)
}

static void led_prof_load(void){
    bool loaded = false;
    led_prof_set_defaults();
    nvs_handle_t h; size_t len=sizeof(g_led_prof);
    if (nvs_open(NVS_NS_LED,NVS_READONLY,&h)==ESP_OK){
        if (g_led_mtx) xSemaphoreTake(g_led_mtx, portMAX_DELAY);
        if (nvs_get_blob(h,NVS_KEY_LED,&g_led_prof,&len)==ESP_OK && len==sizeof(g_led_prof) && g_led_prof.version == 1){
            if (g_led_prof.mode == LED_MODE_CUSTOM){
                ESP_LOGI(TAG,"LED profile loaded: mode=%u(custom) br=%u (first RGB=%u,%u,%u)",
                         g_led_prof.mode, g_led_prof.brightness,
                         (unsigned)g_led_prof.custom_colors[0][0], (unsigned)g_led_prof.custom_colors[0][1], (unsigned)g_led_prof.custom_colors[0][2]);
            } else if (g_led_prof.mode == LED_MODE_GRADIENT_ANIM){
                ESP_LOGI(TAG,"LED profile loaded: mode=%u(gradient) start=(%u,%u,%u) end=(%u,%u,%u) speed=%u br=%u",
                         g_led_prof.mode,
                         g_led_prof.start_r,g_led_prof.start_g,g_led_prof.start_b,
                         g_led_prof.end_r,g_led_prof.end_g,g_led_prof.end_b,
                         g_led_prof.anim_speed,g_led_prof.brightness);
            } else {
                ESP_LOGI(TAG,"LED profile loaded: mode=%u, rgb=(%u,%u,%u), br=%u",
                         g_led_prof.mode,g_led_prof.r,g_led_prof.g,g_led_prof.b,g_led_prof.brightness);
            }
            loaded = true;
        }
        nvs_close(h);
        if (g_led_mtx) xSemaphoreGive(g_led_mtx);
    }
    if (loaded) {
        g_led_dirty = true; /* trigger immediate apply */
    } else {
        ESP_LOGI(TAG, "No LED profile in NVS, LEDs will remain off");
    }
}

static void led_prof_save(void){
    nvs_handle_t h;
    if (nvs_open(NVS_NS_LED,NVS_READWRITE,&h)==ESP_OK){
        nvs_set_blob(h,NVS_KEY_LED,&g_led_prof,sizeof(g_led_prof));
        nvs_commit(h);
        nvs_close(h);
    }
}

/* ===== Pump hours (BLE read/write, NVS persist) ===== */
typedef struct __attribute__((packed)) {
    uint8_t  version;           /* 1 */
    uint32_t total_minutes;     /* wall time while pump > threshold */
    uint64_t total_running_ms;  /* accumulated ms while running */
    uint64_t sum_percent_ms;    /* sum(pct)*ms for average duty */
} pump_hours_t;

static pump_hours_t g_hours = { .version = 1, .total_minutes = 0, .total_running_ms = 0, .sum_percent_ms = 0 };

static void hours_load_from_nvs(void){
    nvs_handle_t h; size_t len = sizeof(g_hours);
    if (nvs_open(NVS_NS_HOURS, NVS_READONLY, &h) == ESP_OK){
        if (nvs_get_blob(h, NVS_KEY_HOURS, &g_hours, &len) == ESP_OK && len == sizeof(g_hours) && g_hours.version == 1){
            ESP_LOGI(TAG, "Hours loaded: min=%u run_ms=%llu sum_pct_ms=%llu", (unsigned)g_hours.total_minutes, (unsigned long long)g_hours.total_running_ms, (unsigned long long)g_hours.sum_percent_ms);
        }
        nvs_close(h);
    }
}

static void hours_save_to_nvs(void){
    nvs_handle_t h;
    if (nvs_open(NVS_NS_HOURS, NVS_READWRITE, &h) == ESP_OK){
        nvs_set_blob(h, NVS_KEY_HOURS, &g_hours, sizeof(g_hours));
        nvs_commit(h);
        nvs_close(h);
    }
}

/* ===== Pump PWM ===== */
static void pump_pwm_set_percent(float pct){
    /* Desired mapping: 100%->5V, 30%->2V, 0%->0V; Drive mapping uses calibrated points for better match */
    float s = clampf(pct, 0.0f, 100.0f);
    if (s <= 0.0f) {
        if (g_pwm_pump_attached) ledc_stop(LEDC_HIGH_SPEED_MODE, LEDC_CHANNEL_1, 0);
        return;
    }
    /* Skip if channel not attached (SP detached it; control_task will re-attach) */
    if (!g_pwm_pump_attached) return;
    /* Во время продувки forced-stop НЕ блокирует помпу */
    if (!g_purge_active){
        uint32_t now_ms_local = (uint32_t)(xTaskGetTickCount()*portTICK_PERIOD_MS);
        if (g_forced_stop_deadline_ms && now_ms_local < g_forced_stop_deadline_ms){
            ledc_stop(LEDC_HIGH_SPEED_MODE, LEDC_CHANNEL_1, 0);
            return;
        }
    }
    float v_des = pump_target_voltage_from_percent(s);
    float v_drv = pump_drive_voltage_from_percent(s);
    float duty_frac = clampf(v_drv / PUMP_SUPPLY_V, 0.0f, 1.0f);
    esp_err_t err;
    err = ledc_timer_resume(LEDC_HIGH_SPEED_MODE, LEDC_TIMER_1);
    if (err != ESP_OK) { ESP_LOGW(TAG, "PUMP: timer_resume err=%s", esp_err_to_name(err)); return; }
    uint32_t duty = (uint32_t)lroundf(duty_frac * (float)LEDC_DUTY_MAX);
    if (duty > LEDC_DUTY_MAX) duty = LEDC_DUTY_MAX;
    ESP_LOGD(TAG, "PUMP PWM: s=%.1f%% -> desired=%.2fV, drive=%.3fV, duty=%lu/%u (%.1f%%), f=%u Hz",
             s, (double)v_des, (double)v_drv, (unsigned long)duty, (unsigned)LEDC_DUTY_MAX, duty_frac*100.0f, (unsigned)LEDC_PUMP_FREQ_HZ);
    err = ledc_set_duty(LEDC_HIGH_SPEED_MODE, LEDC_CHANNEL_1, duty);
    if (err != ESP_OK) { ESP_LOGW(TAG, "PUMP: set_duty err=%s", esp_err_to_name(err)); return; }
    err = ledc_update_duty(LEDC_HIGH_SPEED_MODE, LEDC_CHANNEL_1);
    if (err != ESP_OK) { ESP_LOGW(TAG, "PUMP: update_duty err=%s", esp_err_to_name(err)); }
}

/* ===== Fan PWM ===== */
/* Safe re-attach: fully reconfigure the LEDC timer+channel from scratch.
 * Using LEDC_HIGH_SPEED_MODE which applies updates IMMEDIATELY without
 * the para_up busy-wait that caused WDT hangs / boot-loops on LOW_SPEED_MODE. */
static void safe_ledc_attach_fan(void){
    ledc_timer_config_t t={ .speed_mode=LEDC_HIGH_SPEED_MODE, .duty_resolution=LEDC_TIMER_RES,
                            .timer_num=LEDC_TIMER_0, .freq_hz=LEDC_FAN_FREQ_HZ, .clk_cfg=LEDC_AUTO_CLK };
    esp_err_t err = ledc_timer_config(&t);
    if (err != ESP_OK) { ESP_LOGE(TAG, "FAN: timer_config err=%s", esp_err_to_name(err)); return; }
    ledc_channel_config_t c={ .gpio_num=FAN_PWM_GPIO, .speed_mode=LEDC_HIGH_SPEED_MODE,
                              .channel=LEDC_CHANNEL_0, .intr_type=LEDC_INTR_DISABLE,
                              .timer_sel=LEDC_TIMER_0, .duty=0, .hpoint=0 };
    err = ledc_channel_config(&c);
    if (err != ESP_OK) { ESP_LOGE(TAG, "FAN: channel_config err=%s", esp_err_to_name(err)); return; }
    (void)ledc_stop(LEDC_HIGH_SPEED_MODE, LEDC_CHANNEL_0, 0);
    g_pwm_fan_attached = true;
}
static void safe_ledc_attach_pump(void){
    ledc_timer_config_t t={ .speed_mode=LEDC_HIGH_SPEED_MODE, .duty_resolution=LEDC_TIMER_RES,
                            .timer_num=LEDC_TIMER_1, .freq_hz=LEDC_PUMP_FREQ_HZ, .clk_cfg=LEDC_AUTO_CLK };
    esp_err_t err = ledc_timer_config(&t);
    if (err != ESP_OK) { ESP_LOGE(TAG, "PUMP: timer_config err=%s", esp_err_to_name(err)); return; }
    ledc_channel_config_t c={ .gpio_num=PUMP_PWM_GPIO, .speed_mode=LEDC_HIGH_SPEED_MODE,
                              .channel=LEDC_CHANNEL_1, .intr_type=LEDC_INTR_DISABLE,
                              .timer_sel=LEDC_TIMER_1, .duty=0, .hpoint=0 };
    err = ledc_channel_config(&c);
    if (err != ESP_OK) { ESP_LOGE(TAG, "PUMP: channel_config err=%s", esp_err_to_name(err)); return; }
    (void)ledc_stop(LEDC_HIGH_SPEED_MODE, LEDC_CHANNEL_1, 0);
    g_pwm_pump_attached = true;
}

static void fan_pwm_init(void){
    /* GPIOs are already pinned LOW from early app_main, but reinforce pull-down
       before LEDC takes over the pin mux. */
    gpio_set_pull_mode((gpio_num_t)FAN_PWM_GPIO, GPIO_PULLDOWN_ONLY);
    gpio_pulldown_en((gpio_num_t)FAN_PWM_GPIO);
    gpio_set_pull_mode((gpio_num_t)PUMP_PWM_GPIO, GPIO_PULLDOWN_ONLY);
    gpio_pulldown_en((gpio_num_t)PUMP_PWM_GPIO);
    /* safe_ledc_attach_* handles full timer+channel config internally;
     * no separate ledc_timer_config needed here (avoids triple-config race). */
    safe_ledc_attach_fan();
    safe_ledc_attach_pump();
}

static void fan_pwm_set_percent(float pct){
    float p=clampf(pct,0.0f,100.0f);
#if FAN_PWM_INVERT
    p = 100.0f - p;
#endif
    uint32_t now_ms_local = (uint32_t)(xTaskGetTickCount()*portTICK_PERIOD_MS);
    if (g_forced_stop_deadline_ms && now_ms_local < g_forced_stop_deadline_ms){
        if (g_pwm_fan_attached) ledc_stop(LEDC_HIGH_SPEED_MODE,LEDC_CHANNEL_0,0);
        return;
    }
    if (p<=0.0f){ if (g_pwm_fan_attached) ledc_stop(LEDC_HIGH_SPEED_MODE,LEDC_CHANNEL_0,0); return; }
    /* Skip if channel not attached (SP detached it; control_task will re-attach) */
    if (!g_pwm_fan_attached) return;
    esp_err_t err;
    err = ledc_timer_resume(LEDC_HIGH_SPEED_MODE,LEDC_TIMER_0);
    if (err != ESP_OK) { ESP_LOGW(TAG, "FAN: timer_resume err=%s", esp_err_to_name(err)); return; }
    uint32_t duty=(uint32_t)lroundf((p/100.0f)*LEDC_DUTY_MAX);
    if (duty > LEDC_DUTY_MAX) duty = LEDC_DUTY_MAX;
    err = ledc_set_duty(LEDC_HIGH_SPEED_MODE,LEDC_CHANNEL_0,duty);
    if (err != ESP_OK) { ESP_LOGW(TAG, "FAN: set_duty err=%s", esp_err_to_name(err)); return; }
    err = ledc_update_duty(LEDC_HIGH_SPEED_MODE,LEDC_CHANNEL_0);
    if (err != ESP_OK) { ESP_LOGW(TAG, "FAN: update_duty err=%s", esp_err_to_name(err)); }
}

/* Ensure LEDC timers/channels are initialized exactly once */
static void ensure_ledc_init_once(void){
    static bool inited = false;
    if (!inited){
        /* Hardware-reset LEDC peripheral to clear any stuck state
         * (e.g. stale para_up bits surviving SW_CPU_RESET after WDT) */
        periph_module_reset(PERIPH_LEDC_MODULE);
        fan_pwm_init();
        inited = true;
    }
}

/* ===== Temp source ===== */
static float pick_source_temp(uint8_t source_mode){
    float cpu=(g_cpu_temp_c>-500)?(float)g_cpu_temp_c:NAN;
    float gpu=(g_gpu_temp_c>-500)?(float)g_gpu_temp_c:NAN;
    switch((src_sel_t)source_mode){
        case SRC_CPU: return isnan(cpu)?gpu:cpu;
        case SRC_GPU: return isnan(gpu)?cpu:gpu;
        case SRC_MAX:
        default:      if (isnan(cpu)) return gpu; if (isnan(gpu)) return cpu; return fmaxf(cpu,gpu);
    }
}

/* ===== LED profile command 'LX' ===== */
static bool apply_lx_bytes(const uint8_t* buf, uint16_t total){
    ESP_LOGI(TAG, "apply_lx_bytes: total=%u, buf[0]=%c, buf[1]=%c, ver=%u, mode=%u", total, buf[0], buf[1], buf[2], buf[3]);
    if (total<5) return false;
    if (!(buf[0]=='L' && buf[1]=='X')) return false;
    uint8_t ver=buf[2]; if (ver!=1) return false;
    uint8_t mode=buf[3], brightness=buf[4];
    if (!g_led_strip) leds_init();
    if (g_led_mtx) xSemaphoreTake(g_led_mtx, portMAX_DELAY);
    g_led_prof.version=1;
    if (mode == LED_MODE_CUSTOM) {
        if (total < 5 + sizeof(g_led_prof.custom_colors)) { if (g_led_mtx) xSemaphoreGive(g_led_mtx); return false; }
        g_led_prof.mode = mode;
        g_led_prof.brightness = brightness;
        memcpy(g_led_prof.custom_colors, &buf[5], sizeof(g_led_prof.custom_colors));
    } else if (mode == LED_MODE_GRADIENT_ANIM) {
        if (total < 12) { if (g_led_mtx) xSemaphoreGive(g_led_mtx); return false; }
        g_led_prof.mode = mode;
        g_led_prof.brightness = brightness;
        g_led_prof.start_r = buf[5]; g_led_prof.start_g = buf[6]; g_led_prof.start_b = buf[7];
        g_led_prof.end_r = buf[8]; g_led_prof.end_g = buf[9]; g_led_prof.end_b = buf[10];
        g_led_prof.anim_speed = buf[11];
        ESP_LOGI(TAG,"LED gradient anim set: start=(%u,%u,%u) end=(%u,%u,%u) speed=%u br=%u", g_led_prof.start_r, g_led_prof.start_g, g_led_prof.start_b, g_led_prof.end_r, g_led_prof.end_g, g_led_prof.end_b, g_led_prof.anim_speed, g_led_prof.brightness);
    } else if (total >= 8) {
        g_led_prof.mode = (mode<=LED_MODE_BREATHE)?mode:LED_MODE_SOLID;
        g_led_prof.brightness = brightness;
        g_led_prof.r = buf[5]; g_led_prof.g = buf[6]; g_led_prof.b = buf[7];
    } else {
        /* brightness-only update (compact) */
        /* keep current colors/palette/anim params; just switch mode and brightness */
        g_led_prof.mode = (mode<=LED_MODE_GRADIENT_ANIM)?mode:g_led_prof.mode;
        g_led_prof.brightness = brightness;
    }
    led_prof_save(); g_led_dirty=true;
    if (g_led_mtx) xSemaphoreGive(g_led_mtx);
    /* Apply asynchronously in led_task to avoid races with RMT driver */
    if (mode == LED_MODE_CUSTOM) {
        ESP_LOGI(TAG,"LED profile set: mode=%u (custom) br=%u", g_led_prof.mode, g_led_prof.brightness);
    } else {
        ESP_LOGI(TAG,"LED profile set: mode=%u rgb=(%u,%u,%u) br=%u", g_led_prof.mode, g_led_prof.r, g_led_prof.g, g_led_prof.b, g_led_prof.brightness);
    }
    return true;
}

/* ===== Curve parsers 'FC'/'PC' ===== */
static bool parse_curve_bytes_into(curve_cfg_t* dst,const uint8_t* buf,uint16_t total,char tag1,char tag2){
    if (total<6) return false;
    if (!(buf[0]==(uint8_t)tag1 && buf[1]==(uint8_t)tag2)) return false;
    uint8_t ver=buf[2], src=buf[3], mode=buf[4], n=buf[5];
    if ((ver!=1 && ver!=2) || n<2 || n>CURVE_POINTS_MAX) return false;
    size_t header = (ver==2)?7:6;
    size_t need=header + (size_t)n*3; if (total<need) return false;
    curve_cfg_t nc=*dst;
    nc.version=1;
    nc.source_mode=(src<=2)?src:DEF_SOURCE_MODE;
    nc.interp_mode=(mode<=1)?mode:DEF_INTERP_MODE;
    nc.count=n;
    if (ver==2){
        uint8_t hyst = buf[6];
        float hp = (float)hyst;
        if (hp < 3.0f) hp = 3.0f;
        if (hp > 10.0f) hp = 10.0f;
        nc.hyst_pct = hp;
    }
    const uint8_t* p=&buf[header];
    for(uint8_t i=0;i<n;++i){
        int16_t tx10=(int16_t)(p[0] | (p[1]<<8));
        uint8_t sp=p[2]; p+=3;
        float tC=((float)tx10)/10.0f;
        float sP=(float)sp;
        nc.pts[i].t=clampf(tC,TEMP_MIN_C,TEMP_MAX_C);
        nc.pts[i].s=clampf(sP,SPEED_MIN_PCT,SPEED_MAX_PCT);
    }
    sort_points_by_temp(nc.pts,nc.count);
    *dst=nc;
    return true;
}

static bool apply_fc_bytes(const uint8_t* buf, uint16_t total){
    if (!parse_curve_bytes_into(&g_fan,buf,total,'F','C')) return false;
    fan_save_to_nvs(); gpio_set_level(LED_GPIO,1); vTaskDelay(pdMS_TO_TICKS(50)); gpio_set_level(LED_GPIO,0);
    ESP_LOGI(TAG,"FAN CFG updated"); return true;
}

static bool apply_pc_bytes(const uint8_t* buf, uint16_t total){
    if (!parse_curve_bytes_into(&g_pump,buf,total,'P','C')) return false;
    pump_save_to_nvs(); gpio_set_level(LED_GPIO,1); vTaskDelay(pdMS_TO_TICKS(50)); gpio_set_level(LED_GPIO,0);
    ESP_LOGI(TAG,"PUMP CFG updated"); return true;
}

/* UART 'VC' — Vent Calibration: trigger RPM autocalibration */
static int __attribute__((unused)) sp_try_vc(const uint8_t* d,size_t l,size_t* used){
    if (l < 2) return 0;
    if (!(d[0]=='V' && d[1]=='C')){ *used=1; return -1; }
    *used=2;
    rpm_autocalibrate();
    return 1;
}

/* ===== Tachometer ===== */
static void IRAM_ATTR tach_isr(void* arg){
    intptr_t id = (intptr_t)arg;
    uint32_t now = (uint32_t)esp_timer_get_time();
    if (id == 1) {
        uint32_t last = g_tach1_last_us;
        if ((uint32_t)(now - last) >= TACH_MIN_EDGE_US) {
            g_tach1_last_us = now;
            g_tach1_edges++;
        }
    } else {
        uint32_t last = g_tach2_last_us;
        if ((uint32_t)(now - last) >= TACH_MIN_EDGE_US) {
            g_tach2_last_us = now;
            g_tach2_edges++;
        }
    }
}

static void tach_init(void){
    gpio_config_t io = {
        .pin_bit_mask = (1ULL<<TACH1_GPIO) | (1ULL<<TACH2_GPIO),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_NEGEDGE, /* fans are open-collector: count falling edges */
    };
    ESP_ERROR_CHECK(gpio_config(&io));
    static bool isr_installed = false;
    if (!isr_installed){
        ESP_ERROR_CHECK(gpio_install_isr_service(0));
        isr_installed = true;
    }
    ESP_ERROR_CHECK(gpio_isr_handler_add(TACH1_GPIO, tach_isr, (void*)1));
    ESP_ERROR_CHECK(gpio_isr_handler_add(TACH2_GPIO, tach_isr, (void*)2));
    g_tach1_edges = g_tach2_edges = 0;
    g_rpm1 = g_rpm2 = 0;
    g_rpm_flags = 0;
}

#if CONFIG_BT_NIMBLE_ENABLED
static void rpm_notify_ble(void){
    if (!g_ble_connected || g_conn_handle == 0 || g_rpm_val_handle == 0) return;
    struct {
        int32_t rpm1;
        int32_t rpm2;
        uint32_t flags;
    } __attribute__((packed)) pkt;
    pkt.rpm1 = g_rpm1; /* уже калиброванные */
    pkt.rpm2 = g_rpm2;
    pkt.flags = g_rpm_flags;

    struct os_mbuf *om = ble_hs_mbuf_from_flat(&pkt, sizeof(pkt));
    if (om){
        int rc = ble_gatts_notify_custom(g_conn_handle, g_rpm_val_handle, om);
        if (rc != 0){
            ESP_LOGW(TAG, "rpm notify rc=%d", rc);
        }
    }
}
#endif

#if CONFIG_BT_NIMBLE_ENABLED
static void water_notify_ble(void){
    if (!g_ble_connected || g_conn_handle == 0 || g_water_val_handle == 0) return;
    int32_t w = g_water_temp_c;
    struct os_mbuf *om = ble_hs_mbuf_from_flat(&w, sizeof(w));
    if (om){
        int rc = ble_gatts_notify_custom(g_conn_handle, g_water_val_handle, om);
        if (rc != 0){
            ESP_LOGW(TAG, "water notify rc=%d", rc);
        }
    }
}
#endif

/* NEW: UART helper to send RPM packets 'RP' + <iiI> (калиброванные значения) */
static void uart_send_rp(int32_t rpm1, int32_t rpm2, uint32_t flags){
    uint8_t buf[2 + 12];
    buf[0] = 'R';
    buf[1] = 'P';
    memcpy(&buf[2],  &rpm1, 4);
    memcpy(&buf[6],  &rpm2, 4);
    memcpy(&buf[10], &flags, 4);
    (void)uart_write_bytes(UART_PORT, (const char*)buf, sizeof(buf));
}

/* NEW: UART helper to send Water temperature 'WT' + <i> (deg C as int) */
static void uart_send_wt(int32_t water_c){
    uint8_t buf[2 + 4];
    buf[0] = 'W';
    buf[1] = 'T';
    memcpy(&buf[2], &water_c, 4);
    (void)uart_write_bytes(UART_PORT, (const char*)buf, sizeof(buf));
}

/* NEW: UART helper to send Hours 'HR' + <pump_hours_t> (packed) */
static void uart_send_hr(void){
    uint8_t buf[2 + sizeof(g_hours)];
    buf[0] = 'H';
    buf[1] = 'R';
    memcpy(&buf[2], &g_hours, sizeof(g_hours));
    (void)uart_write_bytes(UART_PORT, (const char*)buf, sizeof(buf));
}

/* NEW: UART helper to send Loop Status 'LS' + <uint8_t code>
 * code: 0=disabled, 1=ok(was pause), 2=broken, 3=restored(was running) */
static void uart_send_ls(uint8_t code){
    uint8_t buf[3];
    buf[0] = 'L';
    buf[1] = 'S';
    buf[2] = code;
    (void)uart_write_bytes(UART_PORT, (const char*)buf, sizeof(buf));
}

/* ===== 1-Wire / DS18B20 low-level ===== */
static inline void ow_drive_low(void){
    gpio_set_direction(DS18B20_GPIO, GPIO_MODE_OUTPUT);
    gpio_set_level(DS18B20_GPIO, 0);
}
static inline void ow_release_bus(void){
    gpio_set_direction(DS18B20_GPIO, GPIO_MODE_INPUT);
}
static inline int ow_read_level(void){
    return gpio_get_level(DS18B20_GPIO);
}
static inline void delay_us(uint32_t us){
    int64_t start = esp_timer_get_time();
    while ((int64_t)(esp_timer_get_time() - start) < (int64_t)us) {
        ;
    }
}

static bool onewire_reset(void){
    /* Pull low for >=480us, then release and sample presence */
    ow_drive_low();
    delay_us(500);
    ow_release_bus();
    delay_us(70);
    int presence = (ow_read_level() == 0);
    delay_us(410);
    return presence;
}

static inline void onewire_write_bit(int bit){
    if (bit){
        ow_drive_low();
        delay_us(6);
        ow_release_bus();
        delay_us(64);
    } else {
        ow_drive_low();
        delay_us(60);
        ow_release_bus();
        delay_us(10);
    }
}

static inline int onewire_read_bit(void){
    int bit;
    ow_drive_low();
    delay_us(6);
    ow_release_bus();
    delay_us(9);
    bit = ow_read_level();
    delay_us(55);
    return bit & 1;
}

static void onewire_write_byte(uint8_t v){
    for (int i=0;i<8;++i){
        onewire_write_bit((v>>i)&1);
    }
}

static uint8_t onewire_read_byte(void){
    uint8_t v=0;
    for (int i=0;i<8;++i){
        v |= (onewire_read_bit() << i);
    }
    return v;
}

static uint8_t ds18b20_crc8(const uint8_t *data, int len){
    uint8_t crc = 0;
    for (int i = 0; i < len; i++){
        uint8_t inbyte = data[i];
        for (uint8_t j = 0; j < 8; j++){
            uint8_t mix = (crc ^ inbyte) & 0x01;
            crc >>= 1;
            if (mix) crc ^= 0x8C; /* Dallas/Maxim */
            inbyte >>= 1;
        }
    }
    return crc;
}

static bool ds18b20_read_celsius(int32_t *out_c){
    if (!onewire_reset()) return false;
    /* Skip ROM (single sensor) and start conversion */
    onewire_write_byte(0xCC); /* SKIP ROM */
    onewire_write_byte(0x44); /* CONVERT T */
    /* Strong pull-up for conversion time (~750ms) to support parasite power */
    ow_release_bus();
    gpio_set_direction(DS18B20_GPIO, GPIO_MODE_OUTPUT);
    gpio_set_level(DS18B20_GPIO, 1);
    vTaskDelay(pdMS_TO_TICKS(900));
    ow_release_bus();
    if (!onewire_reset()) return false;
    onewire_write_byte(0xCC); /* SKIP ROM */
    onewire_write_byte(0xBE); /* READ SCRATCHPAD */
    uint8_t scratch[9];
    for (int i=0;i<9;i++) scratch[i] = onewire_read_byte();
    /* CRC check */
    if (ds18b20_crc8(scratch, 8) != scratch[8]){
        return false;
    }
    int16_t raw = (int16_t)((scratch[1] << 8) | scratch[0]);
    float celsius = (float)raw / 16.0f;
    if (out_c) *out_c = (int32_t)lroundf(celsius);
    return true;
}

static void ds18b20_task(void *arg){
    /* Configure pull-up on the line */
    gpio_config_t io = {
        .pin_bit_mask = (1ULL << DS18B20_GPIO),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&io);
    /* Idle released */
    ow_release_bus();

    for(;;){
        int32_t w = -1000;
        bool ok = ds18b20_read_celsius(&w);
        if (!ok){
            /* Keep previous if available */
            ESP_LOGW(TAG, "DS18B20 read failed");
        } else {
            g_water_temp_c = w;
            g_last_water_ms = (uint32_t)(xTaskGetTickCount()*portTICK_PERIOD_MS);
        }
        /* Log what we actually transmit each second */
        ESP_LOGI(TAG, "WT TX: %ld%s", (long)g_water_temp_c, ok?"":" (stale)");
        /* Always send current known value (or last) once per second */
        uart_send_wt(g_water_temp_c);
#if CONFIG_BT_NIMBLE_ENABLED
        water_notify_ble();
#endif
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

/* Применение калибровки и ограничений */
static inline int32_t rpm_apply_calibrate_clamp(int32_t raw, float scale, int min_rpm, int max_rpm){
    float f = ((float)raw) * scale;
    int32_t v = (int32_t)lroundf(f);
    if (v < 0) v = 0;
    if (max_rpm > 0 && v > max_rpm) v = max_rpm;
    if (min_rpm > 0 && v > 0 && v < min_rpm) v = min_rpm; /* при желании можно отключить, оставлено как «поддержка» */
    return v;
}

static void tach_sample_and_publish(uint32_t interval_ms){
    if (g_calibrating) {
        /* During calibration, skip publishing RPM from control loop to avoid conflicts */
        return;
    }
    /* Сэмплируем импульсы за интервал */
    uint32_t e1 = g_tach1_edges;
    uint32_t e2 = g_tach2_edges;
    g_tach1_edges = 0;
    g_tach2_edges = 0;

    float seconds = (float)interval_ms / 1000.0f;
    /* «сырые» RPM до калибровки */
    int32_t rpm1_raw = (int32_t)lroundf(((float)e1 / (float)TACH_PULSES_PER_REV) * (60.0f / seconds));
    int32_t rpm2_raw = (int32_t)lroundf(((float)e2 / (float)TACH_PULSES_PER_REV) * (60.0f / seconds));

    /* Калибровка и ограничение сверху по паспорту */
    /* Применяем калибровку по коэффициентам и ограничиваем сверху паспортным максимумом */
    int32_t rpm1_cal = (int32_t)lroundf(((float)rpm1_raw) * g_rpm_scale1);
    int32_t rpm2_cal = (int32_t)lroundf(((float)rpm2_raw) * g_rpm_scale2);
    if (rpm1_cal < 0) rpm1_cal = 0;
    if (rpm2_cal < 0) rpm2_cal = 0;
    if (rpm1_cal > FAN1_RPM_MAX) rpm1_cal = FAN1_RPM_MAX;
    if (rpm2_cal > FAN2_RPM_MAX) rpm2_cal = FAN2_RPM_MAX;

    /* Ограничение скорости нарастания RPM (выключено по умолчанию: 0 = без ограничения) */
    #ifndef RPM_RATE_UP_MAX
    #define RPM_RATE_UP_MAX 0
    #endif
    if (RPM_RATE_UP_MAX > 0) {
        int32_t max_inc = (int32_t)lroundf((float)RPM_RATE_UP_MAX * seconds);
        if (rpm1_cal > g_rpm1 + max_inc) rpm1_cal = g_rpm1 + max_inc;
        if (rpm2_cal > g_rpm2 + max_inc) rpm2_cal = g_rpm2 + max_inc;
    }

    g_rpm1 = rpm1_cal;
    g_rpm2 = rpm2_cal;

    /* Проверяем grace period при запуске системы (5 секунд) */
    uint32_t now = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
    bool startup_grace_period = (now - g_system_startup_ms) < 5000;

    /* Флаги «авария» проверяем по калиброванным значениям */
    uint32_t flags = 0;
    /* Таймеры залипания: храним момент начала стала (0 = нет стала) */
    static uint32_t f1_stall_since = 0;
    static uint32_t f2_stall_since = 0;
    if (g_purge_active) {
        flags |= RPM_FLAG_PURGE; /* suppress faults during purge */
        f1_stall_since = 0;
        f2_stall_since = 0;
    } else if (g_waiting_for_temps) {
        /* Suppress stall detection while waiting for target temperatures.
         * PWM is 0, RPM is 0 — this is expected, not a fault. */
        f1_stall_since = 0;
        f2_stall_since = 0;
    } else {
        bool f1_cond = g_system_running && (g_ble_connected || g_usb_connected)
                       && !startup_grace_period
                       && g_fan_last_appl > 1.0f && g_rpm1 < RPM_FAULT_MIN;
        bool f2_cond = g_system_running && (g_ble_connected || g_usb_connected)
                       && !startup_grace_period
                       && g_pump_last_appl > 1.0f && g_rpm2 < RPM_FAULT_MIN;

        /* Запускаем таймер при начале стала, сбрасываем при выходе */
        if (f1_cond) { if (f1_stall_since == 0) f1_stall_since = now; }
        else           { f1_stall_since = 0; }
        if (f2_cond) { if (f2_stall_since == 0) f2_stall_since = now; }
        else           { f2_stall_since = 0; }

        /* Авария — только если стал длится >= 45 секунд */
        if (f1_stall_since != 0 && (now - f1_stall_since) >= 45000u) flags |= RPM_FLAG_F1;
        if (f2_stall_since != 0 && (now - f2_stall_since) >= 45000u) flags |= RPM_FLAG_F2;
    }
    g_rpm_flags = flags;

    /* Логи: raw и калиброванные значения */
    ESP_LOGI(TAG, "RPM RAW: f1=%ld f2=%ld  -> CAL: f1=%ld f2=%ld  flags=0x%02X (dt=%.2fs)",
             (long)rpm1_raw, (long)rpm2_raw, (long)g_rpm1, (long)g_rpm2, (unsigned)g_rpm_flags, seconds);

#if CONFIG_BT_NIMBLE_ENABLED
    rpm_notify_ble();
#endif

    /* Отправляем в Windows‑приложение по UART (USB) калиброванные RPM */
    uart_send_rp(g_rpm1, g_rpm2, g_rpm_flags);
}

/* ===== BLE GATT callbacks ===== */
#if CONFIG_BT_NIMBLE_ENABLED
static int fan_cfg_write_cb(uint16_t, uint16_t, struct ble_gatt_access_ctxt *ctxt, void *){
    if (ctxt->op!=BLE_GATT_ACCESS_OP_WRITE_CHR) return BLE_ATT_ERR_UNLIKELY;
    uint16_t total=OS_MBUF_PKTLEN(ctxt->om); if (total>64) total=64;
    uint8_t buf[64]; os_mbuf_copydata(ctxt->om,0,total,buf);
    (void)apply_fc_bytes(buf,total); return 0;
}

static int pump_cfg_write_cb(uint16_t, uint16_t, struct ble_gatt_access_ctxt *ctxt, void *){
    if (ctxt->op!=BLE_GATT_ACCESS_OP_WRITE_CHR) return BLE_ATT_ERR_UNLIKELY;
    uint16_t total=OS_MBUF_PKTLEN(ctxt->om); if (total>64) total=64;
    uint8_t buf[64]; os_mbuf_copydata(ctxt->om,0,total,buf);
    (void)apply_pc_bytes(buf,total); return 0;
}

static int temp_write_cb(uint16_t, uint16_t, struct ble_gatt_access_ctxt *ctxt, void *){
    if (ctxt->op!=BLE_GATT_ACCESS_OP_WRITE_CHR) return BLE_ATT_ERR_UNLIKELY;
    uint16_t total=OS_MBUF_PKTLEN(ctxt->om); if (total!=8) return 0;
    int32_t pair[2]={0}; os_mbuf_copydata(ctxt->om,0,8,pair);
    g_cpu_temp_c=pair[0]; g_gpu_temp_c=pair[1];
    g_last_temp_ms=(uint32_t)(xTaskGetTickCount()*portTICK_PERIOD_MS);
    gpio_set_level(LED_GPIO,1); vTaskDelay(pdMS_TO_TICKS(20)); gpio_set_level(LED_GPIO,0);
    return 0;
}

static int __attribute__((unused)) cal_write_cb(uint16_t, uint16_t, struct ble_gatt_access_ctxt *ctxt, void *){
    if (ctxt->op!=BLE_GATT_ACCESS_OP_WRITE_CHR) return BLE_ATT_ERR_UNLIKELY;
    /* Any write triggers calibration */
    rpm_autocalibrate();
    return 0;
}

static int led_write_cb(uint16_t, uint16_t, struct ble_gatt_access_ctxt *ctxt, void *){
    if (ctxt->op!=BLE_GATT_ACCESS_OP_WRITE_CHR) return BLE_ATT_ERR_UNLIKELY;
    uint16_t total=OS_MBUF_PKTLEN(ctxt->om); if (total>64) total=64;
    uint8_t buf[64]; os_mbuf_copydata(ctxt->om,0,total,buf);
    if (total>=2 && buf[0]=='L' && buf[1]=='X'){ (void)apply_lx_bytes(buf,total); return 0; }
    if (!g_led_strip) leds_init();
    if (total==4){
        if (g_led_mtx) xSemaphoreTake(g_led_mtx, portMAX_DELAY);
        g_led_prof.version=1; g_led_prof.mode=LED_MODE_SOLID;
        g_led_prof.r=buf[0]; g_led_prof.g=buf[1]; g_led_prof.b=buf[2]; g_led_prof.brightness=buf[3];
        led_prof_save(); g_led_dirty=true;
        if (g_led_mtx) xSemaphoreGive(g_led_mtx);
    } else if (total==3){
        if (g_led_mtx) xSemaphoreTake(g_led_mtx, portMAX_DELAY);
        g_led_prof.version=1; g_led_prof.mode=LED_MODE_SOLID;
        g_led_prof.r=buf[0]; g_led_prof.g=buf[1]; g_led_prof.b=buf[2];
        led_prof_save(); g_led_dirty=true;
        if (g_led_mtx) xSemaphoreGive(g_led_mtx);
    }
    return 0;
}

/* Forward decls for purge control */
static void purge_start(void);
static void purge_stop(void);

/* Control characteristic write: expects 2-3 byte commands 'PG'/'ST'/'SP' and 'LP'+<1|0> */
static int ctrl_write_cb(uint16_t, uint16_t, struct ble_gatt_access_ctxt *ctxt, void *){
    if (ctxt->op!=BLE_GATT_ACCESS_OP_WRITE_CHR) return BLE_ATT_ERR_UNLIKELY;
    uint16_t total=OS_MBUF_PKTLEN(ctxt->om);
    if (total < 2) return BLE_ATT_ERR_UNLIKELY;
    uint8_t cmd[4]={0}; if (total>sizeof(cmd)) total=sizeof(cmd);
    os_mbuf_copydata(ctxt->om,0,total,cmd);
    if (cmd[0]=='P' && cmd[1]=='G') {
        if (g_loopprot_enabled && !g_loop_ok){ ESP_LOGW(TAG, "LOOP: broken, purge denied"); return 0; }
        g_purge_seen_since_last_stop = true; /* track that purge command was issued */
        purge_start();
    } else if (cmd[0]=='S' && cmd[1]=='T') {
        /* 'ST' -> start normal operation.
         * IMPORTANT: heavy LEDC re-attach and boost start are deferred to control_task
         * to avoid stack overflow / para_up hang in the NimBLE host task context. */
        if (g_loopprot_enabled && !g_loop_ok){ ESP_LOGW(TAG, "LOOP: broken, start denied"); return 0; }
        g_forced_stop_deadline_ms = 0; /* clear guard */
        if (g_purge_active) purge_stop();
        /* Force immediate curve re-eval for fan */
        g_fan_last_filt = NAN; g_pump_last_filt = NAN;
        g_fan_last_appl = NAN; g_pump_last_appl = 0.0f;
        g_start_pending = true; /* control_task will check NVS boost flag once */
        g_lp_restore_ms = 0;     /* clear rearm state — system is starting */
        g_system_running = true; /* set LAST so control_task sees consistent state */
    } else if (cmd[0]=='S' && cmd[1]=='P') {
        /* 'SP' -> stop system: set flags, heavy HW ops deferred to control_task */
        g_system_running = false;
        g_waiting_for_temps = false; /* clear waiting flag on stop */
        g_stop_pending = true;   /* control_task will kill LEDC/GPIO */
        /* Cancel any boost */
        g_pump_boost_active = false;
        bool will_arm = (g_purge_completed_since_last_stop || g_purge_seen_since_last_stop);
        bool was_armed = g_pump_boost_armed;
        g_pump_boost_armed = was_armed || will_arm; /* preserve existing arm across extra STOPs */
        if (g_pump_boost_armed){
            ESP_LOGI(TAG, "PUMP BOOST: armed (via SP BLE) completed=%d seen=%d keep=%d", (int)g_purge_completed_since_last_stop, (int)g_purge_seen_since_last_stop, was_armed?1:0);
        }
        g_purge_completed_since_last_stop = false; g_purge_seen_since_last_stop = false;
        if (g_purge_active) purge_stop(); /* cancel active purge on STOP */
    } else if (cmd[0]=='L' && cmd[1]=='K') {
        /* New: 'LK' + <byte> (non-zero to enable) */
        if (total >= 3){
            bool new_flag = (cmd[2] != 0);
            g_led_allow_disconnected = new_flag;
            nvs_handle_t h; if (nvs_open(NVS_NS_LED, NVS_READWRITE, &h) == ESP_OK){
                (void)nvs_set_u8(h, "keep_on", new_flag?1:0);
                (void)nvs_commit(h); nvs_close(h);
            }
            ESP_LOGI(TAG, "CTRL: keep_on set to %d", (int)new_flag);
            if (new_flag) {
                /* If we just enabled and have a saved profile, mark dirty to apply immediately */
                if (g_led_prof.mode != LED_MODE_OFF) g_led_dirty = true;
            } else {
                /* If disabling and no connections present, turn off immediately */
                if (!g_ble_connected && !g_usb_connected) leds_off();
            }
        }
    } else if (cmd[0]=='L' && cmd[1]=='P') {
        if (total >= 3){
            bool en = (cmd[2] != 0);
            g_loopprot_enabled = en;
            nvs_handle_t h; if (nvs_open("sys", NVS_READWRITE, &h) == ESP_OK){
                (void)nvs_set_u8(h, "loopprot", en?1:0);
                (void)nvs_commit(h); nvs_close(h);
            }
            ESP_LOGI(TAG, "CTRL: loop protection %s", en?"ENABLED":"DISABLED");
            /* Если включаем защиту и петля уже разорвана — немедленно принудительно STOP */
            if (en && !g_loop_ok){
                g_system_running = false;
                fan_pwm_set_percent(0.0f);
                pump_pwm_set_percent(0.0f);
                (void)ledc_stop(LEDC_HIGH_SPEED_MODE, LEDC_CHANNEL_0, 0);
                (void)ledc_stop(LEDC_HIGH_SPEED_MODE, LEDC_CHANNEL_1, 0);
                gpio_set_direction((gpio_num_t)FAN_PWM_GPIO, GPIO_MODE_OUTPUT); gpio_set_level((gpio_num_t)FAN_PWM_GPIO, 0);
                gpio_set_direction((gpio_num_t)PUMP_PWM_GPIO, GPIO_MODE_OUTPUT); gpio_set_level((gpio_num_t)PUMP_PWM_GPIO, 0);
                g_pwm_fan_attached = false; g_pwm_pump_attached = false;
                uint32_t now_ms = (uint32_t)(xTaskGetTickCount()*portTICK_PERIOD_MS);
                g_forced_stop_deadline_ms = now_ms + 1500u;
                g_pump_boost_active = false;
                if (g_purge_active) purge_stop();
                ESP_LOGW(TAG, "LOOP: enforced STOP on enable (broken)");
            }
            /* Send status notify to subscribers (0/1/2) */
            #if CONFIG_BT_NIMBLE_ENABLED
            if (g_ble_connected && g_loop_stat_val_handle){
                uint8_t code = en ? (g_loop_ok ? 1 : 2) : 0;
                struct os_mbuf* om = ble_hs_mbuf_from_flat(&code, 1);
                if (om) {
                    int rc = ble_gatts_notify_custom(g_conn_handle, g_loop_stat_val_handle, om);
                    if (rc != 0) ESP_LOGW(TAG, "LOOP notify(toggle) rc=%d", rc);
                }
            }
            #endif
        }
    } else if (cmd[0]=='O' && cmd[1]=='B') {
        /* OLED brightness: 'OB' + <uint8> */
        if (total >= 3){
            uint8_t obr = cmd[2];
            g_oled_brightness = obr;
            if (g_oled_inited){
                if (obr == 0){
                    oled_send_cmd(0xAE); /* display off */
                } else {
                    oled_send_cmd(0xAF); /* display on */
                    oled_send_cmd(0x81); oled_send_cmd(obr);
                }
            }
            /* Persist to NVS */
            nvs_handle_t h;
            if (nvs_open(NVS_NS_OLED, NVS_READWRITE, &h) == ESP_OK){
                nvs_set_u8(h, NVS_KEY_OLED_BR, obr);
                nvs_commit(h);
                nvs_close(h);
            }
            ESP_LOGI(TAG, "CTRL: OLED brightness set to %u", (unsigned)obr);
        }
    } else if (cmd[0]=='D' && cmd[1]=='L') {
        /* Display language: 'DL' + <uint8> (0=RU, 1=EN) */
        if (total >= 3){
            uint8_t lang = cmd[2] ? 1 : 0;
            g_display_lang = lang;
            nvs_handle_t h;
            if (nvs_open(NVS_NS_OLED, NVS_READWRITE, &h) == ESP_OK){
                nvs_set_u8(h, NVS_KEY_OLED_LANG, lang);
                nvs_commit(h);
                nvs_close(h);
            }
            ESP_LOGI(TAG, "CTRL: display lang set to %s", lang ? "EN" : "RU");
        }
    } else if (cmd[0]=='T' && cmd[1]=='W') {
        /* TW consumed but ignored: waiting flag is now derived locally in control_task */
    }
    return 0;
}

static int rpm_read_cb(uint16_t, uint16_t, struct ble_gatt_access_ctxt *ctxt, void *){
    struct {
        int32_t rpm1;
        int32_t rpm2;
        uint32_t flags;
    } __attribute__((packed)) pkt;
    pkt.rpm1 = g_rpm1; /* калиброванные */
    pkt.rpm2 = g_rpm2;
    pkt.flags = g_rpm_flags;
    int rc = os_mbuf_append(ctxt->om, &pkt, sizeof(pkt));
    return rc == 0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
}

static int water_read_cb(uint16_t, uint16_t, struct ble_gatt_access_ctxt *ctxt, void *){
    int32_t w = g_water_temp_c;
    int rc = os_mbuf_append(ctxt->om, &w, sizeof(w));
    return rc == 0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
}

static uint32_t g_hours_last_save_ms = 0;

/* Loop protection status read: returns 1 byte code
   0 = protection disabled, 1 = loop connected (ok), 2 = loop broken */
static int loop_stat_read_cb(uint16_t, uint16_t, struct ble_gatt_access_ctxt *ctxt, void *){
    uint8_t code = 0;
    if (g_loopprot_enabled) {
        code = g_loop_ok ? 1 : 2;
    } else {
        code = 0;
    }
    int rc = os_mbuf_append(ctxt->om, &code, sizeof(code));
    return rc == 0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
}

static int hours_access_cb(uint16_t, uint16_t, struct ble_gatt_access_ctxt *ctxt, void *){
    if (ctxt->op == BLE_GATT_ACCESS_OP_READ_CHR){
        int rc = os_mbuf_append(ctxt->om, &g_hours, sizeof(g_hours));
        return rc == 0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
    }
    if (ctxt->op == BLE_GATT_ACCESS_OP_WRITE_CHR){
        uint16_t total = OS_MBUF_PKTLEN(ctxt->om);
        if (total != sizeof(g_hours)) return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
        pump_hours_t tmp; uint32_t old_minutes = g_hours.total_minutes;
        os_mbuf_copydata(ctxt->om, 0, sizeof(tmp), &tmp);
        if (tmp.version != 1) return BLE_ATT_ERR_UNLIKELY;
        g_hours = tmp;
        /* Throttle NVS writes to reduce flash wear: save if minutes increased or >=60s since last save */
        uint32_t now_ms = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
        bool minutes_changed = (tmp.total_minutes != old_minutes);
        if (minutes_changed || (now_ms - g_hours_last_save_ms) >= 30000u){
            hours_save_to_nvs();
            g_hours_last_save_ms = now_ms;
        }
        return 0;
    }
    return BLE_ATT_ERR_UNLIKELY;
}

/* GATT service (RPM characteristic added) */
static const struct ble_gatt_svc_def gatt_svcs[] = {
    { .type=BLE_GATT_SVC_TYPE_PRIMARY, .uuid=BLE_UUID16_DECLARE(FAN_SERVICE_UUID),
      .characteristics=(struct ble_gatt_chr_def[]){
          { .uuid=BLE_UUID16_DECLARE(TEMP_CHAR_UUID),     .access_cb=temp_write_cb,     .flags=BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_NO_RSP },
          { .uuid=BLE_UUID16_DECLARE(FAN_CFG_CHAR_UUID),  .access_cb=fan_cfg_write_cb,  .flags=BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_NO_RSP },
          { .uuid=BLE_UUID16_DECLARE(LED_CHAR_UUID),      .access_cb=led_write_cb,      .flags=BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_NO_RSP },
          { .uuid=BLE_UUID16_DECLARE(PUMP_CFG_CHAR_UUID), .access_cb=pump_cfg_write_cb, .flags=BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_NO_RSP },
          { .uuid=BLE_UUID16_DECLARE(CTRL_CHAR_UUID),      .access_cb=ctrl_write_cb,     .flags=BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_NO_RSP },
          { .uuid=BLE_UUID16_DECLARE(RPM_CHAR_UUID),      .access_cb=rpm_read_cb,       .flags=BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_NOTIFY },
                      { .uuid=BLE_UUID16_DECLARE(HOURS_CHAR_UUID),    .access_cb=hours_access_cb,   .flags=BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_WRITE },
          { .uuid=BLE_UUID16_DECLARE(WATER_CHAR_UUID),    .access_cb=water_read_cb,     .flags=BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_NOTIFY },
              { .uuid=BLE_UUID16_DECLARE(LOOP_STAT_CHAR_UUID),.access_cb=loop_stat_read_cb, .flags=BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_NOTIFY },
          { 0 }
      }
    },
    { 0 }
};

static void gatt_register_cb(struct ble_gatt_register_ctxt *ctxt, void *){
    if (ctxt->op==BLE_GATT_REGISTER_OP_CHR){
        uint16_t u16=ble_uuid_u16(ctxt->chr.chr_def->uuid);
        if(u16==TEMP_CHAR_UUID)     g_temp_val_handle    =ctxt->chr.val_handle;
        if(u16==FAN_CFG_CHAR_UUID)  g_fan_cfg_val_handle =ctxt->chr.val_handle;
        if(u16==PUMP_CFG_CHAR_UUID) g_pump_cfg_val_handle=ctxt->chr.val_handle;
        if(u16==RPM_CHAR_UUID)      g_rpm_val_handle     =ctxt->chr.val_handle;
        /* HOURS_CHAR_UUID has no notify handle; nothing to store here */
        if(u16==WATER_CHAR_UUID)    g_water_val_handle   =ctxt->chr.val_handle;
        if(u16==LOOP_STAT_CHAR_UUID) g_loop_stat_val_handle = ctxt->chr.val_handle;
    }
}

/* GAP */
static int gap_event(struct ble_gap_event *event, void *){
    switch(event->type){
        case BLE_GAP_EVENT_CONNECT:
            ESP_LOGI(TAG,"Connect %s; status=%d", event->connect.status==0?"ok":"fail", event->connect.status);
            if (event->connect.status==0){
                g_conn_handle=event->connect.conn_handle; g_ble_connected=true; gpio_set_level(LED_GPIO,1);
                g_fan_last_filt=g_pump_last_filt=NAN; g_fan_last_appl=g_pump_last_appl=NAN;
                fan_pwm_set_percent(0.0f); pump_pwm_set_percent(0.0f);
                /* Default to STOP on every (re)connection; app will send ST/SP
                 * within ~200 ms to sync actual switch state, avoiding a
                 * 1-second parasitic fan/pump spin-up. */
                g_system_running = false;
                /* record connection start time for 10s post-connection grace and ПОДКЛЮЧАЮ animation */
                g_conn_start_ms = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
                g_ble_conn_since_ms = g_conn_start_ms;
                /* LED profile is loaded at boot only when keep-on is enabled */
            } else {
                struct ble_gap_adv_params advp={0}; advp.conn_mode=BLE_GAP_CONN_MODE_UND; advp.disc_mode=BLE_GAP_DISC_MODE_GEN;
                ble_gap_adv_start(own_addr_type,NULL,BLE_HS_FOREVER,&advp,gap_event,NULL);
            }
            return 0;
                case BLE_GAP_EVENT_DISCONNECT:
                        ESP_LOGI(TAG,"Disconnect; reason=%d", event->disconnect.reason);
                        g_conn_handle=0; g_ble_connected=false; gpio_set_level(LED_GPIO,0);
                        g_cpu_temp_c = -1000; g_gpu_temp_c = -1000;
                        g_fan_last_filt=g_pump_last_filt=NAN; g_fan_last_appl=g_pump_last_appl=0.0f;
                        /* clear connection start timestamps */
                        g_conn_start_ms = 0;
                        g_ble_conn_since_ms = 0;
                        /* Не обнулять вентиляторы/помпу если идёт продувка */
                        if (!g_purge_active) {
                            fan_pwm_set_percent(0.0f); pump_pwm_set_percent(0.0f);
                        } else {
                            ESP_LOGW(TAG, "BLE disconnect during purge – keeping PWM");
                        }
                                if (!g_ble_connected && !g_usb_connected && !g_led_allow_disconnected) {
                                    ESP_LOGI(TAG, "LED off due to BLE disconnect");
                                    leds_off();
                                }
                        { struct ble_gap_adv_params advp={0}; advp.conn_mode=BLE_GAP_CONN_MODE_UND; advp.disc_mode=BLE_GAP_DISC_MODE_GEN;
                            ble_gap_adv_start(own_addr_type,NULL,BLE_HS_FOREVER,&advp,gap_event,NULL); }
                        return 0;
        case BLE_GAP_EVENT_ADV_COMPLETE:
            ESP_LOGI(TAG,"Adv complete; reason=%d", event->adv_complete.reason);
            { struct ble_gap_adv_params advp={0}; advp.conn_mode=BLE_GAP_CONN_MODE_UND; advp.disc_mode=BLE_GAP_DISC_MODE_GEN;
              ble_gap_adv_start(own_addr_type,NULL,BLE_HS_FOREVER,&advp,gap_event,NULL); }
            return 0;
        default: return 0;
    }
}

static void start_advertising(void){
    struct ble_hs_adv_fields fields; memset(&fields,0,sizeof(fields));
    fields.flags=BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
    fields.tx_pwr_lvl_is_present=1; fields.tx_pwr_lvl=BLE_HS_ADV_TX_PWR_LVL_AUTO;
    const char *name=ble_svc_gap_device_name();
    fields.name=(uint8_t*)name; fields.name_len=(uint8_t)strlen(name); fields.name_is_complete=1;
    ble_uuid16_t svc_uuid=BLE_UUID16_INIT(FAN_SERVICE_UUID);
    fields.uuids16=&svc_uuid; fields.num_uuids16=1; fields.uuids16_is_complete=1;
    int rc=ble_gap_adv_set_fields(&fields);
    if (rc!=0){ ESP_LOGE(TAG,"ble_gap_adv_set_fields rc=%d",rc); return; }
    struct ble_gap_adv_params advp={0}; advp.conn_mode=BLE_GAP_CONN_MODE_UND; advp.disc_mode=BLE_GAP_DISC_MODE_GEN;
    rc=ble_gap_adv_start(own_addr_type,NULL,BLE_HS_FOREVER,&advp,gap_event,NULL);
    if (rc!=0) ESP_LOGE(TAG,"ble_gap_adv_start rc=%d",rc);
    else ESP_LOGI(TAG,"Advertising started (name=%s, UUID=0x%04X)", name, FAN_SERVICE_UUID);
}

static void on_reset(int reason){ ESP_LOGE(TAG,"BLE reset; reason=%d",reason); }

static void on_sync(void){
    int rc=ble_hs_util_ensure_addr(0); assert(rc==0);
    rc=ble_hs_id_infer_auto(0,&own_addr_type); assert(rc==0);
    uint8_t addr[6]={0}; ble_hs_id_copy_addr(own_addr_type,addr,NULL);
    ESP_LOGI(TAG,"BLE addr: %02x:%02x:%02x:%02x:%02x:%02x", addr[0],addr[1],addr[2],addr[3],addr[4],addr[5]);
    ble_svc_gap_device_name_set("PROEKT1");
    start_advertising();
}

static void host_task(void *){
    ESP_LOGI(TAG,"BLE Host task start");
    nimble_port_run();
    nimble_port_freertos_deinit();
}
#endif /* CONFIG_BT_NIMBLE_ENABLED */

/* ===== BLE init (supports Legacy VHCI) ===== */
#if CONFIG_BT_NIMBLE_ENABLED
static esp_err_t ble_stack_init_manual(void){
    esp_err_t e;

    ESP_LOGI(TAG, "BLE init start");
#if !CONFIG_BT_NIMBLE_LEGACY_VHCI_ENABLE
    /* Release Classic BT memory for BLE-only (skip under Legacy VHCI to avoid double-release warning) */
    e = esp_bt_controller_mem_release(ESP_BT_MODE_CLASSIC_BT);
    if (e != ESP_OK && e != ESP_ERR_INVALID_STATE) {
        ESP_LOGE(TAG, "mem_release(CLASSIC_BT) failed: %s", esp_err_to_name(e));
        return e;
    }
#endif

#if CONFIG_BT_NIMBLE_LEGACY_VHCI_ENABLE
    /* Legacy VHCI path: DO NOT init/enable controller or call esp_nimble_hci_init here.
       NimBLE will init/enable controller internally in nimble_port_init() for legacy transport. */
    ESP_LOGI(TAG, "Using Legacy VHCI: controller will be init/enabled by NimBLE");
    e = nimble_port_init(); /* IDF 5.x: returns esp_err_t */
    if (e != ESP_OK) {
        ESP_LOGE(TAG, "nimble_port_init rc=%d", (int)e);
        return e;
    }
    ESP_LOGI(TAG, "BLE init done (Legacy VHCI)");
    return ESP_OK;
#else
    /* Non-legacy VHCI path: init+enable controller, HCI init, then NimBLE host. */
    if (esp_bt_controller_get_status() == ESP_BT_CONTROLLER_STATUS_IDLE) {
        esp_bt_controller_config_t bt_cfg = BT_CONTROLLER_INIT_CONFIG_DEFAULT();
        e = esp_bt_controller_init(&bt_cfg);
        if (e != ESP_OK && e != ESP_ERR_INVALID_STATE) {
            ESP_LOGE(TAG, "bt_controller_init failed: %s", esp_err_to_name(e));
            return e;
        }
    }
    if (esp_bt_controller_get_status() != ESP_BT_CONTROLLER_STATUS_ENABLED) {
        e = esp_bt_controller_enable(ESP_BT_MODE_BLE);
        if (e != ESP_OK && e != ESP_ERR_INVALID_STATE) {
            ESP_LOGE(TAG, "bt_controller_enable(BLE) failed: %s", esp_err_to_name(e));
            return e;
        }
    }
    e = esp_nimble_hci_init();
    if (e != ESP_OK && e != ESP_ERR_INVALID_STATE) {
        ESP_LOGE(TAG, "esp_nimble_hci_init failed: %s", esp_err_to_name(e));
        return e;
    }
    e = nimble_port_init();
    if (e != ESP_OK) {
        ESP_LOGE(TAG, "nimble_port_init rc=%d", (int)e);
        return e;
    }
    ESP_LOGI(TAG, "BLE init done");
    return ESP_OK;
#endif
}
#endif /* CONFIG_BT_NIMBLE_ENABLED */

/* ===== UART parser (RX side: TT/FC/PC/LX) ===== */
typedef struct { uint8_t buf[4096]; size_t len; } stream_parser_t;

static void sp_init(stream_parser_t* p){ memset(p,0,sizeof(*p)); }
static void sp_consume(stream_parser_t* p, size_t n){ if(n>=p->len){ p->len=0; return; } memmove(p->buf,p->buf+n,p->len-n); p->len-=n; }

static inline bool uart_session_active(void){
    return g_usb_connected;
}

static int sp_try_tt(const uint8_t* d,size_t l,size_t* used){
    if (l < 10) return 0;
    if (!(d[0]=='T' && d[1]=='T')){ *used=1; return -1; }
    int32_t cpu=(int32_t)((uint32_t)d[2] | ((uint32_t)d[3]<<8) | ((uint32_t)d[4]<<16) | ((uint32_t)d[5]<<24));
    int32_t gpu=(int32_t)((uint32_t)d[6] | ((uint32_t)d[7]<<8) | ((uint32_t)d[8]<<16) | ((uint32_t)d[9]<<24));
    /* Reject noise: real temperatures are -100..250 °C; random 4-byte values
     * from UART line noise are almost never in this range. */
    if (cpu < -100 || cpu > 250 || gpu < -100 || gpu > 250) {
        *used = 10; return -1;
    }
    g_cpu_temp_c=cpu; g_gpu_temp_c=gpu;
    uint32_t now_ms = (uint32_t)(xTaskGetTickCount()*portTICK_PERIOD_MS);
    g_last_temp_ms = now_ms;
    if (!g_usb_connected) {
        /* first time USB appears — record connection start for 10s grace and ПОДКЛЮЧАЮ animation */
        g_conn_start_ms = now_ms;
        g_usb_conn_since_ms = now_ms;
        /* Default to STOP; app sends ST/SP to sync (parity with BLE) */
        g_system_running = false;
    }
    g_usb_connected = true;
    g_last_usb_ms = now_ms;
    *used=10; return 1;
}

static int sp_try_fc(const uint8_t* d,size_t l,size_t* used){
    if (l < 6) return 0;
    if (!(d[0]=='F' && d[1]=='C')){ *used=1; return -1; }
    uint8_t ver=d[2]; uint8_t n=d[5];
    size_t header = (ver==2)?7:6; size_t need=header + (size_t)n*3;
    if (n<2 || n>CURVE_POINTS_MAX){ *used=2; return -1; }
    if (l < need) return 0;
    if (!uart_session_active()){ *used=need; return 1; } /* discard if no USB session */
    (void)apply_fc_bytes(d,(uint16_t)need);
    *used=need; return 1;
}

static int sp_try_pc(const uint8_t* d,size_t l,size_t* used){
    if (l < 6) return 0;
    if (!(d[0]=='P' && d[1]=='C')){ *used=1; return -1; }
    uint8_t ver=d[2]; uint8_t n=d[5];
    size_t header = (ver==2)?7:6; size_t need=header + (size_t)n*3;
    if (n<2 || n>CURVE_POINTS_MAX){ *used=2; return -1; }
    if (l < need) return 0;
    if (!uart_session_active()){ *used=need; return 1; } /* discard if no USB session */
    (void)apply_pc_bytes(d,(uint16_t)need);
    *used=need; return 1;
}

static int sp_try_lx(const uint8_t* d,size_t l,size_t* used){
    if (l < 5) return 0;
    if (!(d[0]=='L' && d[1]=='X')){ *used=1; return -1; }
    /* Reject if no active USB session — prevents UART noise from setting LED profile */
    if (!uart_session_active()){
        /* Still consume the correct number of bytes to keep parser in sync */
        uint8_t mode = d[3];
        size_t consume = 5;
        if (mode == LED_MODE_CUSTOM) consume = 5 + (size_t)LED_STRIP_LENGTH * 3;
        else if (mode == LED_MODE_GRADIENT_ANIM) consume = 12;
        else if (l >= 8) consume = 8;
        if (l < consume) return 0; /* wait for full packet before discarding */
        *used = consume; return 1;
    }
    /* Determine expected length by mode */
    if (l >= 5){
        uint8_t mode = d[3];
        if (mode == LED_MODE_CUSTOM){
            size_t need = 5 + (size_t)LED_STRIP_LENGTH * 3;
            if (l < need) return 0;
            (void)apply_lx_bytes(d,(uint16_t)need);
            *used = need; return 1;
        }
        if (mode == LED_MODE_GRADIENT_ANIM){
            size_t need = 12;
            if (l < need) return 0;
            (void)apply_lx_bytes(d,(uint16_t)need);
            *used = need; return 1;
        }
        /* SOLID/OFF/BLINK/BREATHE: either 8 (with RGB) or compact 5 (brightness only) */
        if (l >= 8){
            (void)apply_lx_bytes(d,8);
            *used = 8; return 1;
        }
        /* brightness-only packet */
        (void)apply_lx_bytes(d,5);
        *used = 5; return 1;
    }
    return 0;
}

static int sp_try_pg(const uint8_t* d,size_t l,size_t* used){
    if (l < 2) return 0;
    if (!(d[0]=='P' && d[1]=='G')){ *used=1; return -1; }
    if (!uart_session_active()){
        *used = 2;
        ESP_LOGW(TAG, "UART: 'PG' ignored (no USB session)");
        return 1;
    }
    *used=2; g_purge_seen_since_last_stop = true; purge_start(); return 1;
}

static int sp_try_st(const uint8_t* d,size_t l,size_t* used){
    if (l < 2) return 0;
    if (!(d[0]=='S' && d[1]=='T')){ *used=1; return -1; }
    if (!uart_session_active()){
        *used = 2;
        ESP_LOGW(TAG, "UART: 'ST' ignored (no USB session)");
        return 1;
    }
    *used=2;
    /* IMPORTANT: heavy LEDC re-attach and boost start are deferred to control_task
     * to avoid stack overflow in the UART task context. */
    g_forced_stop_deadline_ms = 0;
    if (g_purge_active) purge_stop();
    g_fan_last_filt = NAN; g_pump_last_filt = NAN;
    g_fan_last_appl = NAN; g_pump_last_appl = 0.0f;
    g_start_pending = true; /* control_task will check NVS boost flag once */
    g_lp_restore_ms = 0;     /* clear rearm state — system is starting */
    g_system_running = true; /* set LAST so control_task sees consistent state */
    return 1;
}

static int sp_try_sp(const uint8_t* d,size_t l,size_t* used){
    if (l < 2) return 0;
    if (!(d[0]=='S' && d[1]=='P')){ *used=1; return -1; }
    if (!uart_session_active()){
        *used = 2;
        ESP_LOGW(TAG, "UART: 'SP' ignored (no USB session)");
        return 1;
    }
    *used=2;
    g_system_running = false;
    g_waiting_for_temps = false; /* clear waiting flag on stop */
    g_stop_pending = true;   /* control_task will kill LEDC/GPIO */
    /* Cancel any ongoing boost immediately */
    g_pump_boost_active = false;
    bool will_arm = (g_purge_completed_since_last_stop || g_purge_seen_since_last_stop);
    bool was_armed = g_pump_boost_armed;
    g_pump_boost_armed = was_armed || will_arm; /* keep armed across extra STOPs */
    if (g_pump_boost_armed){
        ESP_LOGI(TAG, "PUMP BOOST: armed (via SP) completed=%d seen=%d keep=%d", (int)g_purge_completed_since_last_stop, (int)g_purge_seen_since_last_stop, was_armed?1:0);
    }
    /* Consume purge flags regardless */
    g_purge_completed_since_last_stop = false;
    g_purge_seen_since_last_stop = false;
    if (g_purge_active) purge_stop(); /* cancel active purge on STOP */
    return 1;
}

/* NEW: LED keep-on flag over UART: 'LK' + ('1' or '0') */
static int sp_try_lk(const uint8_t* d,size_t l,size_t* used){
    if (l < 3) return 0;
    if (!(d[0]=='L' && d[1]=='K')){ *used=1; return -1; }
    if (!uart_session_active()){ *used=3; return 1; } /* discard if no USB session */
    bool new_flag = (d[2] != 0);
    g_led_allow_disconnected = new_flag;
    nvs_handle_t h; if (nvs_open(NVS_NS_LED, NVS_READWRITE, &h) == ESP_OK){
        (void)nvs_set_u8(h, "keep_on", new_flag?1:0);
        (void)nvs_commit(h); nvs_close(h);
    }
    ESP_LOGI(TAG, "UART: keep_on set to %d", (int)new_flag);
    if (new_flag) {
        if (g_led_prof.mode != LED_MODE_OFF) g_led_dirty = true;
    } else {
        if (!g_ble_connected && !g_usb_connected) leds_off();
    }
    *used = 3; return 1;
}

/* NEW: Hours over UART: 'HR' + op + [blob]
   op='R' -> read request, device replies with 'HR'<blob>
   op='W' -> write request with blob (throttled save)
   op='F' -> write request with blob, force immediate save */
/* NEW: Loop protection flag over UART: 'LP' + ('1' or '0') */
static int sp_try_lp(const uint8_t* d,size_t l,size_t* used){
    if (l < 3) return 0;
    if (!(d[0]=='L' && d[1]=='P')){ *used=1; return -1; }
    if (!uart_session_active()){ *used=3; return 1; } /* discard if no USB session */
    bool en = (d[2] != 0);
    g_loopprot_enabled = en;
    nvs_handle_t h; if (nvs_open("sys", NVS_READWRITE, &h) == ESP_OK){
        (void)nvs_set_u8(h, "loopprot", en?1:0);
        (void)nvs_commit(h); nvs_close(h);
    }
    ESP_LOGI(TAG, "UART: loop protection %s", en?"ENABLED":"DISABLED");
    *used = 3; return 1;
}
static int sp_try_hr(const uint8_t* d,size_t l,size_t* used){
    if (l < 3) return 0;
    if (!(d[0]=='H' && d[1]=='R')){ *used=1; return -1; }
    if (!uart_session_active()){ *used=2; return 1; } /* discard if no USB session */
    char op = (char)d[2];
    if (op=='R'){
        *used = 3; /* consume header only */
        uart_send_hr();
        return 1;
    }
    if (op=='W' || op=='F'){
        size_t need = 3 + sizeof(g_hours);
        if (l < need) return 0;
        pump_hours_t tmp; memcpy(&tmp, &d[3], sizeof(tmp));
        if (tmp.version != 1){ *used = need; return -1; }
        uint32_t old_minutes = g_hours.total_minutes;
        g_hours = tmp;
        uint32_t now_ms = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
        bool minutes_changed = (tmp.total_minutes != old_minutes);
        if (op=='F' || minutes_changed || (now_ms - g_hours_last_save_ms) >= 30000u){
            hours_save_to_nvs();
            g_hours_last_save_ms = now_ms;
        }
        *used = need; return 1;
    }
    *used = 2; return -1;
}

static void sp_feed(stream_parser_t* p,const uint8_t* data,size_t len){
    if(!len) return;
    size_t free=sizeof(p->buf)-p->len;
    if(len>free) sp_consume(p,len-free);
    memcpy(p->buf+p->len,data,len);
    p->len+=len;
    while(p->len){
        size_t used=0;
        if(p->len>=2 && p->buf[0]=='T' && p->buf[1]=='T'){ int r=sp_try_tt(p->buf,p->len,&used); if(r==0) break; sp_consume(p,used); continue; }
        if(p->len>=2 && p->buf[0]=='F' && p->buf[1]=='C'){ int r=sp_try_fc(p->buf,p->len,&used); if(r==0) break; sp_consume(p,used); continue; }
        if(p->len>=2 && p->buf[0]=='P' && p->buf[1]=='C'){ int r=sp_try_pc(p->buf,p->len,&used); if(r==0) break; sp_consume(p,used); continue; }
        if(p->len>=2 && p->buf[0]=='L' && p->buf[1]=='X'){ int r=sp_try_lx(p->buf,p->len,&used); if(r==0) break; sp_consume(p,used); continue; }
        if(p->len>=3 && p->buf[0]=='L' && p->buf[1]=='K'){ int r=sp_try_lk(p->buf,p->len,&used); if(r==0) break; sp_consume(p,used); continue; }
        if(p->len>=3 && p->buf[0]=='L' && p->buf[1]=='P'){ int r=sp_try_lp(p->buf,p->len,&used); if(r==0) break; sp_consume(p,used); continue; }
        if(p->len>=2 && p->buf[0]=='H' && p->buf[1]=='R'){ int r=sp_try_hr(p->buf,p->len,&used); if(r==0) break; sp_consume(p,used); continue; }
        if(p->len>=2 && p->buf[0]=='P' && p->buf[1]=='G'){ int r=sp_try_pg(p->buf,p->len,&used); if(r==0) break; sp_consume(p,used); continue; }
        if(p->len>=2 && p->buf[0]=='S' && p->buf[1]=='T'){ int r=sp_try_st(p->buf,p->len,&used); if(r==0) break; sp_consume(p,used); continue; }
        if(p->len>=2 && p->buf[0]=='S' && p->buf[1]=='P'){ int r=sp_try_sp(p->buf,p->len,&used); if(r==0) break; sp_consume(p,used); continue; }
    /* Удалили калибровку по UART ('VC'): больше не поддерживается */
        /* OLED brightness command 'OB' + <uint8>: sets display contrast 0..255 */
        if(p->len>=2 && p->buf[0]=='O' && p->buf[1]=='B'){
            if(p->len<3){ break; } /* wait for brightness byte */
            if (!uart_session_active()){ sp_consume(p, 3); continue; } /* discard if no USB session */
            uint8_t obr = p->buf[2];
            g_oled_brightness = obr;
            if (g_oled_inited){
                if (obr == 0){
                    oled_send_cmd(0xAE); /* display off */
                } else {
                    oled_send_cmd(0xAF); /* display on */
                    oled_send_cmd(0x81); oled_send_cmd(obr);
                }
            }
            /* Persist to NVS */
            nvs_handle_t h;
            if (nvs_open(NVS_NS_OLED, NVS_READWRITE, &h) == ESP_OK){
                nvs_set_u8(h, NVS_KEY_OLED_BR, obr);
                nvs_commit(h);
                nvs_close(h);
            }
            ESP_LOGI(TAG, "OLED: brightness set to %u", (unsigned)obr);
            sp_consume(p, 3); continue;
        }
        /* Display language command 'DL' + <uint8>: 0=RU, 1=EN */
        if(p->len>=2 && p->buf[0]=='D' && p->buf[1]=='L'){
            if(p->len<3){ break; } /* wait for language byte */
            if (!uart_session_active()){ sp_consume(p, 3); continue; } /* discard if no USB session */
            uint8_t lang = p->buf[2] ? 1 : 0;
            g_display_lang = lang;
            nvs_handle_t h;
            if (nvs_open(NVS_NS_OLED, NVS_READWRITE, &h) == ESP_OK){
                nvs_set_u8(h, NVS_KEY_OLED_LANG, lang);
                nvs_commit(h);
                nvs_close(h);
            }
            ESP_LOGI(TAG, "OLED: lang set to %s", lang ? "EN" : "RU");
            sp_consume(p, 3); continue;
        }
        /* TW consumed but ignored: waiting flag is now derived locally in control_task */
        if(p->len>=2 && p->buf[0]=='T' && p->buf[1]=='W'){
            if(p->len<3){ break; }
            sp_consume(p, 3); continue;
        }
        /* OLED diagnostic trigger 'OD': toggles contrast/precharge set B and runs a pattern */
        if(p->len>=2 && p->buf[0]=='O' && p->buf[1]=='D'){ size_t u=2; /* consume */ 
            if (!uart_session_active()){ sp_consume(p,u); continue; } /* discard if no USB session */
            sp_consume(p,u);
            if (g_oled_inited){
                /* Bump contrast & precharge and draw checkerboard */
                oled_send_cmd(0x81); oled_send_cmd(0xFF);
                oled_send_cmd(0xD9); oled_send_cmd(0xF1);
                oled_send_cmd(0xDB); oled_send_cmd(0x40);
                for (int y=0;y<OLED_HEIGHT;y++){
                    for (int x=0;x<OLED_WIDTH;x++){
                        bool on = ((x>>3)&1) ^ ((y>>3)&1);
                        oled_fb_set_pixel(x,y,on);
                    }
                }
                oled_flush();
            }
            continue; }
        sp_consume(p,1);
    }
}

static void uart_rx_task(void*){
    stream_parser_t* sp=(stream_parser_t*)calloc(1,sizeof(stream_parser_t));
    if(!sp){ ESP_LOGE(TAG,"No mem for parser"); vTaskDelete(NULL); return; }
    sp_init(sp);
    uint8_t* rx=(uint8_t*)malloc(1024);
    if(!rx){ ESP_LOGE(TAG,"No mem for UART RX"); free(sp); vTaskDelete(NULL); return; }
    for(;;){
        int n=uart_read_bytes(UART_PORT,rx,1024,pdMS_TO_TICKS(20));
        if(n>0) sp_feed(sp,rx,(size_t)n);
        else vTaskDelay(pdMS_TO_TICKS(10));
    }
}

static void uart_init(void){
    uart_config_t cfg={
        .baud_rate=UART_BAUD, .data_bits=UART_DATA_8_BITS, .parity=UART_PARITY_DISABLE,
        .stop_bits=UART_STOP_BITS_1, .flow_ctrl=UART_HW_FLOWCTRL_DISABLE,
#if ESP_IDF_VERSION_MAJOR >= 5
        .source_clk=UART_SCLK_DEFAULT,
#endif
    };
    esp_err_t _ue = uart_driver_install(UART_PORT,UART_RX_BUF_HW,UART_TX_BUF_HW,0,NULL,0);
    if (_ue != ESP_OK) { ESP_LOGE(TAG,"uart_driver_install failed: %s",esp_err_to_name(_ue)); g_err_uart_hw = true; return; }
    _ue = uart_param_config(UART_PORT,&cfg);
    if (_ue != ESP_OK) { ESP_LOGE(TAG,"uart_param_config failed: %s",esp_err_to_name(_ue)); g_err_uart_hw = true; return; }
    /* Flush any garbage in RX FIFO left over from boot-ROM log at 74880 baud;
     * without this, garbled bytes could momentarily match 'TT' and set g_usb_connected=true */
    uart_flush_input(UART_PORT);
    xTaskCreate(uart_rx_task,"usb_uart_rx",UART_TASK_STACK,NULL,UART_TASK_PRIO,NULL);
}

/* ===== Control loop (with tach sampling) ===== */
static void control_task(void *){
#if FAN_PWM_SELFTEST
    fan_pwm_set_percent(20.0f); pump_pwm_set_percent(20.0f); vTaskDelay(pdMS_TO_TICKS(1500));
    fan_pwm_set_percent(60.0f); pump_pwm_set_percent(60.0f); vTaskDelay(pdMS_TO_TICKS(1500));
    fan_pwm_set_percent(0.0f);  pump_pwm_set_percent(0.0f);
#endif
    const float dt=CTRL_PERIOD_MS/1000.0f; uint32_t last_dbg=0;
    uint32_t tach_accum = 0;

    for(;;){
        uint32_t now=(uint32_t)(xTaskGetTickCount()*portTICK_PERIOD_MS);
        if (g_usb_connected && (now - g_last_usb_ms > 5000)) {
            g_usb_connected = false;
            g_conn_start_ms = 0; /* clear post-connection timer on USB disconnect */
            g_usb_conn_since_ms = 0;
            g_cpu_temp_c = -1000; g_gpu_temp_c = -1000;
            ESP_LOGI(TAG, "CTRL: USB timeout - disconnected");
            if (!g_ble_connected && !g_usb_connected && !g_led_allow_disconnected) {
                ESP_LOGI(TAG, "LED off due to USB timeout");
                leds_off();
            }
        }
    bool fresh=(g_last_temp_ms!=0) && (now-g_last_temp_ms<=STALE_MS);
        if (g_calibrating) {
            /* During calibration we don't interfere with PWM */
            vTaskDelay(pdMS_TO_TICKS(CTRL_PERIOD_MS));
            tach_accum += CTRL_PERIOD_MS;
            if (tach_accum >= 1000){ tach_accum = 0; }
            continue;
        }
        /* During purge sequence, control is overridden by purge task */
        if (g_purge_active) {
            vTaskDelay(pdMS_TO_TICKS(CTRL_PERIOD_MS));
            tach_accum += CTRL_PERIOD_MS;
            if (tach_accum >= 1000){ tach_accum = 0; tach_sample_and_publish(1000); }
            continue;
        }

        /* === Deferred STOP (heavy HW ops moved out of BLE/UART/loopprot contexts) ===
         * SP/break handlers only set g_system_running=false + g_stop_pending=true;
         * actual LEDC stop + GPIO pin-down happen here in control_task with ample stack. */
        if (g_stop_pending) {
            g_stop_pending = false;
            fan_pwm_set_percent(0.0f);
            pump_pwm_set_percent(0.0f);
            (void)ledc_stop(LEDC_HIGH_SPEED_MODE, LEDC_CHANNEL_0, 0);
            (void)ledc_stop(LEDC_HIGH_SPEED_MODE, LEDC_CHANNEL_1, 0);
            gpio_set_direction((gpio_num_t)FAN_PWM_GPIO, GPIO_MODE_OUTPUT);
            gpio_set_level((gpio_num_t)FAN_PWM_GPIO, 0);
            gpio_set_direction((gpio_num_t)PUMP_PWM_GPIO, GPIO_MODE_OUTPUT);
            gpio_set_level((gpio_num_t)PUMP_PWM_GPIO, 0);
            g_pwm_fan_attached = false;
            g_pwm_pump_attached = false;
            g_forced_stop_deadline_ms = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS) + 1500u;
            g_pump_boost_active = false;
            ESP_LOGI(TAG, "CTRL: deferred STOP executed");
        }

        /* === Deferred LEDC re-attach (moved out of BLE/UART callbacks) ===
         * Re-attach channels safely from this dedicated task context, avoiding
         * stack overflow and para_up hang in the NimBLE / UART task. */
        if (g_system_running && !g_pwm_fan_attached){
            safe_ledc_attach_fan();
            ESP_LOGI(TAG, "CTRL: fan channel re-attached");
        }
        if (g_system_running && !g_pwm_pump_attached){
            safe_ledc_attach_pump();
            ESP_LOGI(TAG, "CTRL: pump channel re-attached");
        }
        /* NOTE: boost arming from g_purge_completed_since_last_stop is handled
         * exclusively in SP / ST command handlers to guarantee the STOP→START
         * sequence.  control_task only checks the NVS persisted flag once,
         * right after an ST command (g_start_pending). */
        if (g_start_pending && g_system_running){
            g_start_pending = false;
            /* One-shot NVS check: arm boost from persisted flag (survives reboot between purge and ST) */
            if (!g_pump_boost_armed && !g_pump_boost_active){
                if (boost_flag_take_pending()){
                    g_pump_boost_armed = true;
                    ESP_LOGI(TAG, "PUMP BOOST: armed (NVS flag on ST)");
                }
            }
        }
        /* Deferred boost start: compute target and activate */
        if (g_system_running && g_pump_boost_armed && g_pwm_pump_attached){
            float tgt = 100.0f;
            float tC_pump = pick_source_temp(g_pump.source_mode);
            if (!isnan(tC_pump)){
                tC_pump = clampf(tC_pump, TEMP_MIN_C, TEMP_MAX_C);
                float raw = eval_curve(&g_pump, tC_pump, false);
                tgt = clampf(raw, 0.0f, 100.0f);
            }
            g_pump_boost_target = tgt;
            g_pump_boost_start_ms = now;
            g_pump_boost_active = true;
            g_pump_boost_armed = false;
            pump_pwm_set_percent(0.0f); g_pump_last_appl = 0.0f; g_pump_last_filt = 0.0f;
            ESP_LOGI(TAG, "PUMP BOOST: start (deferred target=%.1f%%)", (double)tgt);
        }

        /* If pump boost is active, run it regardless of temp freshness */
        if (g_system_running && g_pump_boost_active){
            uint32_t elapsed = now - g_pump_boost_start_ms;
            float out = 0.0f;
            if (elapsed < PUMP_BOOST_PHASE1_MS){
                out = 100.0f * ((float)elapsed / (float)PUMP_BOOST_PHASE1_MS);
            } else if (elapsed < (PUMP_BOOST_PHASE1_MS + PUMP_BOOST_HOLD_MS)){
                /* Hold at 100% */
                out = 100.0f;
            } else {
                uint32_t e2 = elapsed - (PUMP_BOOST_PHASE1_MS + PUMP_BOOST_HOLD_MS);
                if (g_pump_boost_target >= 99.5f){
                    out = 100.0f;
                    if (e2 >= PUMP_BOOST_PHASE2_MS){ g_pump_boost_active = false; }
                } else {
                    if (e2 < PUMP_BOOST_PHASE2_MS){
                        float frac = (float)e2 / (float)PUMP_BOOST_PHASE2_MS;
                        out = 100.0f + (g_pump_boost_target - 100.0f) * frac;
                    } else {
                        out = g_pump_boost_target; g_pump_boost_active = false;
                    }
                }
            }
            out = clampf(out, 0.0f, 100.0f);
            pump_pwm_set_percent(out);
            g_pump_last_appl = out;
            if (!g_pump_boost_active){ g_pump_last_filt = g_pump_last_appl; }
            /* Proceed with fan control and skip normal pump logic this tick */
            /* Fan logic still runs below in fresh/stop branches */
        }
        if(!fresh){
            if (g_pump_boost_active){
                /* Temps are stale but boost is running: keep fan at 0%, don't override pump */
                if (isnan(g_fan_last_appl) || g_fan_last_appl!=0.0f){
                    g_fan_last_appl = 0.0f; g_fan_last_filt = 0.0f; fan_pwm_set_percent(0.0f);
                }
                if (now-last_dbg>2000){ ESP_LOGI(TAG,"CTRL: temps stale; pump boost active"); last_dbg=now; }
            } else {
                if(isnan(g_fan_last_appl) || g_fan_last_appl!=0.0f || isnan(g_pump_last_appl) || g_pump_last_appl!=0.0f){
                    g_fan_last_appl=g_pump_last_appl=0.0f; g_fan_last_filt=g_pump_last_filt=0.0f;
                    fan_pwm_set_percent(0.0f); pump_pwm_set_percent(0.0f);
                    ESP_LOGI(TAG,"CTRL: no fresh temps - out=0%%");
                } else if (now-last_dbg>2000){ ESP_LOGI(TAG,"CTRL: waiting temps (BLE/USB)"); last_dbg=now; }
            }
        } else if (!g_system_running) {
            /* Forced stop: keep outputs at 0% until 'ST' */
            if (isnan(g_fan_last_appl) || g_fan_last_appl!=0.0f || isnan(g_pump_last_appl) || g_pump_last_appl!=0.0f){
                g_fan_last_appl = g_pump_last_appl = 0.0f;
                g_fan_last_filt = g_pump_last_filt = 0.0f;
                fan_pwm_set_percent(0.0f); pump_pwm_set_percent(0.0f);
                ESP_LOGI(TAG, "CTRL: STOP active - out=0%%");
            }
        } else {
            float tC_fan=pick_source_temp(g_fan.source_mode);
            float tC_pump=pick_source_temp(g_pump.source_mode);
            if(!isnan(tC_fan)){
                tC_fan=clampf(tC_fan,TEMP_MIN_C,TEMP_MAX_C);
                float raw_fan=eval_curve(&g_fan,tC_fan,true);
                g_fan_last_filt=lp_update(g_fan_last_filt,raw_fan,g_fan.rc_tau_sec,dt);
                if(isnan(g_fan_last_appl) || fabsf(g_fan_last_filt-g_fan_last_appl)>=g_fan.hyst_pct){
                    g_fan_last_appl=g_fan_last_filt; fan_pwm_set_percent(g_fan_last_appl);
                }
            }
            if (g_pump_boost_active){
                uint32_t elapsed = now - g_pump_boost_start_ms;
                float out = 0.0f;
                if (elapsed < PUMP_BOOST_PHASE1_MS){
                    out = 100.0f * ((float)elapsed / (float)PUMP_BOOST_PHASE1_MS);
                } else if (elapsed < (PUMP_BOOST_PHASE1_MS + PUMP_BOOST_HOLD_MS)){
                    out = 100.0f; /* hold phase */
                } else {
                    uint32_t e2 = elapsed - (PUMP_BOOST_PHASE1_MS + PUMP_BOOST_HOLD_MS);
                    if (g_pump_boost_target >= 99.5f){
                        out = 100.0f;
                        if (e2 >= PUMP_BOOST_PHASE2_MS){
                            g_pump_boost_active = false; ESP_LOGI(TAG, "PUMP BOOST: done (100%%)");
                        }
                    } else if (e2 < PUMP_BOOST_PHASE2_MS){
                        float frac = (float)e2 / (float)PUMP_BOOST_PHASE2_MS;
                        out = 100.0f + (g_pump_boost_target - 100.0f) * frac;
                    } else {
                        out = g_pump_boost_target;
                        g_pump_boost_active = false; ESP_LOGI(TAG, "PUMP BOOST: done (target=%.1f%%)", (double)g_pump_boost_target);
                    }
                }
                out = clampf(out, 0.0f, 100.0f);
                pump_pwm_set_percent(out);
                g_pump_last_appl = out;
                if (!g_pump_boost_active){ g_pump_last_filt = g_pump_last_appl; }
            } else if(!isnan(tC_pump)){
                tC_pump=clampf(tC_pump,TEMP_MIN_C,TEMP_MAX_C);
                float raw_pump=eval_curve(&g_pump,tC_pump,false);
                g_pump_last_filt=lp_update(g_pump_last_filt,raw_pump,g_pump.rc_tau_sec,dt);
                if(isnan(g_pump_last_appl) || fabsf(g_pump_last_filt-g_pump_last_appl)>=g_pump.hyst_pct){
                    g_pump_last_appl=g_pump_last_filt; pump_pwm_set_percent(g_pump_last_appl);
                }
            }
            if(now-last_dbg>1000){
                ESP_LOGI(TAG,"CTRL: fan=%.1f%% pump=%.1f%%", g_fan_last_appl,g_pump_last_appl);
                last_dbg=now;
            }
        }

        /* Derive waiting-for-temps flag from actual outputs:
         * both fan and pump at 0% while system is running → temperatures
         * have not yet reached the first curve point. */
        if (g_system_running && !g_pump_boost_active) {
            bool fan_zero  = !isnan(g_fan_last_appl)  && g_fan_last_appl  <= 0.001f;
            bool pump_zero = !isnan(g_pump_last_appl) && g_pump_last_appl <= 0.001f;
            g_waiting_for_temps = fan_zero && pump_zero;
        } else {
            g_waiting_for_temps = false;
        }

        /* Tach sampling each ~1000 ms */
        tach_accum += CTRL_PERIOD_MS;
        if (tach_accum >= 1000){
            tach_sample_and_publish(tach_accum);
            tach_accum = 0;
        }

        vTaskDelay(pdMS_TO_TICKS(CTRL_PERIOD_MS));
    }
}

/* ===== LED Task ===== */
static void led_task(void *){
    const float breathe_period=2.5f, blink_period=0.8f;
    const TickType_t step_ticks=pdMS_TO_TICKS(80);
    leds_init();
    /* Only mark dirty if keep-on is active and profile has something to show;
     * otherwise profile is defaults (OFF) and there is nothing to apply. */
    if (g_led_allow_disconnected && g_led_prof.mode != LED_MODE_OFF) g_led_dirty = true;
    TickType_t start=xTaskGetTickCount();
    uint32_t last_init_ms = 0;
    uint32_t last_delete_warn_ms = 0;
    bool led_is_off = false;
    for(;;){
        /* Включаем/обновляем подсветку только при активной сессии или если разрешено без подключения */
        uint32_t now_ms = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
        bool any_conn = (g_ble_connected || g_usb_connected);
        if (!any_conn && !g_led_allow_disconnected) {
            /* Force profile OFF so no stale animation plays later */
            if (g_led_prof.mode != LED_MODE_OFF) {
                g_led_prof.mode = LED_MODE_OFF;
                g_led_prof.brightness = 0;
            }
            g_led_dirty = false; /* nothing to apply */
            /* Handle stuck g_led_need_reinit: delete strip to stop any RMT output */
            if (g_led_need_reinit && g_led_strip) {
                if (g_led_mtx) xSemaphoreTake(g_led_mtx, portMAX_DELAY);
                esp_err_t derr = led_strip_del(g_led_strip);
                if (derr == ESP_OK) {
                    g_led_strip = NULL;
                    g_led_need_reinit = false;
                    g_led_refresh_errs = 0;
                    g_led_invalid_state_cnt = 0;
                    esp_log_level_set("rmt", ESP_LOG_ERROR);
                    esp_log_level_set("led_strip_rmt", ESP_LOG_ERROR);
                    last_init_ms = now_ms;
                } else if ((now_ms - last_delete_warn_ms) >= 1000) {
                    ESP_LOGW(TAG, "LED strip delete deferred: %s", esp_err_to_name(derr));
                    last_delete_warn_ms = now_ms;
                }
                if (g_led_mtx) xSemaphoreGive(g_led_mtx);
            }
            if (!led_is_off) {
                /* If strip was deleted (or never inited), re-create it to send
                 * actual zeros to the WS2812 — otherwise noise-latched colours
                 * persist on the physical LEDs even though software thinks they're off. */
                if (g_led_strip == NULL) {
                    if ((now_ms - last_init_ms) >= 200) { leds_init(); last_init_ms = now_ms; }
                    if (g_led_strip == NULL) {
                        /* init still failed — mark off to stop retrying every 80 ms */
                        led_is_off = true;
                    } else if (leds_off()) {
                        led_is_off = true;
                    }
                } else if (leds_off()) {
                    led_is_off = true;
                }
            }
            vTaskDelay(step_ticks);
            continue;
        }
        if (led_is_off) led_is_off = false;
        if (!g_led_strip) {
            if ((now_ms - last_init_ms) >= 200) { leds_init(); last_init_ms = now_ms; }
        }
        /* Handle safe reinit request (delete when not busy, then re-init after cooldown) */
        if (g_led_need_reinit && g_led_strip) {
            if (g_led_mtx) xSemaphoreTake(g_led_mtx, portMAX_DELAY);
            /* Try to delete with small retries to allow RMT to become idle */
            esp_err_t derr = ESP_FAIL;
            for (int tries=0; tries<5; ++tries){
                derr = led_strip_del(g_led_strip);
                if (derr == ESP_OK){
                    g_led_strip = NULL;
                    break;
                }
                vTaskDelay(pdMS_TO_TICKS(10));
            }
            if (g_led_strip == NULL) {
                g_led_need_reinit = false;
                g_led_refresh_errs = 0;
                g_led_invalid_state_cnt = 0;
                /* Restore RMT log levels that were suppressed during error storm */
                esp_log_level_set("rmt", ESP_LOG_ERROR);
                esp_log_level_set("led_strip_rmt", ESP_LOG_ERROR);
                g_led_dirty = true;
                start = xTaskGetTickCount();
                /* Start cooldown before attempting leds_init again */
                last_init_ms = now_ms;
            } else if ((now_ms - last_delete_warn_ms) >= 1000) {
                ESP_LOGW(TAG, "LED strip delete deferred after retries: %s", esp_err_to_name(derr));
                last_delete_warn_ms = now_ms;
            }
            if (g_led_mtx) xSemaphoreGive(g_led_mtx);
        }
        bool just_applied = false;
        if(g_led_dirty){
            g_led_dirty=false;
            if(g_led_prof.mode==LED_MODE_OFF) (void)leds_off();
            else if(g_led_prof.mode==LED_MODE_SOLID) leds_apply_solid(g_led_prof.r,g_led_prof.g,g_led_prof.b,g_led_prof.brightness);
            else if(g_led_prof.mode==LED_MODE_CUSTOM) leds_apply_custom();
            /* Gradient anim first frame handled in loop below; mark anim start by resetting start tick */
            start=xTaskGetTickCount();
            just_applied = true;
        }
        if (just_applied) {
            /* Avoid multiple refreshes in the same tick after profile update */
            vTaskDelay(step_ticks);
            continue;
        }
        /* Snapshot profile under mutex to avoid torn reads while animation runs */
        led_mode_t mode; uint8_t anim_speed=0; uint8_t start_r=0,start_g=0,start_b=0,end_r=0,end_g=0,end_b=0; uint8_t brightness=0;
        if (g_led_mtx) xSemaphoreTake(g_led_mtx, portMAX_DELAY);
        mode = (led_mode_t)g_led_prof.mode;
        anim_speed = g_led_prof.anim_speed;
        start_r = g_led_prof.start_r; start_g = g_led_prof.start_g; start_b = g_led_prof.start_b;
        end_r = g_led_prof.end_r; end_g = g_led_prof.end_g; end_b = g_led_prof.end_b;
        brightness = g_led_prof.brightness;
        if (g_led_mtx) xSemaphoreGive(g_led_mtx);
        TickType_t now=xTaskGetTickCount();
        float elapsed=(float)(now-start)/(float)configTICK_RATE_HZ;
        if(mode==LED_MODE_BLINK){
            float phase=fmodf(elapsed,blink_period);
            bool on=(phase<(blink_period*0.5f));
            uint8_t br=on?brightness:0;
            leds_apply_solid(start_r,start_g,start_b,br);
        } else if(mode==LED_MODE_BREATHE){
            float s=0.5f*(1.0f + sinf(2.0f*(float)M_PI*(elapsed/breathe_period)));
            int low=(int)(0.15f*(float)brightness);
            int br=low + (int)lroundf(s*(float)(brightness-low));
            leds_apply_solid(start_r,start_g,start_b,clampu8(br));
        } else if(mode==LED_MODE_GRADIENT_ANIM){
            if (anim_speed > 0) {
                float t = fmodf(elapsed * anim_speed / 5.0f, 1.0f);
                if (g_led_strip) {
                    if (g_led_need_reinit) { vTaskDelay(step_ticks); continue; }
                    if (g_led_mtx && xSemaphoreTake(g_led_mtx, pdMS_TO_TICKS(5)) != pdTRUE) {
                        vTaskDelay(step_ticks);
                        continue;
                    }
                    /* Build frame: moving wave highlight from base(start) to peak(end) */
                    const float radius = 6.0f; /* 5-6 pixels on each side */
                    float center = t * (float)(LED_STRIP_LENGTH);
                    for(int i=0; i<LED_STRIP_LENGTH; i++){
                        float d = fabsf((float)i - center);
                        if (d > (float)LED_STRIP_LENGTH) d = fmodf(d, (float)LED_STRIP_LENGTH);
                        float wrap = (float)LED_STRIP_LENGTH - d;
                        if (wrap < d) d = wrap;
                        float k = 0.0f;
                        if (d <= radius) {
                            k = 1.0f - (d / radius);
                            /* smoothstep */
                            k = k * k * (3.0f - 2.0f * k);
                        }
                        float rf = (float)start_r + ((float)end_r - (float)start_r) * k;
                        float gf = (float)start_g + ((float)end_g - (float)start_g) * k;
                        float bf = (float)start_b + ((float)end_b - (float)start_b) * k;
                        uint8_t r = (uint8_t)clampf(rf, 0.0f, 255.0f);
                        uint8_t g = (uint8_t)clampf(gf, 0.0f, 255.0f);
                        uint8_t b = (uint8_t)clampf(bf, 0.0f, 255.0f);
                        uint8_t br = scale_bright(r, brightness);
                        uint8_t bg = scale_bright(g, brightness);
                        uint8_t bb = scale_bright(b, brightness);
                        (void)led_strip_set_pixel(g_led_strip, i, br, bg, bb);
                    }
                    esp_err_t err = led_refresh_safe();
                    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
                        ESP_LOGE(TAG, "led_strip_refresh(gradient) failed: %d (schedule safe reinit)", err);
                    }
                    led_note_refresh_result(err);
#if LED_FRAME_DUPLICATE
                    if (err == ESP_OK) {
                        vTaskDelay(pdMS_TO_TICKS(2));
                        esp_err_t err2 = led_refresh_safe();
                        if (err2 != ESP_OK && err2 != ESP_ERR_INVALID_STATE) {
                            ESP_LOGW(TAG, "led_strip_refresh(gradient) duplicate failed: %d", err2);
                        }
                        led_note_refresh_result(err2);
                    }
#endif
                    if (g_led_mtx) xSemaphoreGive(g_led_mtx);
                }
            }
        }
        vTaskDelay(step_ticks);
    }
}

/* ===== Purge (air flush) sequence ===== */
/* Forward decl for valve helpers used in purge */
static inline void valve_init(void);
static inline void valve_set(bool active);
static void valve_pwm_init(void);
static void valve_pwm_set_percent(float pct);
static void purge_task(void *arg){
    (void)arg;
    g_purge_active = true; g_purge_cancel = false;
    ESP_LOGI(TAG, "ПРОДУВКА: старт");
    /* Clear forced-stop guard so valve/pump PWM is not blocked during purge */
    g_forced_stop_deadline_ms = 0;
    /* Step 0: immediately stop fans and pumps */
    fan_pwm_set_percent(0.0f);
    pump_pwm_set_percent(0.0f);
    /* Always force re-attach pump (and fan if needed) to guarantee clean LEDC
     * timer+channel HW state — avoids para_up de-sync after fresh boot. */
    if (!g_pwm_fan_attached)  safe_ledc_attach_fan();
    g_pwm_pump_attached = false;
    safe_ledc_attach_pump();
    /* Start valve PWM ramp in parallel with OFF-phase */
    valve_pwm_init();
    ESP_LOGI(TAG, "ПРОДУВКА: valve=%d pump=%d fan=%d", (int)g_pwm_valve_attached, (int)g_pwm_pump_attached, (int)g_pwm_fan_attached);
    uint32_t start_ms = (uint32_t)(xTaskGetTickCount()*portTICK_PERIOD_MS);
    const uint32_t ramp_ms = 3000;             /* 3s smooth close */
    const uint32_t off_ms = 1000;              /* OFF-phase (fans/pump off) */
    const uint32_t air_pause_ms = 1000;        /* Air pause with pump OFF */
    /* Pump profile: 2s ramp 40->100%, 5s hold 100%, 1s ramp down to 40%, then OFF */
    const uint32_t pump_ramp_up_ms   = 1000;  /* 1s ramp 40->100 */
    const uint32_t pump_hold_ms      = 7000;  /* 7s hold */
    const uint32_t pump_ramp_down_ms = 1000;
    const uint32_t pump_total_ms     = pump_ramp_up_ms + pump_hold_ms + pump_ramp_down_ms; /* 8000 */
    const uint32_t pump_start_ms = start_ms + off_ms + air_pause_ms;
    const uint32_t purge_end_ms  = pump_start_ms + pump_total_ms;
    bool peak_logged = false;

    const TickType_t step_ticks = pdMS_TO_TICKS(10); /* finer step for acoustics */
    while (!g_purge_cancel){
        uint32_t now_ms = (uint32_t)(xTaskGetTickCount()*portTICK_PERIOD_MS);
        uint32_t elapsed = now_ms - start_ms;

        /* No display indicator here — ramp (НАПОЛНЯЮ) is shown during pump boost after purge */

        /* Valve PWM ramp: 40% -> 100% over ramp_ms, then hold 100% */
        if (elapsed < ramp_ms){
            float frac = (float)elapsed / (float)ramp_ms;
            float v_pct = 40.0f + (60.0f * frac);
            valve_pwm_set_percent(v_pct);
        } else {
            valve_pwm_set_percent(100.0f);
        }

        /* Pump control timeline with smooth profile */
        if (now_ms < pump_start_ms){
            /* OFF-phase (1s) and then air pause (1s) with pump OFF */
            pump_pwm_set_percent(0.0f);
        } else if (now_ms < purge_end_ms){
            uint32_t pt = now_ms - pump_start_ms;
            if (!peak_logged && pt >= pump_ramp_up_ms){
                peak_logged = true;
                ESP_LOGI(TAG, "ПРОДУВКА: пик оборотов помпы");
            }
            if (pt < pump_ramp_up_ms){
                float frac = (float)pt / (float)pump_ramp_up_ms;          /* 0..1 */
                float pct  = 40.0f + 60.0f * frac;                         /* 40 -> 100 */
                pump_pwm_set_percent(pct);
            } else if (pt < pump_ramp_up_ms + pump_hold_ms){
                pump_pwm_set_percent(100.0f);                              /* hold */
            } else {
                uint32_t dt = pt - (pump_ramp_up_ms + pump_hold_ms);
                float frac = (float)dt / (float)pump_ramp_down_ms;         /* 0..1 */
                if (frac > 1.0f) frac = 1.0f;
                float pct  = 100.0f - 60.0f * frac;                        /* 100 -> 40 */
                pump_pwm_set_percent(pct);
            }
        } else {
            break; /* timeline finished */
        }

        vTaskDelay(step_ticks);
        if (g_purge_cancel){
            pump_pwm_set_percent(0.0f);
            valve_pwm_set_percent(0.0f);
            break;
        }
    }

    /* Stop pumps and deactivate valve */
    pump_pwm_set_percent(0.0f);
    valve_pwm_set_percent(0.0f);

    /* ramp indicator not set here */

    g_purge_active = false;
    /* Mark that purge has completed.  Boost arming happens ONLY when
     * the system transitions through STOP → START (SP then ST commands).
     * We set the flag here; the SP handler will pick it up and arm boost,
     * which will fire on the subsequent ST.  No immediate start — purge
     * is meant to empty the lines and stay idle. */
    g_purge_completed_since_last_stop = true;
    /* Persist so boost survives power loss between purge and next start */
    boost_flag_set_pending(true);
    ESP_LOGI(TAG, "ПРОДУВКА: завершено%s (system_running=%d boost_armed=%d)", g_purge_cancel?" (отменено)":"", (int)g_system_running, (int)g_pump_boost_armed);
    g_purge_cancel = false;
    g_purge_task = NULL;
    vTaskDelete(NULL);
}

static void purge_start(void){
    if (g_purge_active){ ESP_LOGW(TAG, "PURGE: already active"); return; }
    if (g_purge_task){ ESP_LOGW(TAG, "PURGE: task handle set"); return; }
    if (g_loopprot_enabled && !g_loop_ok){ ESP_LOGW(TAG, "LOOP: broken, purge denied"); return; }
    /* Cancel any pending/active pump boost when starting purge */
    g_pump_boost_active = false;
    g_pump_boost_armed = false;
    xTaskCreate(purge_task, "purge", 3072, NULL, 6, &g_purge_task);
}

static void purge_stop(void){
    /* Request cancellation of active purge sequence */
    if (g_purge_active){
        g_purge_cancel = true;
        ESP_LOGI(TAG, "PURGE: cancel requested");
    }
}

/* ===== Entry point ===== */
void app_main(void){
    /* === CRITICAL: Pin fan/pump/LED GPIOs LOW immediately === */
    /* Must happen before ANY other init (NVS, LED, etc.) because floating GPIOs
       cause fan controllers to interpret the signal as 100% duty,
       and floating LED_STRIP_GPIO lets WS2812 latch random noise as pixel data. */
    {
        const gpio_num_t early_pins[] = { (gpio_num_t)FAN_PWM_GPIO, (gpio_num_t)PUMP_PWM_GPIO, (gpio_num_t)LED_STRIP_GPIO };
        for (int i = 0; i < 3; i++) {
            gpio_config_t cfg = {
                .pin_bit_mask = (1ULL << early_pins[i]),
                .mode         = GPIO_MODE_OUTPUT,
                .pull_up_en   = GPIO_PULLUP_DISABLE,
                .pull_down_en = GPIO_PULLDOWN_ENABLE,
                .intr_type    = GPIO_INTR_DISABLE,
            };
            gpio_config(&cfg);
            gpio_set_level(early_pins[i], 0);
        }
    }

    g_system_startup_ms = (uint32_t)(xTaskGetTickCount()*portTICK_PERIOD_MS);
    /* Init NVS */
    esp_err_t nvs_ret = nvs_flash_init();
    if (nvs_ret==ESP_ERR_NVS_NO_FREE_PAGES || nvs_ret==ESP_ERR_NVS_NEW_VERSION_FOUND){
        ESP_ERROR_CHECK(nvs_flash_erase());
        ESP_ERROR_CHECK(nvs_flash_init());
    }
    esp_err_t ret; /* for BLE init later */
    /* Load configs */
    fan_set_defaults(&g_fan);
    if(fan_load_from_nvs()!=ESP_OK){ ESP_LOGW(TAG,"FAN: defaults"); fan_save_to_nvs(); }
    pump_set_defaults(&g_pump);
    if(pump_load_from_nvs()!=ESP_OK){ ESP_LOGW(TAG,"PUMP: defaults"); pump_save_to_nvs(); }
    hours_load_from_nvs();
    /* Clear any pending boost flag to prevent autonomous purge cycles */
    boost_flag_set_pending(false);
    ESP_LOGI(TAG, "Boost pending flag cleared at boot");
    /* Load optional setting: keep LEDs on without connection */
    {
        nvs_handle_t hflag; uint8_t fval = 0;
        if (nvs_open(NVS_NS_LED, NVS_READONLY, &hflag) == ESP_OK){
            if (nvs_get_u8(hflag, "keep_on", &fval) == ESP_OK){
                g_led_allow_disconnected = (fval != 0);
                ESP_LOGI(TAG, "LED keep_on flag loaded: %u", (unsigned)fval);
            }
            nvs_close(hflag);
        }
    }
    /* Create mutex for LED operations before any LED use */
    g_led_mtx = xSemaphoreCreateMutex();
    /* Initialize LED defaults; load saved profile at boot only if keep-on is enabled */
    led_prof_set_defaults();
    if (g_led_allow_disconnected) {
        led_prof_load();
        if (g_led_prof.mode != LED_MODE_OFF) g_led_dirty = true;
    }
    leds_init();
    ESP_LOGI(TAG, "LED boot: allow_disconn=%d mode=%d br=%d dirty=%d",
             (int)g_led_allow_disconnected, g_led_prof.mode,
             g_led_prof.brightness, (int)g_led_dirty);

    gpio_set_direction(LED_GPIO,GPIO_MODE_OUTPUT);
    gpio_set_level(LED_GPIO,0);

    /* Suppress noisy LEDC warnings on unusable pins (e.g., 16/17 on some modules) */
    esp_log_level_set("ledc", ESP_LOG_ERROR);

    ensure_ledc_init_once();
    fan_pwm_set_percent(0.0f);
    pump_pwm_set_percent(0.0f);
    /* Switch to PWM-based valve control */
    valve_pwm_init();
    valve_pwm_set_percent(0.0f);

    /* Tach inputs */
    tach_init();

    /* Калибровка тахометров отключена: используем сырые RPM */

    /* Loop protection GPIOs + monitor task: init at boot */
    {
        gpio_config_t o={ .pin_bit_mask=(1ULL<<LOOP_OUT_GPIO), .mode=GPIO_MODE_OUTPUT,
                          .pull_up_en=GPIO_PULLUP_DISABLE, .pull_down_en=GPIO_PULLDOWN_DISABLE, .intr_type=GPIO_INTR_DISABLE };
        gpio_config(&o); gpio_set_level((gpio_num_t)LOOP_OUT_GPIO, 0);
        gpio_config_t i={ .pin_bit_mask=(1ULL<<LOOP_IN_GPIO), .mode=GPIO_MODE_INPUT,
                          .pull_up_en=GPIO_PULLUP_DISABLE, .pull_down_en=GPIO_PULLDOWN_ENABLE, .intr_type=GPIO_INTR_DISABLE };
        gpio_config(&i);
        /* Load loop protection flag from NVS ('sys': 'loopprot'), default OFF */
        nvs_handle_t h; uint8_t v=0xFF; if (nvs_open("sys", NVS_READONLY, &h) == ESP_OK){
            (void)nvs_get_u8(h, "loopprot", &v); nvs_close(h);
        }
        g_loopprot_enabled = (v==1)?true:false;
        ESP_LOGI(TAG, "LOOP: protection %s (nvs=%u)", g_loopprot_enabled?"ENABLED":"DISABLED", (unsigned)v);
        /* Kick a quick initial probe (toggle once) to avoid stale default before task converges */
        bool in0 = gpio_get_level((gpio_num_t)LOOP_IN_GPIO) ? true : false;
        gpio_set_level((gpio_num_t)LOOP_OUT_GPIO, 1);
        vTaskDelay(pdMS_TO_TICKS(10));
        bool in1 = gpio_get_level((gpio_num_t)LOOP_IN_GPIO) ? true : false;
        gpio_set_level((gpio_num_t)LOOP_OUT_GPIO, 0);
        g_loop_ok = (in0 != in1); /* if input reacts to toggle, assume closed */
        if (g_loopprot_enabled && !g_loop_ok){
            ESP_LOGW(TAG, "LOOP: broken at boot, enforce STOP");
            /* Enforce STOP same as SP */
            g_system_running = false;
            fan_pwm_set_percent(0.0f);
            pump_pwm_set_percent(0.0f);
            (void)ledc_stop(LEDC_HIGH_SPEED_MODE, LEDC_CHANNEL_0, 0);
            (void)ledc_stop(LEDC_HIGH_SPEED_MODE, LEDC_CHANNEL_1, 0);
            gpio_set_direction((gpio_num_t)FAN_PWM_GPIO, GPIO_MODE_OUTPUT); gpio_set_level((gpio_num_t)FAN_PWM_GPIO, 0);
            gpio_set_direction((gpio_num_t)PUMP_PWM_GPIO, GPIO_MODE_OUTPUT); gpio_set_level((gpio_num_t)PUMP_PWM_GPIO, 0);
            g_pwm_fan_attached = false; g_pwm_pump_attached = false;
            uint32_t now_ms = (uint32_t)(xTaskGetTickCount()*portTICK_PERIOD_MS);
            g_forced_stop_deadline_ms = now_ms + 1500u;
            g_pump_boost_active = false;
        }
        xTaskCreate(loopprot_task, "loopprot", 3072, NULL, 5, NULL);
    }

    /* UART */
    uart_init();
    ESP_LOGI(TAG,"USB/UART enabled @%d", UART_BAUD);

    /* DS18B20 reader */
    xTaskCreate(ds18b20_task, "ds18b20", 3072, NULL, 4, NULL);
    
    /* Loop protection monitor started above */

#if CONFIG_BT_NIMBLE_ENABLED
    /* Manual, idempotent BLE init (Legacy VHCI-safe). */
    ret = ble_stack_init_manual();
    if (ret == ESP_OK) {
        ble_hs_cfg.reset_cb          = on_reset;
        ble_hs_cfg.sync_cb           = on_sync;
        ble_hs_cfg.gatts_register_cb = gatt_register_cb;
        ble_hs_cfg.store_status_cb   = ble_store_util_status_rr;

        ble_svc_gap_init();
        ble_svc_gatt_init();
        ble_svc_gap_device_name_set("PROEKT1");

        int rc=ble_gatts_count_cfg(gatt_svcs); assert(rc==0);
        rc=ble_gatts_add_svcs(gatt_svcs);      assert(rc==0);
        ble_store_config_init();

        nimble_port_freertos_init(host_task);
    } else {
        ESP_LOGE(TAG,"BLE disabled due to init error: %s", esp_err_to_name(ret));
        g_err_ble_hw = true;
    }
#else
    ESP_LOGW(TAG,"Bluetooth NimBLE disabled in menuconfig");
#endif

    xTaskCreate(control_task,"fan_pump_ctrl",4096,NULL,5,NULL);
    xTaskCreate(led_task,"led_task",3072,NULL,4,&g_led_task);
    xTaskCreate(oled_task,"oled_task",4096,NULL,3,NULL);
}
/* ===== RPM calibration: load/save and one-time autocal at boot ===== */
static void __attribute__((unused)) rpm_scale_load(void){
    g_rpm_scale_has1 = g_rpm_scale_has2 = false;
    nvs_handle_t h;
    if (nvs_open(NVS_NS_CAL, NVS_READONLY, &h) == ESP_OK) {
        size_t sz = sizeof(float);
        float v;
        if (nvs_get_blob(h, NVS_KEY_RPM1, &v, &sz) == ESP_OK && sz == sizeof(float) && isfinite(v) && v > 0.1f && v < 5.0f) {
            g_rpm_scale1 = v; g_rpm_scale_has1 = true;
        }
        sz = sizeof(float);
        if (nvs_get_blob(h, NVS_KEY_RPM2, &v, &sz) == ESP_OK && sz == sizeof(float) && isfinite(v) && v > 0.1f && v < 5.0f) {
            g_rpm_scale2 = v; g_rpm_scale_has2 = true;
        }
        nvs_close(h);
    }
    if (g_rpm_scale_has1 || g_rpm_scale_has2) {
        ESP_LOGI(TAG, "RPM scale loaded: f1=%.4f%s f2=%.4f%s",
                 (double)g_rpm_scale1, g_rpm_scale_has1?"":" (def)",
                 (double)g_rpm_scale2, g_rpm_scale_has2?"":" (def)");
    } else {
        ESP_LOGI(TAG, "RPM scale: defaults (no NVS)");
    }
}

static void rpm_scale_save(void){
    nvs_handle_t h;
    if (nvs_open(NVS_NS_CAL, NVS_READWRITE, &h) != ESP_OK) return;
    (void)nvs_set_blob(h, NVS_KEY_RPM1, &g_rpm_scale1, sizeof(g_rpm_scale1));
    (void)nvs_set_blob(h, NVS_KEY_RPM2, &g_rpm_scale2, sizeof(g_rpm_scale2));
    (void)nvs_commit(h);
    nvs_close(h);
    ESP_LOGI(TAG, "RPM scale saved: f1=%.4f f2=%.4f", (double)g_rpm_scale1, (double)g_rpm_scale2);
}

static inline void tach_reset_counters(void){
    g_tach1_edges = 0; g_tach2_edges = 0;
    g_tach1_last_us = 0; g_tach2_last_us = 0;
}

static void tach_measure_raw(uint32_t interval_ms, int32_t *out_rpm1_raw, int32_t *out_rpm2_raw){
    tach_reset_counters();
    vTaskDelay(pdMS_TO_TICKS(interval_ms));
    uint32_t e1 = g_tach1_edges;
    uint32_t e2 = g_tach2_edges;
    float seconds = (float)interval_ms / 1000.0f;
    int32_t r1 = (int32_t)lroundf(((float)e1 / (float)TACH_PULSES_PER_REV) * (60.0f / seconds));
    int32_t r2 = (int32_t)lroundf(((float)e2 / (float)TACH_PULSES_PER_REV) * (60.0f / seconds));
    if (out_rpm1_raw) *out_rpm1_raw = r1;
    if (out_rpm2_raw) *out_rpm2_raw = r2;
}

static void rpm_autocalibrate(void){
    /* Run only if not already stored */
    if (g_calibrating) { ESP_LOGW(TAG, "RPM autocal: already running"); return; }
    g_calibrating = true;
    if (g_rpm_scale_has1 && g_rpm_scale_has2) {
        ESP_LOGI(TAG, "RPM autocal: overriding existing calibration (manual trigger)");
    }
    ESP_LOGI(TAG, "RPM autocal: 100%% PWM for 15s, measuring raw RPM");
    ensure_ledc_init_once();
    /* Spin-up */
    fan_pwm_set_percent(100.0f);
    pump_pwm_set_percent(100.0f);
    vTaskDelay(pdMS_TO_TICKS(15000));
    /* Two measurements of 1000 ms for stability */
    int32_t r1a=0,r2a=0,r1b=0,r2b=0;
    tach_measure_raw(1000, &r1a, &r2a);
    tach_measure_raw(1000, &r1b, &r2b);
    fan_pwm_set_percent(0.0f);
    pump_pwm_set_percent(0.0f);
    int32_t r1 = (r1a + r1b) / 2;
    int32_t r2 = (r2a + r2b) / 2;
    ESP_LOGI(TAG, "RPM autocal raw: f1=%ld (%ld,%ld) f2=%ld (%ld,%ld)",
             (long)r1, (long)r1a, (long)r1b, (long)r2, (long)r2a, (long)r2b);
    const float target = 1800.0f;
    bool changed=false;
    if (!g_rpm_scale_has1 && r1 > 200) {
        float s = target / (float)r1;
        s = clampf(s, 0.2f, 2.0f);
        g_rpm_scale1 = s; g_rpm_scale_has1 = true; changed=true;
    }
    if (!g_rpm_scale_has2 && r2 > 200) {
        float s = target / (float)r2;
        s = clampf(s, 0.2f, 2.0f);
        g_rpm_scale2 = s; g_rpm_scale_has2 = true; changed=true;
    }
    if (changed) {
        rpm_scale_save();
        ESP_LOGI(TAG, "RPM autocal done: scale1=%.4f scale2=%.4f (target=%.0f)", (double)g_rpm_scale1, (double)g_rpm_scale2, (double)target);
    } else {
        ESP_LOGW(TAG, "RPM autocal skipped: insufficient raw RPM (r1=%ld r2=%ld)", (long)r1, (long)r2);
    }
    g_calibrating = false;
}

/* ===== OLED Task ===== */

/* Smooth a scaled glyph by filling "staircase" corners.
 * Scans the framebuffer region and wherever two diagonally adjacent pixels are
 * ON but their shared orthogonal neighbours are OFF, fills one corner pixel to
 * round off the blocky edges. */
static void oled_smooth_region(int rx, int ry, int rw, int rh){
    /* Work on a copy to avoid feedback during the scan */
    for (int y = ry + 1; y < ry + rh - 1; ++y){
        for (int x = rx + 1; x < rw + rx - 1; ++x){
            /* current pixel must be ON */
            int page = y >> 3; int bit = y & 7;
            if (x < 0 || x >= OLED_WIDTH || y < 0 || y >= OLED_HEIGHT) continue;
            size_t idx = (size_t)page * OLED_WIDTH + (size_t)x;
            if (!(g_oled_fb[idx] & (1u << bit))) continue;

            /* Check 4 diagonal directions; if diagonal is ON but the two
             * orthogonal neighbours bridging it are OFF → fill one of them */
            #define PX_ON(px, py) ( \
                (px) >= 0 && (px) < OLED_WIDTH && (py) >= 0 && (py) < OLED_HEIGHT && \
                (g_oled_fb[((py)>>3)*OLED_WIDTH+(px)] & (1u << ((py)&7))) )

            /* top-right: if (x+1,y-1) ON, but (x+1,y) OFF and (x,y-1) OFF → fill (x+1,y-1 side) */
            if (PX_ON(x+1,y-1) && !PX_ON(x+1,y) && !PX_ON(x,y-1))
                oled_fb_set_pixel(x, y-1, true);
            /* top-left */
            if (PX_ON(x-1,y-1) && !PX_ON(x-1,y) && !PX_ON(x,y-1))
                oled_fb_set_pixel(x, y-1, true);
            /* bottom-right */
            if (PX_ON(x+1,y+1) && !PX_ON(x+1,y) && !PX_ON(x,y+1))
                oled_fb_set_pixel(x, y+1, true);
            /* bottom-left */
            if (PX_ON(x-1,y+1) && !PX_ON(x-1,y) && !PX_ON(x,y+1))
                oled_fb_set_pixel(x, y+1, true);

            #undef PX_ON
        }
    }
}

static void oled_task(void *arg){
    (void)arg;
    oled_init();
    if (!g_oled_inited){
        ESP_LOGE(TAG, "OLED: init failed");
        vTaskDelete(NULL);
        return;
    }

    /* Capture display-ready timestamp — countdown starts from THIS moment, not app_main */
    uint32_t oled_ready_ms = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);

    ESP_LOGI(TAG, "OLED: task started (portrait 64x128)");

    /* Draw a single char at integer scale S */
    #define DRAW_CHAR_S(x0, y0, ch, S) do { \
        const uint8_t* _g = font5x7_get(ch); \
        for (int _dx = 0; _dx < 5; ++_dx){ \
            uint8_t _col = _g[_dx]; \
            for (int _dy = 0; _dy < 7; ++_dy){ \
                if ((_col >> _dy) & 1u){ \
                    for (int _sy = 0; _sy < (S); ++_sy) \
                        for (int _sx = 0; _sx < (S); ++_sx) \
                            oled_fb_set_pixel((x0)+_dx*(S)+_sx, (y0)+_dy*(S)+_sy, true); \
                } \
            } \
        } \
    } while(0)

    /* Draw text at scale S with stride = 6*S per char */
    #define DRAW_TEXT_S(x0, y0, str, S) do { \
        const char* _s = (str); int _x = (x0); \
        for (int _k = 0; _s[_k]; ++_k){ \
            DRAW_CHAR_S(_x, (y0), _s[_k], (S)); \
            _x += 6 * (S); \
        } \
    } while(0)

    /* Draw integer right-aligned at scale S, `width` char slots, stride per slot */
    #define DRAW_INT_S(x0, y0, val, width, S, stride) do { \
        char _buf[12]; int _v = (val); \
        int _neg = (_v < 0); if (_neg) _v = -_v; \
        int _i = 0; \
        if (_v == 0) { _buf[_i++] = '0'; } \
        else { while (_v > 0 && _i < 10) { _buf[_i++] = '0' + (_v % 10); _v /= 10; } } \
        if (_neg && _i < 11) _buf[_i++] = '-'; \
        int _pad = (width) - _i; \
        for (int _p = 0; _p < _pad; ++_p) DRAW_CHAR_S((x0) + _p * (stride), (y0), ' ', (S)); \
        for (int _j = 0; _j < _i; ++_j) DRAW_CHAR_S((x0) + (_pad + _i - 1 - _j) * (stride), (y0), _buf[_j], (S)); \
    } while(0)

    /* Same as DRAW_INT_S but pads with '0' instead of space (for animations: 01 02 ... 09) */
    #define DRAW_INT_ZP_S(x0, y0, val, width, S, stride) do { \
        char _buf[12]; int _v = (val); \
        int _neg = (_v < 0); if (_neg) _v = -_v; \
        int _i = 0; \
        if (_v == 0) { _buf[_i++] = '0'; } \
        else { while (_v > 0 && _i < 10) { _buf[_i++] = '0' + (_v % 10); _v /= 10; } } \
        if (_neg && _i < 11) _buf[_i++] = '-'; \
        int _pad = (width) - _i; \
        for (int _p = 0; _p < _pad; ++_p) DRAW_CHAR_S((x0) + _p * (stride), (y0), '0', (S)); \
        for (int _j = 0; _j < _i; ++_j) DRAW_CHAR_S((x0) + (_pad + _i - 1 - _j) * (stride), (y0), _buf[_j], (S)); \
    } while(0)

    /* Draw a 5x7 icon glyph (column-major, LSB=top) at position, with optional scale */
    #define DRAW_ICON(x0, y0, cols5, S) do { \
        for (int _dx = 0; _dx < 5; ++_dx){ \
            uint8_t _col = (cols5)[_dx]; \
            for (int _dy = 0; _dy < 7; ++_dy){ \
                if ((_col >> _dy) & 1u){ \
                    for (int _sy = 0; _sy < (S); ++_sy) \
                        for (int _sx = 0; _sx < (S); ++_sx) \
                            oled_fb_set_pixel((x0)+_dx*(S)+_sx, (y0)+_dy*(S)+_sy, true); \
                } \
            } \
        } \
    } while(0)

    /* --- Status bar icons (5 cols × 7 rows, column-major, LSB=top) --- */
    /* Bluetooth symbol (stylised B with arrowheads) */
    static const uint8_t ico_bt[5]   = {0x22, 0x14, 0x7F, 0x2A, 0x14};
    /* USB symbol (trident-like) */
    static const uint8_t ico_usb[5]  = {0x08, 0x1C, 0x7F, 0x1C, 0x08};
    /* Ready: bold checkmark (thicker strokes) */
    static const uint8_t ico_rdy[5]  = {0x30,0x60,0x30,0x18,0x0C};
    /* Loading: dot count cycles 0..2 (animated via load_frame) */
    static int load_frame = 0;
    /* Warning triangle icon (5×7, column-major, LSB=top):
     *  row0: . . X . .    row1: . X . X .    row2: X . . . X
     *  row3: X . . . X    row4: X X X X X */
    static const uint8_t ico_warn[5] = {0x1C, 0x12, 0x11, 0x12, 0x1C};

    /* Layout constants.
     * Scale 2 for digits.
     * 3 temperature sections + separator lines + status bar at bottom.
     *
     * Section height 35px: 5(pad) + 7(label) + 2(gap) + 14(digits) + 7(pad) = 35px
     * 3 sections × 35 = 105.  2 separators + 1 status sep = 3.  Status bar: 20.
     * Total: 105 + 3 + 20 = 128.  Tighter padding, larger status bar. */
    const int SCALE    = 2;
    const int DIG_W    = 5 * SCALE;       /* 10 */
    const int DIG_STR  = DIG_W + 1;      /* 11 — stride between 2x chars */
    const int DIG_H    = 7 * SCALE;       /* 14 */
    const int DEGC_W   = 16;             /* 4(ring) + 2(gap) + 10(C@2x) */
    const int SEC_H    = 35;             /* section height */
    const int STATUS_H = 20;            /* status bar height */
    const int STATUS_Y = 128 - STATUS_H; /* y=108 */

    /* Screen timeout state */
    uint32_t disconn_since_ms = 0; /* ms-timestamp when no-connection state began (0 = connected) */
    bool screen_off = false;       /* true after fade-out; suppresses render until fade-in */
    /* Frame index at which the ПОДКЛЮЧАЮ animation started (-1 = not active) */
    int conn_frame_base = -1;
    /* Wall-clock deadline (ms) until which ПОДКЛЮЧАЮ animation is active.
     * Set once when connection is first latched; is_connecting is derived purely
     * from this timestamp so no transport flicker can make errors bleed through. */
    uint32_t conn_anim_end_ms = 0;
    /* Wall-clock error blink: ЗАЩИТА/ОШИБКА alternates with РАБОТА/ПАУЗА every
     * ERR_BLINK_HALF_MS ms, independent of load_frame — speed never changes. */
    #define ERR_BLINK_HALF_MS 500u
    bool     err_blink_on        = false;
    uint32_t err_blink_toggle_ms = 0;
    /* Frame index at which the ПРОДУВКА animation started (-1 = not active) */
    int purge_frame_base = -1;
    /* Frame index at which the НАПОЛНЯЮ (ramp) animation started (-1 = not active) */
    int ramp_frame_base = -1;
    /* After purge finishes, suppress "РАБОТА" for a grace period while
     * the system transitions to STOP (g_system_running drop may lag by 1-3 s). */
    bool     prev_purge_active = false;
    uint32_t purge_ended_ms    = 0;
    #define PURGE_WORK_SUPPRESS_MS 3000u
    /* Waiting-for-target-temps marquee scroll state */
    int      wait_scroll_px          = 0;
    bool     prev_waiting_for_temps  = false;
    uint32_t wait_scroll_ms          = 0;
    #define WAIT_SCROLL_PERIOD_MS 30u   /* ~33 px/s, smooth marquee scroll */
    /* Hydroline disconnected marquee scroll state */
    int      hydro_scroll_px         = 0;
    bool     prev_hydro_active       = false;
    uint32_t hydro_scroll_ms         = 0;
    #define HYDRO_SCROLL_PERIOD_MS 30u  /* ~33 px/s, same speed as waiting scroll */
    /* How long to show "ПОДКЛЮЧАЮ" after a new BLE/USB connection */
    #define CONNECTING_SHOW_MS 4000u

    /* Per-channel connect-in animation: fires when a channel transitions -1000→real.
     * Counts 0 → actual over CONN_ANIM_DUR_MS at 20 ms/frame. */
    #define CONN_ANIM_DUR_MS (22u * 94u)   /* same as boot countdown: 2068 ms */
    int32_t prev_ch[3]        = {-1000, -1000, -1000}; /* last seen value per channel */
    uint32_t ch_anim_start[3] = {0, 0, 0};             /* 0 = not active             */

    /* Timestamp of last load_frame advance. load_frame ticks every 94 ms regardless
     * of how fast the OLED loop runs — so ЗАГРУЗКА speed is always correct even
     * when we refresh the screen at 20 ms during the boot digit countdown. */
    uint32_t last_load_frame_ms = oled_ready_ms;

    for (;;){
        oled_fb_clear();

        /* ----- Screen timeout: 10 min no-connection -> fade out; on connect -> fade in ----- */
        {
            bool any_conn = g_ble_connected || g_usb_connected;
            uint32_t t_now = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);

            if (any_conn) {
                disconn_since_ms = 0;
                if (screen_off) {
                    /* Fade in: 0 -> g_oled_brightness over 3 s (60 steps × 50 ms) */
                    uint8_t target = g_oled_brightness;
                    for (int s = 0; s <= 60; s++) {
                        uint8_t br = (uint8_t)((uint32_t)target * (uint32_t)s / 60u);
                        oled_send_cmd(0x81); oled_send_cmd(br);
                        vTaskDelay(pdMS_TO_TICKS(50));
                    }
                    screen_off = false;
                }
            } else {
                if (disconn_since_ms == 0) disconn_since_ms = t_now ? t_now : 1u;
                if (!screen_off && (t_now - disconn_since_ms) >= 600000u) {
                    /* Fade out: g_oled_brightness -> 0 over 3 s (60 steps × 50 ms) */
                    uint8_t start_br = g_oled_brightness;
                    for (int s = 60; s >= 0; s--) {
                        uint8_t br = (uint8_t)((uint32_t)start_br * (uint32_t)s / 60u);
                        oled_send_cmd(0x81); oled_send_cmd(br);
                        vTaskDelay(pdMS_TO_TICKS(50));
                    }
                    screen_off = true;
                }
            }

            /* While screen is off: skip rendering, poll at 1 Hz */
            if (screen_off) {
                vTaskDelay(pdMS_TO_TICKS(1000));
                continue;
            }
        }

        /* ---- Boot countdown for temperatures: 99 → actual (or 99 → 00 → "--") over 5 s ---- */
        /* Use oled_ready_ms (display-ready time) so the full 5 s is always visible */
        uint32_t bc_now = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);

        /* Detect purge end: latch timestamp for РАБОТА-suppress grace period */
        {
            bool cur_purge = g_purge_active;
            if (prev_purge_active && !cur_purge)
                purge_ended_ms = bc_now ? bc_now : 1u;
            prev_purge_active = cur_purge;
        }
        uint32_t bc_elapsed = bc_now - oled_ready_ms;
        /* Duration = 22 frames × 94 ms — exactly matches the ЗАГРУЗКА animation,
         * so digits and status bar animation end at the same tick. One-shot: once
         * bc_elapsed exceeds this value it is never <2068 again (oled_ready_ms is fixed). */
        bool is_boot_countdown = (bc_elapsed < CONN_ANIM_DUR_MS);

        /* ---- Detect -1000→real transitions and latch connect-in animation start times ---- */
        {
            int32_t cur[3] = {g_cpu_temp_c, g_gpu_temp_c, g_water_temp_c};
            for (int ci = 0; ci < 3; ++ci) {
                if (prev_ch[ci] <= -1000 && cur[ci] > -1000 && !is_boot_countdown) {
                    /* Channel just got first real data after boot countdown finished */
                    ch_anim_start[ci] = bc_now ? bc_now : 1u;
                }
                if (cur[ci] <= -1000) {
                    /* Data lost: reset so animation re-fires next time data arrives */
                    ch_anim_start[ci] = 0;
                }
                prev_ch[ci] = cur[ci];
            }
        }
        /* Any connect-in animation active? (drives 20 ms frame rate) */
        bool is_conn_anim = false;
        for (int ci = 0; ci < 3; ++ci) {
            if (ch_anim_start[ci] != 0 && (bc_now - ch_anim_start[ci]) < CONN_ANIM_DUR_MS)
                is_conn_anim = true;
        }

        /* ---- 3 temperature sections ---- */
        for (int sec = 0; sec < 3; ++sec){
            int sy = sec * (SEC_H + 1);   /* +1 for separator pixel */
            const char* label;
            int temp;

            switch (sec){
                case 0: label = g_display_lang ? "CPU"   : "ЦП";   temp = (int)g_cpu_temp_c;   break;
                case 1: label = g_display_lang ? "GPU"   : "ГП";   temp = (int)g_gpu_temp_c;   break;
                default: label = g_display_lang ? "WATER" : "ВОДА"; temp = (int)g_water_temp_c; break;
            }

            /* Boot countdown: animate digits from 99 down to actual value.
             * Duration matches ЗАГРУЗКА exactly: 22 frames × 94 ms = 2068 ms.
             * Connected (temp > -1000): lerp 99 → actual.
             * No data (temp == -1000): count 99 → 0, then normal "--". */
            if (is_boot_countdown) {
                float prog = (float)bc_elapsed / (float)CONN_ANIM_DUR_MS;
                if (prog > 1.0f) prog = 1.0f;
                if (temp > -1000) {
                    temp = 99 + (int)((float)(temp - 99) * prog + 0.5f);
                } else {
                    temp = 99 - (int)(99.0f * prog + 0.5f);
                }
            } else if (ch_anim_start[sec] != 0 && temp > -1000) {
                /* Connect-in animation: count 0 → actual over CONN_ANIM_DUR_MS */
                uint32_t ch_elapsed = bc_now - ch_anim_start[sec];
                if (ch_elapsed < CONN_ANIM_DUR_MS) {
                    float prog = (float)ch_elapsed / (float)CONN_ANIM_DUR_MS;
                    temp = (int)((float)temp * prog + 0.5f);
                }
                /* When elapsed >= CONN_ANIM_DUR_MS: show actual value as-is */
            }

            /* Label: 1x centred (use codepoint count for UTF-8 strings) */
            int lbl_w = utf8_charlen(label);
            oled_draw_text((64 - lbl_w * 6) / 2, sy + 5, label);

            /* Count digits for horizontal centering */
            int ndig = 0;
            int dig_y = sy + 14;

            if (temp <= -1000) {
                ndig = 2;  /* "--" + °C */
            } else {
                int tv = temp < 0 ? -temp : temp;
                if (tv >= 100) ndig = 3;
                else if (tv >= 10) ndig = 2;
                else ndig = 1;
                if (temp < 0) ndig++;
            }

            /* During any digit animation keep at least 2 digits so "01..09" never shifts
             * layout compared to "10..99". Applies to both boot countdown and connect-in. */
            bool sec_anim_active = is_boot_countdown ||
                (ch_anim_start[sec] != 0 && (bc_now - ch_anim_start[sec]) < CONN_ANIM_DUR_MS);
            if (sec_anim_active && ndig < 2) ndig = 2;

            /* total width: digits + gap + °C */
            int total_w = (ndig - 1) * DIG_STR + DIG_W + 2 + DEGC_W;
            int dig_x = (64 - total_w) / 2;
            if (dig_x < 0) dig_x = 0;

            if (temp <= -1000) {
                DRAW_CHAR_S(dig_x + 0 * DIG_STR, dig_y, '-', SCALE);
                DRAW_CHAR_S(dig_x + 1 * DIG_STR, dig_y, '-', SCALE);
            } else if (sec_anim_active) {
                DRAW_INT_ZP_S(dig_x, dig_y, temp, ndig, SCALE, DIG_STR);
            } else {
                DRAW_INT_S(dig_x, dig_y, temp, ndig, SCALE, DIG_STR);
            }

            /* Smooth the digit region */
            oled_smooth_region(dig_x, dig_y, ndig * DIG_STR, DIG_H);

            /* °C: degree ring (4x4) + C at 2x, vertically centred with digits */
            int degc_x = dig_x + (ndig - 1) * DIG_STR + DIG_W + 2;
            int degc_y = dig_y + (DIG_H - 14) / 2;
            /* degree ring */
            oled_fb_set_pixel(degc_x+1, degc_y,   true);
            oled_fb_set_pixel(degc_x+2, degc_y,   true);
            oled_fb_set_pixel(degc_x,   degc_y+1, true);
            oled_fb_set_pixel(degc_x+3, degc_y+1, true);
            oled_fb_set_pixel(degc_x,   degc_y+2, true);
            oled_fb_set_pixel(degc_x+3, degc_y+2, true);
            oled_fb_set_pixel(degc_x+1, degc_y+3, true);
            oled_fb_set_pixel(degc_x+2, degc_y+3, true);
            /* C at 2x */
            DRAW_CHAR_S(degc_x + 6, degc_y, 'C', 2);

            /* Separator line between sections (sparse dithered: 1 dot every 5px) */
            if (sec < 2){
                int sep_y = sy + SEC_H;
                for (int x = 4; x < 60; x += 5)
                    oled_fb_set_pixel(x, sep_y, true);
            }
        }

        /* ---- Status bar (y = STATUS_Y .. 127) ---- */
        /* Separator above status bar (sparse dithered: 1 dot every 5px) */
        for (int x = 0; x < 64; x += 5)
            oled_fb_set_pixel(x, STATUS_Y - 1, true);

        int ico_y = STATUS_Y + (STATUS_H - 7) / 2;  /* vertically centre 7px icon */

        /* Determine connection state */
        /* 2 cycles × 11 frames × 94 ms ≈ 2.1 s boot animation */
        bool is_loading = (load_frame < 22);

#if CONFIG_BT_NIMBLE_ENABLED
        bool ble_on = g_ble_connected;
        bool usb_on = g_usb_connected;
#else
        bool ble_on = false;
        bool usb_on = g_usb_connected;
#endif
        /* ПОДКЛЮЧАЮ: latch animation when a new connection first appears.
         * is_connecting is derived exclusively from a wall-clock deadline
         * (conn_anim_end_ms) so NO transport flicker, disconnect, or loop-break
         * event can cut it short — ЗАЩИТА and all other errors are unconditionally
         * blocked for the full 2750 ms animation window (22 frames × 125 ms). */
        {
            bool any_new_conn = !is_loading &&
                ((ble_on && g_ble_conn_since_ms != 0) ||
                 (usb_on && g_usb_conn_since_ms != 0));
            if (any_new_conn) {
                if (conn_frame_base < 0) {
                    conn_frame_base  = load_frame;          /* latch frame base for letter reveal */
                    conn_anim_end_ms = bc_now + 22u * 125u; /* wall-clock deadline: 2750 ms */
                }
            } else {
                /* Expire only after the full wall-clock window has passed */
                if (bc_now >= conn_anim_end_ms)
                    conn_frame_base = -1;
            }
        }
        /* Pure wall-clock gate: once triggered, stays true for the full 2750 ms
         * regardless of what happens to the connection state. */
        bool is_connecting = (conn_anim_end_ms != 0) && (bc_now < conn_anim_end_ms) && !is_loading;

        /* ПРОДУВКА: show while g_purge_active, looping; latch frame base so animation
         * always starts from the first letter regardless of load_frame value.
         * Ensure that once started, the animation finishes at least one full
         * reveal+pause cycle even if purge ends early. */
        {
            const int PURGE_FULL_FRAMES = 11; /* reveal (0..7) + pause (8..10) */
            if (g_purge_active) {
                if (purge_frame_base < 0) purge_frame_base = load_frame;
            } else {
                if (purge_frame_base >= 0) {
                    if ((load_frame - purge_frame_base) >= PURGE_FULL_FRAMES) purge_frame_base = -1;
                } else {
                    purge_frame_base = -1;
                }
            }
        }
        bool is_purging = (purge_frame_base >= 0);

        /* RAMP (НАПОЛНЯЮ): show while pump boost is active (post-purge filling).
         * Once started, allow the animation to finish at least one full cycle
         * even if pump boost ends prematurely. */
        {
            const int RAMP_FULL_FRAMES = 11; /* reveal+pause frames */
            if (g_pump_boost_active) {
                if (ramp_frame_base < 0) ramp_frame_base = load_frame;
            } else {
                if (ramp_frame_base >= 0) {
                    if ((load_frame - ramp_frame_base) >= RAMP_FULL_FRAMES) ramp_frame_base = -1;
                } else {
                    ramp_frame_base = -1;
                }
            }
        }
        bool is_ramping = (ramp_frame_base >= 0);

        /* ----- Compute highest-priority active error code -----
         *  err 1: fan or pump stall (PWM > 1% but RPM < threshold)
         *  err 2: BLE hardware/stack init failed
         *  err 3: UART/USB hardware init failed
         *  err 4: DS18B20 water sensor dead > 60 s after first response
         *  err 5: liquid loop broken (hose/leak, loop-protection enabled)
         *  err 6: water temperature critical (>= WATER_TEMP_CRIT_C °C)
         */
        uint32_t now_err = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
        bool e1 = (g_rpm_flags & (RPM_FLAG_F1 | RPM_FLAG_F2)) != 0;
        bool e2 = g_err_ble_hw;
        bool e3 = g_err_uart_hw;
        /* err 4: sensor was seen at least once AND has been silent > 60 s */
        bool e4 = (g_last_water_ms != 0) && ((now_err - g_last_water_ms) > 60000u);
        /* err 5: loop protection active AND loop is currently broken */
        bool e5 = g_loopprot_enabled && !g_loop_ok;
        /* err 6: water temp is valid AND has exceeded critical threshold */
        bool e6 = (g_water_temp_c > -1000) && (g_water_temp_c >= WATER_TEMP_CRIT_C);
        int active_err = 0;
        /* Priority: e6 (water overheat) > e5 (loop broken) > e1 (fan stall) > e4 (sensor dead) > e2/e3 (hw init) */
        if      (e6) active_err = 6;
        else if (e5) active_err = 5;
        else if (e1) active_err = 1;
        else if (e4) active_err = 4;
        else if (e2) active_err = 2;
        else if (e3) active_err = 3;

        /* Advance the wall-clock error blink.
         * While any status-bar animation plays, blink is frozen at false so errors
         * cannot bleed through.  Timer resets at animation end → first thing shown is
         * always the normal status (ПАУЗА/РАБОТА/…), then alternate every 500 ms. */
        {
            bool any_status_anim = is_loading || is_purging || is_ramping || is_connecting;
            if (any_status_anim) {
                err_blink_on        = false;
                err_blink_toggle_ms = bc_now;
            } else if (active_err != 0) {
                if ((bc_now - err_blink_toggle_ms) >= ERR_BLINK_HALF_MS) {
                    err_blink_on        = !err_blink_on;
                    err_blink_toggle_ms += ERR_BLINK_HALF_MS;
                    /* Guard against lag accumulation */
                    if ((bc_now - err_blink_toggle_ms) >= ERR_BLINK_HALF_MS)
                        err_blink_toggle_ms = bc_now;
                }
            } else {
                /* No active error — reset timer so it's fresh when error appears */
                err_blink_on        = false;
                err_blink_toggle_ms = bc_now;
            }
        }

        /* Waiting-for-target-temps: explicit flag from app (command TW) */
        bool waiting_for_temps = g_waiting_for_temps;

        /* Advance marquee scroll offset when waiting */
        if (waiting_for_temps) {
            if (!prev_waiting_for_temps) { wait_scroll_px = 0; wait_scroll_ms = bc_now; }
            if ((bc_now - wait_scroll_ms) >= WAIT_SCROLL_PERIOD_MS) {
                wait_scroll_px++;
                wait_scroll_ms += WAIT_SCROLL_PERIOD_MS;
                if ((bc_now - wait_scroll_ms) >= WAIT_SCROLL_PERIOD_MS) wait_scroll_ms = bc_now;
            }
        } else {
            wait_scroll_px = 0;
        }
        prev_waiting_for_temps = waiting_for_temps;

        /* Advance hydroline-disconnected marquee scroll offset */
        if (e5) {
            if (!prev_hydro_active) { hydro_scroll_px = 0; hydro_scroll_ms = bc_now; }
            if ((bc_now - hydro_scroll_ms) >= HYDRO_SCROLL_PERIOD_MS) {
                hydro_scroll_px++;
                hydro_scroll_ms += HYDRO_SCROLL_PERIOD_MS;
                if ((bc_now - hydro_scroll_ms) >= HYDRO_SCROLL_PERIOD_MS) hydro_scroll_ms = bc_now;
            }
        } else {
            hydro_scroll_px = 0;
        }
        prev_hydro_active = e5;

        if (is_loading) {
            /* ЗАГРУЗКА letter-by-letter: 2 cycles × 11 frames × 94 ms ≈ 2.1 s.
             * Frames 0..7: reveal 1 new letter per frame (8 letters total).
             * Frames 8..10: pause, all 8 letters shown. */
            const char* load_word = g_display_lang ? "LOADING" : "ЗАГРУЗКА";
            int load_word_len = g_display_lang ? 7 : 8;
            int cycle_frame = load_frame % 11;
            int revealed_letters = (cycle_frame < load_word_len) ? cycle_frame + 1 : load_word_len;

            const int word_px = load_word_len * 6;
            int wx = (64 - word_px) / 2;  /* =8 */

            const char* wp = load_word;
            int xpos = wx;
            for (int li = 0; li < revealed_letters; li++) {
                uint16_t lcp = utf8_next_cp(&wp);
                if (lcp == 0) break;
                int lnc = 5;
                const uint8_t* lg = font_wide_get((int)lcp, &lnc);
                if (!lg) lg = font5x7_get((int)lcp);
                for (int dc = 0; dc < lnc; dc++) {
                    uint8_t lcol = lg[dc];
                    for (int dr = 0; dr < 8; dr++) {
                        if ((lcol >> dr) & 1u)
                            oled_fb_set_pixel(xpos + dc, ico_y + dr, true);
                    }
                }
                xpos += lnc + 1;
            }
        } else if (is_purging) {
            /* ПРОДУВКА letter-by-letter, loops while purge is active.
             * 8 letters: frames 0..7 reveal, frames 8..10 pause, then repeats.
             * 125 ms/frame → 11 * 125 = 1.375 s per cycle. */
            const char* purge_word = g_display_lang ? "PURGING" : "ПРОДУВКА";
            int purge_word_len = g_display_lang ? 7 : 8;
            int prel   = load_frame - purge_frame_base;
            int pcycle = prel % 11;
            int purge_revealed = (pcycle < purge_word_len) ? pcycle + 1 : purge_word_len;

            const int purge_px = purge_word_len * 6;
            int pwx = (64 - purge_px) / 2;    /* =8 */

            const char* pwp = purge_word;
            int pxpos = pwx;
            for (int li = 0; li < purge_revealed; li++) {
                uint16_t lcp = utf8_next_cp(&pwp);
                if (lcp == 0) break;
                int lnc = 5;
                const uint8_t* lg = font_wide_get((int)lcp, &lnc);
                if (!lg) lg = font5x7_get((int)lcp);
                for (int dc = 0; dc < lnc; dc++) {
                    uint8_t lcol = lg[dc];
                    for (int dr = 0; dr < 8; dr++) {
                        if ((lcol >> dr) & 1u)
                            oled_fb_set_pixel(pxpos + dc, ico_y + dr, true);
                    }
                }
                pxpos += lnc + 1;
            }
        } else if (is_ramping) {
            /* НАПОЛНЯЮ letter-by-letter, show during the short valve PWM ramp.
             * 8 letters: frames 0..7 reveal, frames 8..10 pause, then repeats. */
            const char* ramp_word = g_display_lang ? "FILLING" : "НАПОЛНЯЮ";
            int ramp_word_len = g_display_lang ? 7 : 8;
            int rrel   = load_frame - ramp_frame_base;
            int rcycle = rrel % 11;
            int ramp_revealed = (rcycle < ramp_word_len) ? rcycle + 1 : ramp_word_len;

            const int ramp_px = ramp_word_len * 6;
            int rwx = (64 - ramp_px) / 2;    /* =8 */

            const char* rwp = ramp_word;
            int rxpos = rwx;
            for (int li = 0; li < ramp_revealed; li++) {
                uint16_t lcp = utf8_next_cp(&rwp);
                if (lcp == 0) break;
                int lnc = 5;
                const uint8_t* lg = font_wide_get((int)lcp, &lnc);
                if (!lg) lg = font5x7_get((int)lcp);
                for (int dc = 0; dc < lnc; dc++) {
                    uint8_t lcol = lg[dc];
                    for (int dr = 0; dr < 8; dr++) {
                        if ((lcol >> dr) & 1u)
                            oled_fb_set_pixel(rxpos + dc, ico_y + dr, true);
                    }
                }
                rxpos += lnc + 1;
            }
        } else if (is_connecting) {
            /* ПОДКЛЮЧАЮ letter-by-letter, 2 cycles.
             * rel_frame is relative to connection moment → always starts from letter 1.
             * Frames 0..8: reveal 1 new letter per frame (9 letters).
             * Frames 9..10: pause, all 9 letters shown. 2 × 11 × 125 ms ≈ 2.75 s. */
            const char* conn_word = g_display_lang ? "CONNECT" : "ПОДКЛЮЧАЮ";
            int conn_word_len = g_display_lang ? 7 : 9;
            int rel_frame  = load_frame - conn_frame_base;
            int ccycle     = rel_frame % 11;
            int conn_revealed = (ccycle < conn_word_len) ? ccycle + 1 : conn_word_len;

            const int conn_px = conn_word_len * 6;
            int cwx = (64 - conn_px) / 2;    /* =5 */

            const char* cwp = conn_word;
            int cxpos = cwx;
            for (int li = 0; li < conn_revealed; li++) {
                uint16_t lcp = utf8_next_cp(&cwp);
                if (lcp == 0) break;
                int lnc = 5;
                const uint8_t* lg = font_wide_get((int)lcp, &lnc);
                if (!lg) lg = font5x7_get((int)lcp);
                for (int dc = 0; dc < lnc; dc++) {
                    uint8_t lcol = lg[dc];
                    for (int dr = 0; dr < 8; dr++) {
                        if ((lcol >> dr) & 1u)
                            oled_fb_set_pixel(cxpos + dc, ico_y + dr, true);
                    }
                }
                cxpos += lnc + 1;
            }
        } else if (e5) {
            /* HYDROLINE DISCONNECTED: pixel-marquee "подключите гидролинии".
             * Highest priority among status messages — no alternation.
             * If connected, show connection icon on the left (same as waiting_for_temps). */
            const char* hydro_str = g_display_lang ? "CONNECT HYDROLINES" : "ПОДКЛЮЧИТЕ ГИДРОЛИНИИ";
            int hydro_px    = text_px_width(hydro_str);
            int hydro_gap   = 20;
            int hydro_cycle = hydro_px + hydro_gap;

            if (ble_on || usb_on) {
                const char* conn_txt = NULL;
                const uint8_t* conn_icon = NULL;
                if (ble_on) { conn_txt = g_display_lang ? "BT" : "БТ"; conn_icon = ico_bt; }
                else        { conn_txt = g_display_lang ? "USB" : "ЮСБ"; conn_icon = ico_usb; }
                int conn_w    = text_px_width(conn_txt);
                int left_zone = 5 + 2 + conn_w + 3;
                int x0 = left_zone - (hydro_scroll_px % hydro_cycle);
                oled_draw_text(x0,              ico_y, hydro_str);
                oled_draw_text(x0 + hydro_cycle, ico_y, hydro_str);
                oled_fb_fill_rect(0, ico_y, left_zone, 8, false);
                DRAW_ICON(0, ico_y, conn_icon, 1);
                oled_draw_text(5 + 2, ico_y, conn_txt);
            } else {
                int x0 = -(hydro_scroll_px % hydro_cycle);
                oled_draw_text(x0,              ico_y, hydro_str);
                oled_draw_text(x0 + hydro_cycle, ico_y, hydro_str);
            }
        } else if (active_err != 0 && err_blink_on) {
            /* Error state (non-loop errors; loop broken handled above as marquee).
             * err_blink_on half (500 ms): show ⚠ icon + error text.
             * err_blink_on=false half falls through to normal status (ПАУЗА/РАБОТА/etc.) */
            char etxt[20];
            const char* ebase = g_display_lang ? "ERROR " : "ОШИБКА ";
            int ebi = 0; const char* ep = ebase;
            while (*ep) etxt[ebi++] = *ep++;
            etxt[ebi++] = '0' + (char)active_err;
            etxt[ebi] = '\0';
            int etxt_chlen = g_display_lang ? 8 : 8;
            int etxt_w = etxt_chlen * 6;
            /* Small warning icon: ico_warn (5px wide) + 2px gap + text, centred */
            int total_err_w = 5 + 2 + etxt_w;
            int ex = (64 - total_err_w) / 2;
            if (ex < 0) ex = 0;
            DRAW_ICON(ex, ico_y, ico_warn, 1);
            oled_draw_text(ex + 5 + 2, ico_y, etxt);
        } else if (g_loopprot_enabled && g_loop_ok && g_lp_restore_ms != 0 &&
                   !g_system_running && g_was_running_before_loop_break) {
            /* Loop restored — countdown before rearm. "ПУСК N" in one line.
             * Show only if system WAS running before the loop broke;
             * if user was on pause, skip countdown silently. */
            int secs_left = LP_REARM_SECS - (int)((bc_now - g_lp_restore_ms) / 1000u);
            if (secs_left < 1) secs_left = 1;
            /* "ПУСК " (5 chars) + digit (1 char) = 6 × 6px = 36px, centred */
            char cntd[16];
            const char* pusk = g_display_lang ? "START " : "ПУСК ";
            int pusk_chlen = g_display_lang ? 6 : 5;
            int ci = 0; const char* cp = pusk;
            while (*cp) cntd[ci++] = *cp++;
            cntd[ci++] = '0' + (char)secs_left;
            cntd[ci] = '\0';
            int cntd_w = (pusk_chlen + 1) * 6;
            oled_draw_text((64 - cntd_w) / 2, ico_y, cntd);
        } else {
            /* Connection-first logic:
             * - If no connection -> show "ГОТОВ"
             * - Else (there is connection) -> show "ПАУЗА" or "РАБОТА" with conn icon/text
             */
            if (!ble_on && !usb_on) {
                /* No connection: icon + "READY"/"ГОТОВ" centred */
                const char* rtxt = g_display_lang ? "READY" : "ГОТОВ";
                int rtxt_w = text_px_width(rtxt);
                int total_w = 5 + 2 + rtxt_w;
                int rx = (64 - total_w) / 2;
                DRAW_ICON(rx, ico_y, ico_rdy, 1);
                oled_draw_text(rx + 7, ico_y, rtxt);
            } else {
                /* There is a connection: draw PAUSE or WORK with connection icon/text */
                const char* conn_txt = NULL;
                const uint8_t* conn_icon = NULL;
                if (ble_on) { conn_txt = g_display_lang ? "BT" : "БТ"; conn_icon = ico_bt; }
                else if (usb_on) { conn_txt = g_display_lang ? "USB" : "ЮСБ"; conn_icon = ico_usb; }
                int conn_w = conn_txt ? text_px_width(conn_txt) : 0;

                if (!g_system_running ||
                    (purge_ended_ms != 0 && (bc_now - purge_ended_ms) < PURGE_WORK_SUPPRESS_MS)) {
                    /* PAUSE: static label, show connection type next to it (no animation)
                     * Layout: [ICON][2px gap][CONN_TEXT][2px gap]["ПАУЗА"] or just "ПАУЗА" if no conn */
                    const char* ptxt = g_display_lang ? "PAUSE" : "ПАУЗА";
                    int ptxt_w = text_px_width(ptxt);
                    int total_w = conn_txt ? (5 + 2 + conn_w + 2 + ptxt_w) : ptxt_w;
                    int px = (64 - total_w) / 2;
                    if (px < 0) px = 0;

                    if (conn_txt) {
                        DRAW_ICON(px, ico_y, conn_icon, 1);
                        oled_draw_text(px + 5 + 2, ico_y, conn_txt);
                        oled_draw_text(px + 5 + 2 + conn_w + 2, ico_y, ptxt);
                    } else {
                        oled_draw_text(px, ico_y, ptxt);
                    }
                } else if (waiting_for_temps) {
                    /* WAITING FOR TARGET TEMPS: pixel-marquee scrolling text.
                     * Left zone: [ICON 5px][2px][CONN_TEXT][3px gap]  — static, drawn ON TOP of scroll.
                     * Scroll zone: everything to the right of left zone. */
                    const char* wt_str   = g_display_lang ? "WAITING TARGETS" : "ОЖИДАЮ ЦЕЛЕВЫЕ ТЕМПЕРАТУРЫ";
                    int wt_px            = text_px_width(wt_str);
                    int wt_gap           = 20;                    /* inter-copy gap for seamless wrap */
                    int wt_cycle         = wt_px + wt_gap;
                    /* Left static zone width: icon(5) + gap(2) + conn_text + padding(3) */
                    int left_zone = 5 + 2 + conn_w + 3;
                    /* Draw scrolling text first (may overlap left zone) */
                    int x0 = left_zone - (wait_scroll_px % wt_cycle);
                    oled_draw_text(x0,            ico_y, wt_str);
                    oled_draw_text(x0 + wt_cycle, ico_y, wt_str);
                    /* Clear left zone to black, then draw icon + label on top */
                    oled_fb_fill_rect(0, ico_y, left_zone, 8, false);
                    DRAW_ICON(0, ico_y, conn_icon, 1);
                    oled_draw_text(5 + 2, ico_y, conn_txt);
                } else {
                    /* WORK: static label, show connection type next to it (no animation)
                     * Layout: [ICON][2px gap][CONN_TEXT][2px gap]["РАБОТА"] or just "РАБОТА" if no conn */
                    const char* wtxt = g_display_lang ? "ACTIVE" : "РАБОТА";
                    int wtxt_w = text_px_width(wtxt);
                    int total_w_w = conn_txt ? (5 + 2 + conn_w + 2 + wtxt_w) : wtxt_w;
                    int pxw = (64 - total_w_w) / 2;
                    if (pxw < 0) pxw = 0;

                    if (conn_txt) {
                        DRAW_ICON(pxw, ico_y, conn_icon, 1);
                        oled_draw_text(pxw + 5 + 2, ico_y, conn_txt);
                        oled_draw_text(pxw + 5 + 2 + conn_w + 2, ico_y, wtxt);
                    } else {
                        oled_draw_text(pxw, ico_y, wtxt);
                    }
                }
            }
        }

        /* Advance load_frame every 94 ms by wall-clock, independent of loop speed.
         * This keeps ЗАГРУЗКА letter reveal rate constant even when the loop runs at 20 ms. */
        {
            uint32_t lf_now = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
            uint32_t lf_period = is_purging ? 125u : (is_connecting ? 125u : (is_ramping ? 62u : 94u));
            if ((lf_now - last_load_frame_ms) >= lf_period) {
                load_frame++;
                last_load_frame_ms += lf_period;
            }
        }

        oled_flush();
        /* During boot digit countdown or loading: refresh at 20 ms so every digit value
         * (99,98,97...) is rendered in its own frame. load_frame still advances at 94 ms
         * so ЗАГРУЗКА animation speed is unaffected. */
        /* Priority: boot/loading → 20 ms; purging → 125 ms; connecting → 125 ms
         * (is_connecting takes priority over is_conn_anim so ПОДКЛЮЧАЮ speed is stable);
         * digit connect-in anim → 20 ms; ramping → 62 ms; idle → 500 ms. */
        vTaskDelay(pdMS_TO_TICKS((is_loading || is_boot_countdown) ? 20 : (is_purging ? 125 : (is_connecting ? 125 : (is_conn_anim ? 20 : (is_ramping ? 62 : ((e5 || waiting_for_temps) ? 20 : 500)))))));
    }

    #undef DRAW_CHAR_S
    #undef DRAW_TEXT_S
    #undef DRAW_INT_S
    #undef DRAW_INT_ZP_S
    #undef DRAW_ICON
    #undef ERR_BLINK_HALF_MS
    #undef CONNECTING_SHOW_MS
    #undef PURGE_WORK_SUPPRESS_MS
}

/* ===== Valve (solenoid) control ===== */
static inline void valve_init(void){
    /* Redirect legacy init to PWM init */
    valve_pwm_init();
    valve_pwm_set_percent(0.0f);
}
/* Deprecated: binary valve control (use valve_pwm_set_percent instead) */
static inline void valve_set(bool active){
    /* Legacy fallback: map true->100%, false->0% via PWM for consistency */
    if (!g_pwm_valve_attached) valve_pwm_init();
    if (active) valve_pwm_set_percent(100.0f); else valve_pwm_set_percent(0.0f);
}

/* ===== Valve PWM (soft close/open) ===== */
static void valve_pwm_init(void){
    if (g_pwm_valve_attached) return;
    /* Keep pulldown for safety */
    gpio_set_pull_mode((gpio_num_t)VALVE_GPIO, GPIO_PULLDOWN_ONLY);
#if defined(GPIO_PULLDOWN_ENABLE) || defined(gpio_pulldown_en)
    gpio_pulldown_en((gpio_num_t)VALVE_GPIO);
#endif
    /* Configure dedicated LEDC timer/channel for the valve */
    ledc_timer_config_t t_valve={ .speed_mode=LEDC_HIGH_SPEED_MODE, .duty_resolution=LEDC_TIMER_RES,
                                  .timer_num=LEDC_TIMER_2, .freq_hz=LEDC_VALVE_FREQ_HZ, .clk_cfg=LEDC_AUTO_CLK };
    esp_err_t err = ledc_timer_config(&t_valve);
    if (err != ESP_OK) { ESP_LOGE(TAG, "VALVE: timer_config err=%s", esp_err_to_name(err)); return; }
    ledc_channel_config_t c_valve={ .gpio_num=VALVE_GPIO, .speed_mode=LEDC_HIGH_SPEED_MODE,
                                    .channel=LEDC_CHANNEL_2, .intr_type=LEDC_INTR_DISABLE,
                                    .timer_sel=LEDC_TIMER_2, .duty=0, .hpoint=0 };
    err = ledc_channel_config(&c_valve);
    if (err != ESP_OK) { ESP_LOGE(TAG, "VALVE: channel_config err=%s", esp_err_to_name(err)); return; }
    (void)ledc_stop(LEDC_HIGH_SPEED_MODE, LEDC_CHANNEL_2, 0);
    g_pwm_valve_attached = true;
}

static void valve_pwm_set_percent(float pct){
    float p = clampf(pct, 0.0f, 100.0f);
    if (!g_pwm_valve_attached){
        valve_pwm_init();
    }
    /* Во время продувки forced-stop НЕ блокирует клапан */
    if (!g_purge_active){
        uint32_t now_ms_local = (uint32_t)(xTaskGetTickCount()*portTICK_PERIOD_MS);
        if (g_forced_stop_deadline_ms && now_ms_local < g_forced_stop_deadline_ms){
            ledc_stop(LEDC_HIGH_SPEED_MODE, LEDC_CHANNEL_2, 0);
            return;
        }
    }
    if (p <= 0.0f){
        /* fully open to water (inactive) */
        ledc_stop(LEDC_HIGH_SPEED_MODE, LEDC_CHANNEL_2, 0);
        return;
    }
    esp_err_t err;
    err = ledc_timer_resume(LEDC_HIGH_SPEED_MODE, LEDC_TIMER_2);
    if (err != ESP_OK) { ESP_LOGW(TAG, "VALVE: timer_resume err=%s", esp_err_to_name(err)); return; }
    uint32_t duty=(uint32_t)lroundf((p/100.0f)*LEDC_DUTY_MAX);
    err = ledc_set_duty(LEDC_HIGH_SPEED_MODE, LEDC_CHANNEL_2, duty);
    if (err != ESP_OK) { ESP_LOGW(TAG, "VALVE: set_duty err=%s", esp_err_to_name(err)); return; }
    err = ledc_update_duty(LEDC_HIGH_SPEED_MODE, LEDC_CHANNEL_2);
    if (err != ESP_OK) { ESP_LOGW(TAG, "VALVE: update_duty err=%s", esp_err_to_name(err)); }
}

/* ===== Loop protection monitor ===== */
static void loopprot_task(void *arg){
    (void)arg;
    TickType_t last = xTaskGetTickCount();
    const TickType_t step = pdMS_TO_TICKS(50); /* 20 Hz toggle */
    /* Новый надёжный детектор: считаем количество изменений входа за окно из 10 тактов (~500 мс).
       Целая петля: вход меняется почти на каждом такте (>=8 из 10). Разрыв: вход почти постоянен (<=1 из 10). */
    bool last_in = gpio_get_level((gpio_num_t)LOOP_IN_GPIO) ? true : false;
    uint8_t win = 0, edges = 0;
    for(;;){
        bool drive = !g_loop_last_drive;
        gpio_set_level((gpio_num_t)LOOP_OUT_GPIO, drive?1:0);
        g_loop_last_drive = drive;
        bool in = gpio_get_level((gpio_num_t)LOOP_IN_GPIO) ? true : false;
        if (in != last_in) { edges++; last_in = in; }
        if (++win >= 10){
            if (edges <= 1){
                if (g_loop_ok){
                    g_loop_ok = false;
                    g_lp_restore_ms = 0;   /* cancel any rearm countdown */
                    g_was_running_before_loop_break = g_system_running; /* remember if user was in РАБОТА */
                    ESP_LOGW(TAG, "LOOP: broken (was_running=%d)", (int)g_was_running_before_loop_break);
                    /* notify clients about status change */
                    #if CONFIG_BT_NIMBLE_ENABLED
                    if (g_ble_connected && g_loop_stat_val_handle){
                        uint8_t code = g_loopprot_enabled ? 2 : 0;
                        struct os_mbuf* om = ble_hs_mbuf_from_flat(&code, 1);
                        if (om) {
                            int rc = ble_gatts_notify_custom(g_conn_handle, g_loop_stat_val_handle, om);
                            if (rc != 0) ESP_LOGW(TAG, "LOOP notify(broken) rc=%d", rc);
                        }
                    }
                    #endif
                    /* UART parity: send loop status over USB too */
                    if (g_usb_connected) {
                        uart_send_ls(g_loopprot_enabled ? 2 : 0);
                    }
                    if (g_loopprot_enabled){
                        /* Defer heavy STOP to control_task (avoid stack overflow here) */
                        g_system_running = false;
                        g_stop_pending = true;
                        g_pump_boost_armed  = false; /* prevent stale boost on auto-rearm */
                        if (g_purge_active) purge_stop();
                    }
                }
            } else if (edges >= 8){
                if (!g_loop_ok){
                    g_loop_ok = true;
                    g_lp_restore_ms = g_was_running_before_loop_break
                                      ? (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS)
                                      : 0; /* no countdown if user was on pause */
                    ESP_LOGI(TAG, "LOOP: restored (was_running=%d), rearm %s",
                             (int)g_was_running_before_loop_break,
                             g_lp_restore_ms ? "countdown" : "skip");
                    /* notify clients about status change.
                     * code 3 = loop restored AND system was running before break
                     *           (tells app to auto-start with countdown)
                     * code 1 = loop restored, system was on pause (no auto-start) */
                    #if CONFIG_BT_NIMBLE_ENABLED
                    if (g_ble_connected && g_loop_stat_val_handle){
                        uint8_t code;
                        if (!g_loopprot_enabled) code = 0;
                        else code = g_was_running_before_loop_break ? 3 : 1;
                        struct os_mbuf* om = ble_hs_mbuf_from_flat(&code, 1);
                        if (om) {
                            int rc = ble_gatts_notify_custom(g_conn_handle, g_loop_stat_val_handle, om);
                            if (rc != 0) ESP_LOGW(TAG, "LOOP notify(restored) rc=%d code=%d", rc, (int)code);
                        }
                    }
                    #endif
                    /* UART parity: send loop status over USB too */
                    if (g_usb_connected) {
                        uint8_t code;
                        if (!g_loopprot_enabled) code = 0;
                        else code = g_was_running_before_loop_break ? 3 : 1;
                        uart_send_ls(code);
                    }
                }
            }
            win = 0; edges = 0;
        }

        /* Auto-rearm: after LP_REARM_SECS, restart system if it was running before loop broke */
        if (g_lp_restore_ms != 0 && g_loop_ok && g_was_running_before_loop_break && !g_system_running) {
            uint32_t elapsed = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS) - g_lp_restore_ms;
            if (elapsed >= (uint32_t)(LP_REARM_SECS * 1000)) {
                ESP_LOGI(TAG, "LOOP: auto-rearm after %d s", LP_REARM_SECS);
                g_fan_last_filt = NAN; g_pump_last_filt = NAN;
                g_fan_last_appl = NAN; g_pump_last_appl = 0.0f;
                /* NOTE: do NOT set g_start_pending here — it triggers NVS boost
                 * check in control_task, causing unwanted RAMP after loop restore.
                 * Boost/RAMP should only happen after purge → SP → ST sequence. */
                g_lp_restore_ms = 0;
                g_was_running_before_loop_break = false;
                g_system_running = true;
                /* Notify app that auto-rearm completed: code 4 = "system auto-started".
                 * App should force its button to РАБОТА immediately (no own countdown). */
                #if CONFIG_BT_NIMBLE_ENABLED
                if (g_ble_connected && g_loop_stat_val_handle){
                    uint8_t code = 4;
                    struct os_mbuf* om = ble_hs_mbuf_from_flat(&code, 1);
                    if (om) {
                        int rc = ble_gatts_notify_custom(g_conn_handle, g_loop_stat_val_handle, om);
                        if (rc != 0) ESP_LOGW(TAG, "LOOP notify(auto-rearm) rc=%d", rc);
                    }
                }
                #endif
                if (g_usb_connected) {
                    uart_send_ls(4);
                }
            }
        }

        vTaskDelayUntil(&last, step);
    }
}
