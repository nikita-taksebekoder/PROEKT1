#include "u8g2.h"
#include "u8x8.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "esp_rom_sys.h"
#include "esp_log.h"

// Simple SW I2C bit-bang callbacks for U8g2
// Pins are configured by Kconfig or defines here
static int s_u8g2_sw_i2c_scl = 22;
static int s_u8g2_sw_i2c_sda = 21;
static int s_u8g2_sw_i2c_delay_us = 10; /* extra slow for long wires/weak pullups */
static int s_u8g2_reset_gpio = -1; /* optional */

static void sw_i2c_delay(void) { esp_rom_delay_us(s_u8g2_sw_i2c_delay_us); }

static void sw_i2c_set_scl(int level) {
    gpio_set_level(s_u8g2_sw_i2c_scl, level);
    sw_i2c_delay();
}

static void sw_i2c_set_sda(int level) {
    gpio_set_level(s_u8g2_sw_i2c_sda, level);
    sw_i2c_delay();
}

static int sw_i2c_get_sda(void) {
    return gpio_get_level(s_u8g2_sw_i2c_sda);
}

uint8_t u8x8_byte_sw_i2c_espidf(u8x8_t *u8x8, uint8_t msg, uint8_t arg_int, void *arg_ptr) {
    switch (msg) {
    case U8X8_MSG_BYTE_INIT: {
        gpio_config_t io = {
            .pin_bit_mask = (1ULL << s_u8g2_sw_i2c_scl) | (1ULL << s_u8g2_sw_i2c_sda),
            .mode = GPIO_MODE_INPUT_OUTPUT_OD,
            .pull_up_en = GPIO_PULLUP_ENABLE,
            .pull_down_en = GPIO_PULLDOWN_DISABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        gpio_config(&io);
        // both high (released)
        sw_i2c_set_scl(1);
        sw_i2c_set_sda(1);
        break;
    }
    case U8X8_MSG_BYTE_START_TRANSFER: {
        // START condition
        sw_i2c_set_sda(1); sw_i2c_set_scl(1); sw_i2c_set_sda(0); sw_i2c_set_scl(0);
        // Send 8-bit I2C address (U8g2 stores 8-bit address)
        uint8_t addr8 = u8x8_GetI2CAddress(u8x8);
        for (int i = 0; i < 8; i++) {
            sw_i2c_set_sda((addr8 & 0x80) != 0);
            sw_i2c_set_scl(1);
            sw_i2c_set_scl(0);
            addr8 <<= 1;
        }
        // ACK bit for address
        sw_i2c_set_sda(1); // release
        sw_i2c_set_scl(1);
        (void)sw_i2c_get_sda();
        sw_i2c_set_scl(0);
        break; }
    case U8X8_MSG_BYTE_END_TRANSFER:
        // STOP: SDA high while SCL high
        sw_i2c_set_sda(0); sw_i2c_set_scl(1); sw_i2c_set_sda(1);
        break;
    case U8X8_MSG_BYTE_SET_DC:
        // not used for SSD13xx I2C CAD path
        break;
    case U8X8_MSG_BYTE_SEND: {
        uint8_t *data = (uint8_t*)arg_ptr;
        while (arg_int > 0) {
            uint8_t b = *data++;
            for (int i = 0; i < 8; i++) {
                sw_i2c_set_sda((b & 0x80) != 0);
                sw_i2c_set_scl(1);
                sw_i2c_set_scl(0);
                b <<= 1;
            }
            // ACK bit
            sw_i2c_set_sda(1); // release
            sw_i2c_set_scl(1);
            // read ACK (optional)
            (void)sw_i2c_get_sda();
            sw_i2c_set_scl(0);
            arg_int--;
        }
        break;
    }
    default:
        return 0;
    }
    return 1;
}

uint8_t u8x8_gpio_and_delay_espidf(u8x8_t *u8x8, uint8_t msg, uint8_t arg_int, void *arg_ptr) {
    switch (msg) {
    case U8X8_MSG_GPIO_AND_DELAY_INIT:
        // prepare reset pin if configured
        if (s_u8g2_reset_gpio >= 0) {
            gpio_config_t rst = {
                .pin_bit_mask = (1ULL << s_u8g2_reset_gpio),
                .mode = GPIO_MODE_OUTPUT,
                .pull_up_en = GPIO_PULLUP_DISABLE,
                .pull_down_en = GPIO_PULLDOWN_DISABLE,
                .intr_type = GPIO_INTR_DISABLE,
            };
            gpio_config(&rst);
            gpio_set_level(s_u8g2_reset_gpio, 1); // idle high
        }
        break;
    case U8X8_MSG_DELAY_MILLI:
        vTaskDelay(pdMS_TO_TICKS(arg_int));
        break;
    case U8X8_MSG_DELAY_10MICRO:
        for (int i = 0; i < arg_int; i++) esp_rom_delay_us(10);
        break;
    case U8X8_MSG_DELAY_100NANO:
        // ignore
        break;
    case U8X8_MSG_GPIO_I2C_CLOCK:
        sw_i2c_set_scl(arg_int);
        break;
    case U8X8_MSG_GPIO_I2C_DATA:
        sw_i2c_set_sda(arg_int);
        break;
    case U8X8_MSG_GPIO_RESET:
        if (s_u8g2_reset_gpio >= 0) {
            gpio_set_level(s_u8g2_reset_gpio, arg_int ? 1 : 0);
        }
        break;
    case U8X8_MSG_GPIO_CS:
    case U8X8_MSG_GPIO_DC:
        // not used for I2C; ignore
        break;
    default:
        // ignore unhandled messages
        return 1;
    }
    return 1;
}

void u8g2_espidf_sw_i2c_set_pins(int sda, int scl) { s_u8g2_sw_i2c_sda = sda; s_u8g2_sw_i2c_scl = scl; }
void u8g2_espidf_sw_i2c_set_delay_us(int delay_us) { s_u8g2_sw_i2c_delay_us = delay_us > 0 ? delay_us : 1; }
void u8g2_espidf_sw_i2c_set_reset_pin(int gpio) { s_u8g2_reset_gpio = gpio; }

/* Simple SW I2C probe for 7-bit address; returns 1 if ACK received */
uint8_t u8g2_espidf_sw_i2c_probe(uint8_t addr7) {
    // init bus (open-drain, pull-ups)
    gpio_config_t io = {
        .pin_bit_mask = (1ULL << s_u8g2_sw_i2c_scl) | (1ULL << s_u8g2_sw_i2c_sda),
        .mode = GPIO_MODE_INPUT_OUTPUT_OD,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&io);
    sw_i2c_set_scl(1); sw_i2c_set_sda(1);
    // START
    sw_i2c_set_sda(1); sw_i2c_set_scl(1); sw_i2c_set_sda(0); sw_i2c_set_scl(0);
    // send address byte (write)
    uint8_t b = (uint8_t)((addr7 << 1) | 0);
    for (int i=0;i<8;i++) { sw_i2c_set_sda((b & 0x80)!=0); sw_i2c_set_scl(1); sw_i2c_set_scl(0); b <<= 1; }
    // ACK
    sw_i2c_set_sda(1); sw_i2c_set_scl(1); int ack = (sw_i2c_get_sda()==0); sw_i2c_set_scl(0);
    // STOP
    sw_i2c_set_sda(0); sw_i2c_set_scl(1); sw_i2c_set_sda(1);
    return ack ? 1 : 0;
}

