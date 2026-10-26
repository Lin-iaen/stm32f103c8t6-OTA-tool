/**
 * protocol.h - Shared wire protocol for the f103-workbench.
 *
 * Frame format inherited verbatim from the smart-robot-car project (MIT):
 *   [0xAA][0x55][CMD][LEN_H][LEN_L][PAYLOAD...][CRC16_H][CRC16_L]
 *   - LEN is payload length (0..1024), big-endian.
 *   - CRC16-MODBUS covers CMD..end of PAYLOAD (see crc.h).
 *   - Response convention: echo (CMD | 0x80), first payload byte = status.
 *
 * Command spaces:
 *   0x01..0x0F  Bootloader (OTA)   -- inherited unchanged from smart-robot-car
 *   0x10..0x2F  Application        -- redefined as a generic IO console
 *
 * KEEP IN SYNC with host/fwb/protocol.py (single source of truth is this file;
 * host/fwb/tests/test_protocol.py guards the alignment).
 */
#ifndef PROTOCOL_H
#define PROTOCOL_H

#include <stdint.h>

#define PROTO_SOF0       0xAA
#define PROTO_SOF1       0x55
#define PROTO_MAX_PAYLOAD 1024
#define PROTO_OVERHEAD   6   /* SOF0 SOF1 CMD LEN_H LEN_L CRC_H CRC_L minus payload */

/* ---------------- Bootloader commands (0x01..0x0F) ---------------- */
#define BL_QUERY    0x01  /* resp: bl_ver(3) + app_base(4 BE) + max_size(4 BE) + page(4 BE) */
#define BL_START    0x02   /* payload: total_len(4B, BE) -> set flag + erase app region */
#define BL_DATA     0x03   /* payload: offset(4B, BE) + chunk(<=1024), even offsets */
#define BL_VERIFY   0x04   /* payload: crc32(4B, BE) of whole image */
#define BL_JUMP     0x05   /* clear flag, jump (only after successful verify) */
#define BL_ABORT    0x06   /* clear flag if app valid, reset */

/* Bootloader trigger flag stored in Backup register DR1 (needs PWR+BKP clock).
 * STM32F1 BKP_DRx is 16-bit, so this MUST fit in 16 bits. */
#define OTA_MAGIC   0x4F54U    /* 16-bit "OT" */

/* ---------------- Application commands (0x10..0x2F) ----------------
 * Generic IO console: any F103C8T6 board becomes remotely operable. */
#define APP_PING          0x10  /* no payload -> echo OK */
#define APP_GET_VERSION   0x11  /* no payload -> resp: bl_ver(3)+app_ver(3) */
#define APP_REBOOT        0x12  /* no payload -> echo OK then NVIC_SystemReset */
#define APP_OTA_START     0x13  /* payload: total_len(4B, BE) -> set flag, reset into BL */

#define APP_GPIO_CONFIG   0x14  /* payload: port(1) pin(1) mode(1) pull(1)
                                 * mode: 0=input 1=output 2=alt 3=analog
                                 * pull: 0=none 1=pullup 2=pulldown (inputs only) */
#define APP_GPIO_WRITE    0x15  /* payload: port(1) pin(1) value(1: 0/1) */
#define APP_GPIO_READ     0x16  /* payload: port(1) pin(1) -> resp: value(1) */
#define APP_ADC_READ      0x17  /* payload: channel(1, 0..17) -> resp: mv(2 BE) */
#define APP_PWM_SET       0x18  /* payload: ch(1) freq_hz(4 BE) duty(2 BE, 0..1000) */
#define APP_PWM_STOP      0x19  /* payload: ch(1) */
#define APP_GET_TELEMETRY 0x1A  /* no payload -> resp is the 0x9A report frame */
#define APP_SET_PARAM     0x1B  /* payload: param_id(1) + value(4, BE) */
#define APP_GET_PARAM     0x1C  /* payload: param_id(1) */
#define APP_SET_IO        0x1D  /* payload: led(1) rsv(1) rsv(1) -- board LED (PC13) */

/* Unsolicited report (app -> host), same frame as the GET_TELEMETRY response:
 * 0x1A | 0x80 == 0x9A, so GET_TELEMETRY must NOT also send an echo
 * (same convention as the original project's GET_STATUS). */
#define APP_TELEMETRY_REPORT 0x9A
/* Telemetry payload (7 bytes):
 *   uptime_ms(4, BE) | vbat_mv(2, BE) | flags(1)
 *   flags.bit0 = PWM active on any channel */

/* ---------------- Status / error codes ---------------- */
#define PROTO_OK          0x00
#define PROTO_ERR_GENERIC 0x01
#define PROTO_ERR_BUSY    0x02
#define PROTO_ERR_PARAM   0x03
#define PROTO_ERR_CRC     0x04
#define PROTO_ERR_NOAPP   0x05   /* bootloader: no valid app to jump */
#define PROTO_ERR_FLASH   0x06
#define PROTO_ERR_MODE    0x07   /* pin not configured for this operation */

/* ---------------- Parameter IDs ---------------- */
#define PARAM_HEARTBEAT_MS 0x01  /* telemetry period, 0=off (default 1000) */
#define PARAM_VREF_MV      0x02  /* ADC full-scale reference mV (default 3300) */

/* ---------------- Firmware versions ----------------
 * Semantic MAJOR.MINOR.PATCH. This fork diverges from smart-robot-car at
 * 0.1.0 (UART moved to USART1, generic console app). Bump patch per change. */
#define BL_VERSION_MAJOR  0
#define BL_VERSION_MINOR  1
#define BL_VERSION_PATCH  1
#define APP_VERSION_MAJOR 0
#define APP_VERSION_MINOR  1
#define APP_VERSION_PATCH  38

#endif /* PROTOCOL_H */
