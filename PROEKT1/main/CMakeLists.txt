idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES
        bt
        led_strip
        esp_driver_ledc
        esp_driver_uart
        esp_driver_gpio
    PRIV_REQUIRES
        nvs_flash
)