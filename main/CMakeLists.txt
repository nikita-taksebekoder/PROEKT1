idf_component_register(
    SRCS
        "main.c"
    INCLUDE_DIRS "."
    REQUIRES
        bt
        led_strip
        u8g2_port
        esp_driver_ledc
        esp_driver_uart
        esp_driver_gpio
        esp_driver_i2c
        driver
    PRIV_REQUIRES
        nvs_flash
)