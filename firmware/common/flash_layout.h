/**
 * flash_layout.h - Flash memory map for STM32F103C8/CB (1KB pages).
 *
 * The F103C8T6 is specified as 64KB, but many Blue Pill boards carry a die
 * that reports (and actually has) 128KB. Read the flash-size register at
 * 0x1FFFF7E0 at runtime and size the layout accordingly:
 *
 *   64KB part                          128KB part
 *   0x08000000 +----------------+      0x08000000 +----------------+
 *              | Bootloader 12K |                | Bootloader 12K |
 *   0x08003000 +----------------+      0x08003000 +----------------+
 *              | App 51 KB      |                | App 115 KB     |
 *   0x0800FC00 +----------------+      0x0801FC00 +----------------+
 *              | Config 1 KB    |                | Config 1 KB    |
 *   0x08010000 +----------------+      0x08020000 +----------------+
 *
 * The bootloader and app MUST use the same runtime helpers below; otherwise
 * the app would write its config page into the other layout's app region.
 *
 * SHARED by BOTH the bootloader and the application image. Add this directory
 * (firmware/common) to both include paths: the bootloader Makefile already
 * passes -I../common, and the CubeMX app project must add firmware/common too
 * (it already must, for protocol.h / crc.h).
 */
#ifndef FLASH_LAYOUT_H
#define FLASH_LAYOUT_H

#include <stdint.h>

#define FLASH_BASE_ADDR   0x08000000U
#define FLASH_PAGE_SIZE   1024U

#define BOOTLOADER_BASE   0x08000000U
#define BOOTLOADER_SIZE   0x00003000U   /* 12 KB */

#define APP_BASE          0x08003000U

/* F_SIZE: 16-bit flash size in KB (RM0008). Present on all F103 parts. */
#define FLASH_SIZE_REG_ADDR  0x1FFFF7E0U
#define FLASH_SIZE_MIN_KB    64U
#define FLASH_SIZE_MAX_KB    128U

/**
 * Read the real flash size. Values outside [64, 128] (0xFFFF on some clones,
 * 256KB parts, ...) fall back to 64KB: using less flash is safe, using more
 * than the die has is not.
 *
 * FLASH_SIZE_FORCE_KB is a build-time test hook (e.g. -DFLASH_SIZE_FORCE_KB=64)
 * for validating the 64KB layout on a 128KB board. Normal builds leave it
 * undefined and read F_SIZE.
 */
static inline uint32_t flash_size_kb(void) {
#ifdef FLASH_SIZE_FORCE_KB
    return FLASH_SIZE_FORCE_KB;
#else
    uint16_t kb = *(volatile const uint16_t *)FLASH_SIZE_REG_ADDR;
    if (kb < FLASH_SIZE_MIN_KB || kb > FLASH_SIZE_MAX_KB) return FLASH_SIZE_MIN_KB;
    return kb;
#endif
}

static inline uint32_t flash_end_addr(void) {
    return FLASH_BASE_ADDR + flash_size_kb() * 1024U;
}

/** Last 1KB page: app calibration/params, managed by the app. */
static inline uint32_t config_page_addr(void) {
    return flash_end_addr() - FLASH_PAGE_SIZE;
}

/** App region: APP_BASE .. config_page_addr (exclusive). */
static inline uint32_t app_max_size(void) {
    return config_page_addr() - APP_BASE;
}

#define CONFIG_PAGE_SIZE  FLASH_PAGE_SIZE

#define OTA_UPDATE_MAGIC 0x5550U /* update in progress */

/* NOTE: OTA_MAGIC is defined in protocol.h (which both images include), NOT
 * here, to avoid a macro-redefinition clash between the two builds. */

/* App validity: stack pointer must sit in SRAM (20KB: 0x20000000..0x20005000) */
#define SRAM_BASE_ADDR    0x20000000U
#define SRAM_SIZE         0x00005000U

#endif /* FLASH_LAYOUT_H */
