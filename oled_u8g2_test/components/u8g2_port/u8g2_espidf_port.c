#include "u8g2.h"
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <stdint.h>

// GPIOs for SW I2C (use your wiring)
#ifndef U8G2_SDA_GPIO
#define U8G2_SDA_GPIO 21
#endif
#ifndef U8G2_SCL_GPIO
#define U8G2_SCL_GPIO 22
#endif

static inline void gpio_out(gpio_num_t pin, int level){
    gpio_set_direction(pin, GPIO_MODE_OUTPUT);
    gpio_set_level(pin, level);
}

// Minimal GPIO+delay callback for u8g2/u8x8 (software I2C)
uint8_t u8x8_gpio_and_delay_esp32_sw_i2c(u8x8_t *u8x8, uint8_t msg, uint8_t arg_int, void *arg_ptr){
    (void)u8x8; (void)arg_ptr;
    switch(msg){
        case U8X8_MSG_GPIO_AND_DELAY_INIT:
            gpio_out(U8G2_SCL_GPIO, 1);
            gpio_out(U8G2_SDA_GPIO, 1);
            break;
        case U8X8_MSG_DELAY_MILLI:
            vTaskDelay(pdMS_TO_TICKS(arg_int));
            break;
        case U8X8_MSG_DELAY_10MICRO:
        case U8X8_MSG_DELAY_100NANO:
            // crude spin-wait
            for(volatile int i=0;i<arg_int*10;i++) __asm__ __volatile__("nop");
            break;
        case U8X8_MSG_GPIO_I2C_CLOCK:
            gpio_set_level(U8G2_SCL_GPIO, arg_int);
            break;
        case U8X8_MSG_GPIO_I2C_DATA:
            gpio_set_level(U8G2_SDA_GPIO, arg_int);
            break;
        default:
            // ignore other GPIOs (CS/DC/RESET not used for I2C)
            break;
    }
    return 1;
}

// Use built-in u8x8 byte function for software I2C
extern uint8_t u8x8_byte_sw_i2c(u8x8_t *u8x8, uint8_t msg, uint8_t arg_int, void *arg_ptr);

// Helper to init U8G2 with SSD1312 64x128 (portrait) using SW I2C
void u8g2_espidf_setup_ssd1312_64x128_sw_i2c(u8g2_t *u8g2){
    // Try common setup name; if it changes upstream, adjust here
    extern void u8g2_Setup_ssd1312_i2c_64x128_f(u8g2_t *u8g2, const u8g2_cb_t *rotation, u8x8_byte_cb byte_cb, u8x8_gpio_and_delay_cb gpio_cb);
    u8g2_Setup_ssd1312_i2c_64x128_f(u8g2, U8G2_R0, u8x8_byte_sw_i2c, u8x8_gpio_and_delay_esp32_sw_i2c);
}
