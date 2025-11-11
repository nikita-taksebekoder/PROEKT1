#include "u8g2.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"

static const char *TAG = "oled_u8g2_test";

extern void u8g2_espidf_setup_ssd1312_64x128_sw_i2c(u8g2_t *u8g2);

void app_main(void){
    ESP_LOGI(TAG, "U8g2 SSD1312 64x128 SW I2C test start");

    static u8g2_t u8g2;
    u8g2_espidf_setup_ssd1312_64x128_sw_i2c(&u8g2);
    u8g2_InitDisplay(&u8g2);          // send init sequence
    u8g2_SetPowerSave(&u8g2, 0);      // wake up

    for(;;){
        u8g2_ClearBuffer(&u8g2);
        u8g2_SetFont(&u8g2, u8g2_font_6x10_tf);
        u8g2_DrawStr(&u8g2, 10, 24, "VODA");
        u8g2_DrawStr(&u8g2, 10, 54, "TEST SSD1312 64x128");
        u8g2_SendBuffer(&u8g2);
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
