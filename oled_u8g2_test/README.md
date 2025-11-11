# OLED U8g2 Test (SSD1312 64x128 over SW I2C)

This minimal ESP-IDF project draws text on a 64x128 SSD1312 OLED using U8g2 with software I2C on GPIO 21/22.

## Wiring
- SDA -> GPIO21
- SCL -> GPIO22
- VCC -> 3.3V (or try 5V if your board requires it)
- GND -> GND

## Prepare U8g2 sources
Clone U8g2 into `third_party/u8g2` inside this project:

```pwsh
cd oled_u8g2_test
git clone https://github.com/olikraus/u8g2.git third_party/u8g2
```

## Build & flash
Use ESP-IDF tasks (target esp32):

```pwsh
idf.py set-target esp32
idf.py build
idf.py -p COM3 flash monitor
```

If function name differs upstream (setup for SSD1312 64x128), adjust it in `components/u8g2_port/u8g2_espidf_port.c`.
