U8g2 integration for ESP-IDF (SW I2C)

This component wraps the U8g2 graphics library and provides software I2C callbacks for ESP-IDF.

Setup:
- Clone U8g2 into third_party/u8g2 so that csrc exists:
  git clone https://github.com/olikraus/u8g2.git third_party/u8g2

Pins:
- Defaults: SDA=21, SCL=22, bit delay ~2us.
- You can override at runtime with:
  u8g2_espidf_sw_i2c_set_pins(21, 22);
  u8g2_espidf_sw_i2c_set_delay_us(2);

Usage in code:
- Include headers in your component:
  #include "u8g2.h"
  #include "u8g2_espidf_port.h"
- Setup and draw (example):
  u8g2_t u8g2;
  u8g2_espidf_sw_i2c_set_pins(21, 22);
  u8g2_Setup_ssd1306_64x128_er_f(&u8g2, U8G2_R0, u8x8_byte_sw_i2c_espidf, u8x8_gpio_and_delay_espidf);
  u8x8_SetI2CAddress(u8g2_GetU8x8(&u8g2), 0x3C << 1);
  u8g2_InitDisplay(&u8g2);
  u8g2_SetPowerSave(&u8g2, 0);
  u8g2_ClearBuffer(&u8g2);
  u8g2_SetFont(&u8g2, u8g2_font_6x12_tf);
  u8g2_DrawStr(&u8g2, 0, 12, "Hello");
  u8g2_SendBuffer(&u8g2);
