#pragma once
#include "u8g2.h"
#include "u8x8.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Configure SW I2C pins and timing (optional, defaults: SDA=21, SCL=22, delay=2us) */
void u8g2_espidf_sw_i2c_set_pins(int sda, int scl);
void u8g2_espidf_sw_i2c_set_delay_us(int delay_us);
/* Return 1 if device ACKs on given 7-bit address */
uint8_t u8g2_espidf_sw_i2c_probe(uint8_t addr7);
/* Optional: set hardware RESET gpio for OLED (set to -1 to disable) */
void u8g2_espidf_sw_i2c_set_reset_pin(int gpio);

/* Expose callbacks for U8g2 Setup */
uint8_t u8x8_byte_sw_i2c_espidf(u8x8_t *u8x8, uint8_t msg, uint8_t arg_int, void *arg_ptr);
uint8_t u8x8_gpio_and_delay_espidf(u8x8_t *u8x8, uint8_t msg, uint8_t arg_int, void *arg_ptr);

#ifdef __cplusplus
}
#endif
