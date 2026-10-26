/**
 * bootloader.h - Public interface for the USART1 bootloader (f103-workbench).
 *
 * Ported from smart-robot-car (MIT): UART3(PB10/PB11) -> UART1(PA9/PA10) for
 * the Blue Pill minimum system board. DFU state machine unchanged.
 *
 * USART1 on PA9(TX)/PA10(RX), 115200 8N1. USART1 sits on APB2 (72 MHz),
 * 72000000/115200 = 625 exactly -> zero baud-rate error.
 */
#ifndef BOOTLOADER_H
#define BOOTLOADER_H

#include <stdint.h>
#include "flash_layout.h"

/* USART1 on PA9(TX)/PA10(RX), 115200 8N1 */
#define BL_USART_BAUDRATE 115200

void bl_system_init(void);
void bl_gpio_init(void);
void bl_usart1_init(uint32_t baud);
void bl_usart1_putc(uint8_t c);
int  bl_usart1_getc_timeout(uint32_t ms);   /* returns -1 on timeout */
void bl_led_toggle(void);

/* Flash helpers (register level) */
int  bl_flash_unlock(void);
int  bl_flash_erase_app(void);              /* erase entire app region */
int  bl_flash_write(uint32_t addr, const uint8_t *data, uint32_t len);

/* Backup register OTA flag */
int bl_set_ota_flag(uint32_t v);
uint32_t bl_get_ota_flag(void);

/* App image validation + jump */
int bl_app_valid(void);
void bl_jump_to_app(void);

/* Frame-level OTA state machine (driven by main loop) */
void bl_process_frame(const uint8_t *payload, uint16_t len, uint8_t cmd);

/* Build and send a response frame */
void bl_send_response(uint8_t cmd, const uint8_t *payload, uint16_t len);

#endif /* BOOTLOADER_H */
