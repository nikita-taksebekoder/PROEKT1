# U8g2 ESP-IDF port: builds the U8g2 C sources from third_party/u8g2/csrc

set(U8G2_ROOT ${CMAKE_CURRENT_LIST_DIR}/../../third_party/u8g2)
set(U8G2_CSRC ${U8G2_ROOT}/csrc)

file(GLOB U8G2_SOURCES ${U8G2_CSRC}/*.c)

idf_component_register(
    SRCS ${U8G2_SOURCES} "u8g2_espidf_port.c"
    INCLUDE_DIRS ${U8G2_CSRC}
    REQUIRES driver
)
