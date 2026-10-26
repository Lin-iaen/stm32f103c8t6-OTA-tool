/**
 * crc.h - CRC16(MODBUS) and CRC32(IEEE) shared by Bootloader and App.
 *
 * The PC control software (Python) implements the exact same algorithms so
 * that frames and firmware images can be verified end-to-end.
 */
#ifndef CRC_H
#define CRC_H

#include <stdint.h>

/* CRC16/MODBUS: poly 0x8005 (reflected 0xA001), init 0xFFFF, no final XOR */
uint16_t crc16_modbus(const uint8_t *data, uint32_t len);

/* CRC32/IEEE: poly 0xEDB88320 (reflected), init 0xFFFFFFFF, final XOR 0xFFFFFFFF */
uint32_t crc32_ieee(const uint8_t *data, uint32_t len);

/* Incremental CRC32 (used by the bootloader to verify a streamed image
 * without buffering it in RAM):
 *   uint32_t s = crc32_init();
 *   s = crc32_update(s, chunk, len);   // per chunk
 *   uint32_t final = crc32_final(s);   // == crc32_ieee(whole)
 */
uint32_t crc32_init(void);
uint32_t crc32_update(uint32_t state, const uint8_t *data, uint32_t len);
uint32_t crc32_final(uint32_t state);

#endif /* CRC_H */
