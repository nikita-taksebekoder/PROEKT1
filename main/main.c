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
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "led_strip.h"  // WS2812

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

/* BLE UUIDs */
#define FAN_SERVICE_UUID     0xFFE0
#define TEMP_CHAR_UUID       0xFFE1
#define FAN_CFG_CHAR_UUID    0xFFE2
#define LED_CHAR_UUID        0xFFE3
#define PUMP_CFG_CHAR_UUID   0xFFE4
#define RPM_CHAR_UUID        0xFFE5  /* RPM read/notify */

/* GPIO */
#define LED_GPIO             2
#define FAN_PWM_GPIO         16
#define PUMP_PWM_GPIO        17

/* Tachometer GPIOs */
#define TACH1_GPIO           18
#define TACH2_GPIO           19

/* Tachometer model:
   - Мы считаем только спадающие фронты (NEGEDGE).
   - Для типичных PC-вентиляторов 2 импульса на оборот. Но в реальности счётчик может завышать из-за «дребезга».
   - Поэтому ниже добавлена КАЛИБРОВКА по коэффициенту (scale) и ограничение max, чтобы не превышать паспортные значения. */
#define TACH_PULSES_PER_REV  2

/* Паспортные ограничения и калибровка (подогнаны по вашим данным):
   Пример: при 100% PWM видим около 3000 raw RPM, а паспорт — 1800 => scale ≈ 1800/3000 = 0.60
   По вашим последним данным среднее ~2850 => 1800/2850 ≈ 0.63
   Возьмём 0.63 как базовый масштаб для обоих каналов. При необходимости подстройте отдельно. */
#define FAN1_RPM_SCALE   0.63f
#define FAN2_RPM_SCALE   0.63f
#define FAN1_RPM_MAX     1800
#define FAN2_RPM_MAX     1800
/* По желанию можно добавить нижнюю границу отображения (паспорт 150), но мы НЕ будем «подтягивать» вверх,
   чтобы видеть реальные низкие значения. Поэтому MIN оставим 0. */
#define FAN1_RPM_MIN     0
#define FAN2_RPM_MIN     0

/* Порог аварии (после калибровки) */
#define RPM_FAULT_MIN        100  /* если подаём >1%, а RPM ниже 100 — считаем «авария» */

/* WS2812 */
#define LED_STRIP_GPIO       4
#define LED_STRIP_LENGTH     20
#define LED_STRIP_RES_HZ     (10 * 1000 * 1000)
#define LED_BRIGHT_DEF       64

/* Ranges */
#define TEMP_MIN_C           30.0f
#define TEMP_MAX_C           110.0f
#define SPEED_MIN_PCT        0.0f
#define SPEED_MAX_PCT        100.0f
#define CURVE_POINTS_MAX     16

/* Control and PWM */
#define CTRL_PERIOD_MS       200
#define LEDC_FREQ_HZ         25000
#define LEDC_TIMER_RES       LEDC_TIMER_10_BIT
#define LEDC_DUTY_MAX        ((1U << 10) - 1)

/* Defaults */
#define DEF_INTERP_MODE      1        /* 0=linear, 1=spline */
#define DEF_SOURCE_MODE      2        /* 0=CPU, 1=GPU, 2=MAX */
#define DEF_RC_TAU_SEC       1.5f
#define DEF_HYST_PCT         2.0f
#define STALE_MS             5000

/* Fan specifics */
#define FAN_MIN_ON_PCT       30.0f
#define OFF_BELOW_FIRST_PT

/* Pump voltage limits */
#define PUMP_SUPPLY_V        12.0f
#define PUMP_V_MIN           2.0f
#define PUMP_V_MAX           5.0f

/* Diagnostics */
#define FAN_PWM_INVERT       0
#define PUMP_PWM_INVERT      0
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
static uint16_t g_temp_val_handle = 0;
static uint16_t g_fan_cfg_val_handle = 0;
static uint16_t g_pump_cfg_val_handle = 0;
static uint16_t g_rpm_val_handle = 0; /* RPM notify/read */
#endif

static volatile int32_t g_cpu_temp_c = -1000;
static volatile int32_t g_gpu_temp_c = -1000;
static volatile uint32_t g_last_temp_ms = 0;

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

/* Tachometer */
static volatile uint32_t g_tach1_edges = 0;
static volatile uint32_t g_tach2_edges = 0;
/* Храним уже КАЛИБРОВАННЫЕ RPM (после scale и clamp) */
static int32_t g_rpm1 = 0, g_rpm2 = 0;
static uint32_t g_rpm_flags = 0; /* bit0: fan1 fault, bit1: fan2 fault */
#define RPM_FLAG_F1 0x01
#define RPM_FLAG_F2 0x02

/* NVS namespaces */
#define NVS_NS_FAN   "fan"
#define NVS_KEY_FAN  "cfg_v1"
#define NVS_NS_PUMP  "pump"
#define NVS_KEY_PUMP "cfg_v1"
#define NVS_NS_LED   "led"
#define NVS_KEY_LED  "prof_v1"

/* ===== Forward decls ===== */
static void fan_pwm_init(void);
static void fan_pwm_set_percent(float pct);
static void pump_pwm_set_percent(float pct);

static void control_task(void *arg);
static void led_task(void *arg);
static void uart_rx_task(void *arg);
static void uart_init(void);

static void tach_init(void);
static void tach_sample_and_publish(uint32_t interval_ms);

static void uart_send_rp(int32_t rpm1, int32_t rpm2, uint32_t flags); /* UART RP TX */

#if CONFIG_BT_NIMBLE_ENABLED
static void start_advertising(void);
static void on_reset(int reason);
static void on_sync(void);
static void host_task(void *);
static esp_err_t ble_stack_init_manual(void);
#endif

/* ===== Utils ===== */
static inline float clampf(float x, float a, float b){ if(x<a) return a; if(x>b) return b; return x; }
static inline uint8_t clampu8(int v){ if(v<0) return 0; if(v>255) return 255; return (uint8_t)v; }

static float fan_apply_min_floor(float s){
    if (s > 0.0f && s < FAN_MIN_ON_PCT) return FAN_MIN_ON_PCT;
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
    return for_fan?fan_apply_min_floor(s):s;
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

static void leds_apply_rgb(uint8_t r,uint8_t g,uint8_t b){
    if (!g_led_strip) { ESP_LOGW(TAG, "LED strip not initialized"); return; }
    ESP_LOGI(TAG, "Setting all LEDs to r=%u g=%u b=%u", r, g, b);
    for(int i=0;i<LED_STRIP_LENGTH;++i) (void)led_strip_set_pixel(g_led_strip,i,r,g,b);
    esp_err_t err = led_strip_refresh(g_led_strip);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "led_strip_refresh failed: %d", err);
    } else {
        ESP_LOGI(TAG, "LED strip refreshed successfully");
    }
}

static void leds_apply_solid(uint8_t r,uint8_t g,uint8_t b,uint8_t br){
    ESP_LOGI(TAG, "Applying solid LED: r=%u g=%u b=%u br=%u", r, g, b, br);
    leds_apply_rgb(scale_bright(r,br),scale_bright(g,br),scale_bright(b,br));
}

static void leds_apply_custom(void){
    if (!g_led_strip) return;
    ESP_LOGI(TAG, "Applying custom LED colors");
    for(int i=0;i<LED_STRIP_LENGTH;++i){
        uint8_t r_raw = g_led_prof.custom_colors[i][0];
        uint8_t g_raw = g_led_prof.custom_colors[i][1];
        uint8_t b_raw = g_led_prof.custom_colors[i][2];
        uint8_t r = scale_bright(r_raw, g_led_prof.brightness);
        uint8_t g = scale_bright(g_raw, g_led_prof.brightness);
        uint8_t b = scale_bright(b_raw, g_led_prof.brightness);
        ESP_LOGI(TAG, "LED[%d]: raw=(%u,%u,%u) scaled=(%u,%u,%u)", i, r_raw, g_raw, b_raw, r, g, b);
        (void)led_strip_set_pixel(g_led_strip,i,r,g,b);
    }
    (void)led_strip_refresh(g_led_strip);
}

static void leds_off(void){
    if (!g_led_strip) return;
    (void)led_strip_clear(g_led_strip);
    (void)led_strip_refresh(g_led_strip);
}

static void leds_init(void){
    if (g_led_strip) return;
    led_strip_config_t strip_config={
        .strip_gpio_num=LED_STRIP_GPIO,
        .max_leds=LED_STRIP_LENGTH,
        .led_model=LED_MODEL_WS2812,
        .flags.invert_out=false,
    };
    led_strip_rmt_config_t rmt_config={
        .clk_src=RMT_CLK_SRC_DEFAULT,
        .resolution_hz=LED_STRIP_RES_HZ,
        .mem_block_symbols=0,
        .flags.with_dma=false,
    };
    esp_err_t err=led_strip_new_rmt_device(&strip_config,&rmt_config,&g_led_strip);
    if (err!=ESP_OK){ ESP_LOGE(TAG,"led_strip_new_rmt_device failed: %d",err); g_led_strip=NULL; return; }
    leds_off();
    ESP_LOGI(TAG,"LED strip initialized on GPIO %d, leds=%d",LED_STRIP_GPIO,LED_STRIP_LENGTH);
    // ...existing code...
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
        if (nvs_get_blob(h,NVS_KEY_LED,&g_led_prof,&len)==ESP_OK && len==sizeof(g_led_prof) && g_led_prof.version == 1){
            ESP_LOGI(TAG,"LED profile loaded: mode=%u, rgb=(%u,%u,%u), br=%u",
                     g_led_prof.mode,g_led_prof.r,g_led_prof.g,g_led_prof.b,g_led_prof.brightness);
            loaded = true;
        }
        nvs_close(h);
    }
    if (loaded) {
        g_led_dirty = true;
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

/* ===== Pump PWM ===== */
static void pump_pwm_set_percent(float pct){
    float s=clampf(pct,0.0f,100.0f);
#if PUMP_PWM_INVERT
    /* optional invert */
#endif
    if (s<=0.0f){ ledc_stop(LEDC_LOW_SPEED_MODE,LEDC_CHANNEL_1,0); return; }
    float v=(PUMP_V_MAX)*(s/100.0f);
    if (v>0.0f && v<PUMP_V_MIN) v=PUMP_V_MIN;
    float duty_frac=clampf(v/PUMP_SUPPLY_V,0.0f,1.0f);
#if PUMP_PWM_INVERT
    duty_frac = 1.0f - duty_frac;
#endif
    ESP_ERROR_CHECK(ledc_timer_resume(LEDC_LOW_SPEED_MODE,LEDC_TIMER_0));
    uint32_t duty=(uint32_t)lroundf(duty_frac*(float)LEDC_DUTY_MAX);
    ESP_ERROR_CHECK(ledc_set_duty(LEDC_LOW_SPEED_MODE,LEDC_CHANNEL_1,duty));
    ESP_ERROR_CHECK(ledc_update_duty(LEDC_LOW_SPEED_MODE,LEDC_CHANNEL_1));
}

/* ===== Fan PWM ===== */
static void fan_pwm_init(void){
    ledc_timer_config_t t={ .speed_mode=LEDC_LOW_SPEED_MODE, .duty_resolution=LEDC_TIMER_RES,
                            .timer_num=LEDC_TIMER_0, .freq_hz=LEDC_FREQ_HZ, .clk_cfg=LEDC_AUTO_CLK };
    ESP_ERROR_CHECK(ledc_timer_config(&t));
    ledc_channel_config_t c_fan={ .gpio_num=FAN_PWM_GPIO, .speed_mode=LEDC_LOW_SPEED_MODE,
                                  .channel=LEDC_CHANNEL_0, .intr_type=LEDC_INTR_DISABLE,
                                  .timer_sel=LEDC_TIMER_0, .duty=0, .hpoint=0 };
    ESP_ERROR_CHECK(ledc_channel_config(&c_fan));
    ledc_channel_config_t c_pump={ .gpio_num=PUMP_PWM_GPIO, .speed_mode=LEDC_LOW_SPEED_MODE,
                                   .channel=LEDC_CHANNEL_1, .intr_type=LEDC_INTR_DISABLE,
                                   .timer_sel=LEDC_TIMER_0, .duty=0, .hpoint=0 };
    ESP_ERROR_CHECK(ledc_channel_config(&c_pump));
    ESP_ERROR_CHECK(ledc_stop(LEDC_LOW_SPEED_MODE,LEDC_CHANNEL_0,0));
    ESP_ERROR_CHECK(ledc_stop(LEDC_LOW_SPEED_MODE,LEDC_CHANNEL_1,0));
}

static void fan_pwm_set_percent(float pct){
    float p=clampf(pct,0.0f,100.0f);
#if FAN_PWM_INVERT
    p = 100.0f - p;
#endif
    if (p<=0.0f){ ledc_stop(LEDC_LOW_SPEED_MODE,LEDC_CHANNEL_0,0); return; }
    ESP_ERROR_CHECK(ledc_timer_resume(LEDC_LOW_SPEED_MODE,LEDC_TIMER_0));
    uint32_t duty=(uint32_t)lroundf((p/100.0f)*LEDC_DUTY_MAX);
    ESP_ERROR_CHECK(ledc_set_duty(LEDC_LOW_SPEED_MODE,LEDC_CHANNEL_0,duty));
    ESP_ERROR_CHECK(ledc_update_duty(LEDC_LOW_SPEED_MODE,LEDC_CHANNEL_0));
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
    if (total<8) return false;
    if (!(buf[0]=='L' && buf[1]=='X')) return false;
    uint8_t ver=buf[2]; if (ver!=1) return false;
    uint8_t mode=buf[3], brightness=buf[4];
    if (!g_led_strip) leds_init();
    g_led_prof.version=1;
    if (mode == LED_MODE_CUSTOM) {
        if (total < 5 + sizeof(g_led_prof.custom_colors)) return false;
        g_led_prof.mode = mode;
        g_led_prof.brightness = brightness;
        memcpy(g_led_prof.custom_colors, &buf[5], sizeof(g_led_prof.custom_colors));
    } else if (mode == LED_MODE_GRADIENT_ANIM) {
        if (total < 12) return false;
        g_led_prof.mode = mode;
        g_led_prof.brightness = brightness;
        g_led_prof.start_r = buf[5]; g_led_prof.start_g = buf[6]; g_led_prof.start_b = buf[7];
        g_led_prof.end_r = buf[8]; g_led_prof.end_g = buf[9]; g_led_prof.end_b = buf[10];
        g_led_prof.anim_speed = buf[11];
        ESP_LOGI(TAG,"LED gradient anim set: start=(%u,%u,%u) end=(%u,%u,%u) speed=%u br=%u", g_led_prof.start_r, g_led_prof.start_g, g_led_prof.start_b, g_led_prof.end_r, g_led_prof.end_g, g_led_prof.end_b, g_led_prof.anim_speed, g_led_prof.brightness);
    } else {
        g_led_prof.mode = (mode<=LED_MODE_BREATHE)?mode:LED_MODE_SOLID;
        g_led_prof.brightness = brightness;
        g_led_prof.r = buf[5]; g_led_prof.g = buf[6]; g_led_prof.b = buf[7];
    }
    led_prof_save(); g_led_dirty=true;
    // Apply immediately for solid mode
    if (g_led_prof.mode == LED_MODE_SOLID) {
        leds_apply_solid(g_led_prof.r, g_led_prof.g, g_led_prof.b, g_led_prof.brightness);
    }
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
    if (ver!=1 || n<2 || n>CURVE_POINTS_MAX) return false;
    size_t need=6 + n*3; if (total<need) return false;
    curve_cfg_t nc=*dst;
    nc.version=1;
    nc.source_mode=(src<=2)?src:DEF_SOURCE_MODE;
    nc.interp_mode=(mode<=1)?mode:DEF_INTERP_MODE;
    nc.count=n;
    const uint8_t* p=&buf[6];
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

/* ===== Tachometer ===== */
static void IRAM_ATTR tach_isr(void* arg){
    intptr_t id = (intptr_t)arg;
    if (id == 1) { g_tach1_edges++; }
    else         { g_tach2_edges++; }
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
    int32_t rpm1_cal = rpm_apply_calibrate_clamp(rpm1_raw, FAN1_RPM_SCALE, FAN1_RPM_MIN, FAN1_RPM_MAX);
    int32_t rpm2_cal = rpm_apply_calibrate_clamp(rpm2_raw, FAN2_RPM_SCALE, FAN2_RPM_MIN, FAN2_RPM_MAX);

    g_rpm1 = rpm1_cal;
    g_rpm2 = rpm2_cal;

    /* Проверяем grace period при запуске системы (5 секунд) */
    uint32_t now = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
    bool startup_grace_period = (now - g_system_startup_ms) < 5000;

    /* Флаги «авария» проверяем по калиброванным значениям */
    uint32_t flags = 0;
    if ((g_ble_connected || g_usb_connected) && !startup_grace_period && g_fan_last_appl > 1.0f && g_rpm1 < RPM_FAULT_MIN) flags |= RPM_FLAG_F1;
    if ((g_ble_connected || g_usb_connected) && !startup_grace_period && g_pump_last_appl > 1.0f && g_rpm2 < RPM_FAULT_MIN) flags |= RPM_FLAG_F2;
    g_rpm_flags = flags;

#if RPM_CAL_LOG
    ESP_LOGI(TAG, "RPM RAW: f1=%ld f2=%ld  -> CAL: f1=%ld f2=%ld  flags=0x%02X (dt=%.2fs)",
             (long)rpm1_raw, (long)rpm2_raw, (long)g_rpm1, (long)g_rpm2, (unsigned)g_rpm_flags, seconds);
#elif RPM_LOG_ENABLE
    ESP_LOGI(TAG, "RPM: fan1=%ld fan2=%ld flags=0x%02X", (long)g_rpm1, (long)g_rpm2, (unsigned)g_rpm_flags);
#endif

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
    uint16_t total=OS_MBUF_PKTLEN(ctxt->om); if (total>256) total=256;
    uint8_t buf[256]; os_mbuf_copydata(ctxt->om,0,total,buf);
    (void)apply_fc_bytes(buf,total); return 0;
}

static int pump_cfg_write_cb(uint16_t, uint16_t, struct ble_gatt_access_ctxt *ctxt, void *){
    if (ctxt->op!=BLE_GATT_ACCESS_OP_WRITE_CHR) return BLE_ATT_ERR_UNLIKELY;
    uint16_t total=OS_MBUF_PKTLEN(ctxt->om); if (total>256) total=256;
    uint8_t buf[256]; os_mbuf_copydata(ctxt->om,0,total,buf);
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

static int led_write_cb(uint16_t, uint16_t, struct ble_gatt_access_ctxt *ctxt, void *){
    if (ctxt->op!=BLE_GATT_ACCESS_OP_WRITE_CHR) return BLE_ATT_ERR_UNLIKELY;
    uint16_t total=OS_MBUF_PKTLEN(ctxt->om); if (total>256) total=256;
    uint8_t buf[256]; os_mbuf_copydata(ctxt->om,0,total,buf);
    if (total>=2 && buf[0]=='L' && buf[1]=='X'){ (void)apply_lx_bytes(buf,total); return 0; }
    if (!g_led_strip) leds_init();
    if (total==4){
        g_led_prof.version=1; g_led_prof.mode=LED_MODE_SOLID;
        g_led_prof.r=buf[0]; g_led_prof.g=buf[1]; g_led_prof.b=buf[2]; g_led_prof.brightness=buf[3];
        led_prof_save(); g_led_dirty=true;
    } else if (total==3){
        g_led_prof.version=1; g_led_prof.mode=LED_MODE_SOLID;
        g_led_prof.r=buf[0]; g_led_prof.g=buf[1]; g_led_prof.b=buf[2];
        led_prof_save(); g_led_dirty=true;
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

/* GATT service (RPM characteristic added) */
static const struct ble_gatt_svc_def gatt_svcs[] = {
    { .type=BLE_GATT_SVC_TYPE_PRIMARY, .uuid=BLE_UUID16_DECLARE(FAN_SERVICE_UUID),
      .characteristics=(struct ble_gatt_chr_def[]){
          { .uuid=BLE_UUID16_DECLARE(TEMP_CHAR_UUID),     .access_cb=temp_write_cb,     .flags=BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_NO_RSP },
          { .uuid=BLE_UUID16_DECLARE(FAN_CFG_CHAR_UUID),  .access_cb=fan_cfg_write_cb,  .flags=BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_NO_RSP },
          { .uuid=BLE_UUID16_DECLARE(LED_CHAR_UUID),      .access_cb=led_write_cb,      .flags=BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_NO_RSP },
          { .uuid=BLE_UUID16_DECLARE(PUMP_CFG_CHAR_UUID), .access_cb=pump_cfg_write_cb, .flags=BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_NO_RSP },
          { .uuid=BLE_UUID16_DECLARE(RPM_CHAR_UUID),      .access_cb=rpm_read_cb,       .flags=BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_NOTIFY },
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
                /* record connection start time for 10s post-connection grace */
                g_conn_start_ms = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
            } else {
                struct ble_gap_adv_params advp={0}; advp.conn_mode=BLE_GAP_CONN_MODE_UND; advp.disc_mode=BLE_GAP_DISC_MODE_GEN;
                ble_gap_adv_start(own_addr_type,NULL,BLE_HS_FOREVER,&advp,gap_event,NULL);
            }
            return 0;
                case BLE_GAP_EVENT_DISCONNECT:
                        ESP_LOGI(TAG,"Disconnect; reason=%d", event->disconnect.reason);
                        g_conn_handle=0; g_ble_connected=false; gpio_set_level(LED_GPIO,0);
                        g_fan_last_filt=g_pump_last_filt=NAN; g_fan_last_appl=g_pump_last_appl=0.0f;
                        /* clear connection start timestamp */
                        g_conn_start_ms = 0;
                        fan_pwm_set_percent(0.0f); pump_pwm_set_percent(0.0f);
                        if (!g_ble_connected && !g_usb_connected) {
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

    /* Always release Classic BT memory for BLE-only */
    e = esp_bt_controller_mem_release(ESP_BT_MODE_CLASSIC_BT);
    if (e != ESP_OK && e != ESP_ERR_INVALID_STATE) {
        ESP_LOGE(TAG, "mem_release(CLASSIC_BT) failed: %s", esp_err_to_name(e));
        return e;
    }

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

static int sp_try_tt(const uint8_t* d,size_t l,size_t* used){
    if (l < 10) return 0;
    if (!(d[0]=='T' && d[1]=='T')){ *used=1; return -1; }
    int32_t cpu=(int32_t)((uint32_t)d[2] | ((uint32_t)d[3]<<8) | ((uint32_t)d[4]<<16) | ((uint32_t)d[5]<<24));
    int32_t gpu=(int32_t)((uint32_t)d[6] | ((uint32_t)d[7]<<8) | ((uint32_t)d[8]<<16) | ((uint32_t)d[9]<<24));
    g_cpu_temp_c=cpu; g_gpu_temp_c=gpu;
    uint32_t now_ms = (uint32_t)(xTaskGetTickCount()*portTICK_PERIOD_MS);
    g_last_temp_ms = now_ms;
    if (!g_usb_connected) {
        /* first time USB appears — record connection start for 10s grace */
        g_conn_start_ms = now_ms;
    }
    g_usb_connected = true;
    g_last_usb_ms = now_ms;
    *used=10; return 1;
}

static int sp_try_fc(const uint8_t* d,size_t l,size_t* used){
    if (l < 6) return 0;
    if (!(d[0]=='F' && d[1]=='C')){ *used=1; return -1; }
    uint8_t n=d[5]; size_t need=6 + (size_t)n*3;
    if (n<2 || n>CURVE_POINTS_MAX){ *used=2; return -1; }
    if (l < need) return 0;
    (void)apply_fc_bytes(d,(uint16_t)need);
    *used=need; return 1;
}

static int sp_try_pc(const uint8_t* d,size_t l,size_t* used){
    if (l < 6) return 0;
    if (!(d[0]=='P' && d[1]=='C')){ *used=1; return -1; }
    uint8_t n=d[5]; size_t need=6 + (size_t)n*3;
    if (n<2 || n>CURVE_POINTS_MAX){ *used=2; return -1; }
    if (l < need) return 0;
    (void)apply_pc_bytes(d,(uint16_t)need);
    *used=need; return 1;
}

static int sp_try_lx(const uint8_t* d,size_t l,size_t* used){
    if (l < 8) return 0;
    if (!(d[0]=='L' && d[1]=='X')){ *used=1; return -1; }
    (void)apply_lx_bytes(d,8);
    *used=8; return 1;
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
    ESP_ERROR_CHECK(uart_driver_install(UART_PORT,UART_RX_BUF_HW,UART_TX_BUF_HW,0,NULL,0));
    ESP_ERROR_CHECK(uart_param_config(UART_PORT,&cfg));
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
            ESP_LOGI(TAG, "CTRL: USB timeout - disconnected");
            if (!g_ble_connected && !g_usb_connected) {
                ESP_LOGI(TAG, "LED off due to USB timeout");
                leds_off();
            }
        }
        bool fresh=(g_last_temp_ms!=0) && (now-g_last_temp_ms<=STALE_MS);
        if(!fresh){
            if(isnan(g_fan_last_appl) || g_fan_last_appl!=0.0f || isnan(g_pump_last_appl) || g_pump_last_appl!=0.0f){
                g_fan_last_appl=g_pump_last_appl=0.0f; g_fan_last_filt=g_pump_last_filt=0.0f;
                fan_pwm_set_percent(0.0f); pump_pwm_set_percent(0.0f);
                ESP_LOGI(TAG,"CTRL: no fresh temps - out=0%%");
            } else if (now-last_dbg>2000){ ESP_LOGI(TAG,"CTRL: waiting temps (BLE/USB)"); last_dbg=now; }
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
            if(!isnan(tC_pump)){
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
    const TickType_t step_ticks=pdMS_TO_TICKS(50);
    leds_init(); g_led_dirty=true; TickType_t start=xTaskGetTickCount();
    for(;;){
        if (!g_ble_connected && !g_usb_connected) {
            leds_off();
            vTaskDelay(step_ticks);
            continue;
        }
        if(g_led_dirty){
            g_led_dirty=false;
            if(g_led_prof.mode==LED_MODE_OFF) leds_off();
            else if(g_led_prof.mode==LED_MODE_SOLID) leds_apply_solid(g_led_prof.r,g_led_prof.g,g_led_prof.b,g_led_prof.brightness);
            else if(g_led_prof.mode==LED_MODE_CUSTOM) leds_apply_custom();
            start=xTaskGetTickCount();
        }
        led_mode_t mode=(led_mode_t)g_led_prof.mode;
        TickType_t now=xTaskGetTickCount();
        float elapsed=(float)(now-start)/(float)configTICK_RATE_HZ;
        if(mode==LED_MODE_BLINK){
            float phase=fmodf(elapsed,blink_period);
            bool on=(phase<(blink_period*0.5f));
            uint8_t br=on?g_led_prof.brightness:0;
            leds_apply_solid(g_led_prof.r,g_led_prof.g,g_led_prof.b,br);
        } else if(mode==LED_MODE_BREATHE){
            float s=0.5f*(1.0f + sinf(2.0f*(float)M_PI*(elapsed/breathe_period)));
            int low=(int)(0.15f*(float)g_led_prof.brightness);
            int br=low + (int)lroundf(s*(float)(g_led_prof.brightness-low));
            leds_apply_solid(g_led_prof.r,g_led_prof.g,g_led_prof.b,clampu8(br));
        } else if(mode==LED_MODE_GRADIENT_ANIM){
            if (g_led_prof.anim_speed > 0) {
                float t = fmodf(elapsed * g_led_prof.anim_speed / 5.0f, 1.0f);
                for(int i=0; i<LED_STRIP_LENGTH; i++){
                    float local_t = fmodf((i / (float)(LED_STRIP_LENGTH-1)) + t, 1.0f);
                    uint8_t r = (uint8_t)(g_led_prof.start_r + (g_led_prof.end_r - g_led_prof.start_r) * local_t);
                    uint8_t g = (uint8_t)(g_led_prof.start_g + (g_led_prof.end_g - g_led_prof.start_g) * local_t);
                    uint8_t b = (uint8_t)(g_led_prof.start_b + (g_led_prof.end_b - g_led_prof.start_b) * local_t);
                    uint8_t br = scale_bright(r, g_led_prof.brightness);
                    uint8_t bg = scale_bright(g, g_led_prof.brightness);
                    uint8_t bb = scale_bright(b, g_led_prof.brightness);
                    (void)led_strip_set_pixel(g_led_strip, i, br, bg, bb);
                }
                (void)led_strip_refresh(g_led_strip);
                // ESP_LOGI(TAG, "Applied gradient anim at t=%.2f", t);
            }
        }
        vTaskDelay(step_ticks);
    }
}

/* ===== Entry ===== */
static void ensure_ledc_init_once(void){
    static bool inited=false;
    if(!inited){ fan_pwm_init(); inited=true; }
}

void app_main(void){
    g_system_startup_ms = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
    esp_err_t ret=nvs_flash_init();
    if(ret==ESP_ERR_NVS_NO_FREE_PAGES || ret==ESP_ERR_NVS_NEW_VERSION_FOUND){
        ESP_ERROR_CHECK(nvs_flash_erase());
        ESP_ERROR_CHECK(nvs_flash_init());
    }

    /* Load configs */
    fan_set_defaults(&g_fan);
    if(fan_load_from_nvs()!=ESP_OK){ ESP_LOGW(TAG,"FAN: defaults"); fan_save_to_nvs(); }
    pump_set_defaults(&g_pump);
    if(pump_load_from_nvs()!=ESP_OK){ ESP_LOGW(TAG,"PUMP: defaults"); pump_save_to_nvs(); }
    led_prof_load(); leds_init();

    gpio_set_direction(LED_GPIO,GPIO_MODE_OUTPUT);
    gpio_set_level(LED_GPIO,0);

    ensure_ledc_init_once();
    fan_pwm_set_percent(0.0f);
    pump_pwm_set_percent(0.0f);

    /* Tach inputs */
    tach_init();

    /* UART */
    uart_init();
    ESP_LOGI(TAG,"USB/UART enabled @%d", UART_BAUD);

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
    }
#else
    ESP_LOGW(TAG,"Bluetooth NimBLE disabled in menuconfig");
#endif

    xTaskCreate(control_task,"fan_pump_ctrl",4096,NULL,5,NULL);
    xTaskCreate(led_task,"led_task",3072,NULL,4,&g_led_task);
}