/**
 * crc.c - CRC implementations (see crc.h for the contract).
 */
#include "crc.h"

static uint16_t crc16_table[256];
static uint32_t crc32_table[256];
static uint8_t tables_ready = 0;

static void build_tables(void) {
    for (uint32_t i = 0; i < 256; i++) {
        uint16_t c16 = (uint16_t)i;
        for (int k = 0; k < 8; k++) {
            c16 = (c16 & 1) ? (uint16_t)((c16 >> 1) ^ 0xA001) : (uint16_t)(c16 >> 1);
        }
        crc16_table[i] = c16;

        uint32_t c32 = i;
        for (int k = 0; k < 8; k++) {
            c32 = (c32 & 1) ? (c32 >> 1) ^ 0xEDB88320U : c32 >> 1;
        }
        crc32_table[i] = c32;
    }
    tables_ready = 1;
}

uint16_t crc16_modbus(const uint8_t *data, uint32_t len) {
    if (!tables_ready) build_tables();
    uint16_t crc = 0xFFFF;
    for (uint32_t i = 0; i < len; i++) {
        crc = (uint16_t)((crc >> 8) ^ crc16_table[(crc ^ data[i]) & 0xFF]);
    }
    return crc;
}

uint32_t crc32_ieee(const uint8_t *data, uint32_t len) {
    return crc32_final(crc32_update(crc32_init(), data, len));
}

uint32_t crc32_init(void) {
    if (!tables_ready) build_tables();
    return 0xFFFFFFFFU;
}

uint32_t crc32_update(uint32_t state, const uint8_t *data, uint32_t len) {
    uint32_t crc = state;
    for (uint32_t i = 0; i < len; i++) {
        crc = (crc >> 8) ^ crc32_table[(crc ^ data[i]) & 0xFF];
    }
    return crc;
}

uint32_t crc32_final(uint32_t state) {
    return state ^ 0xFFFFFFFFU;
}
