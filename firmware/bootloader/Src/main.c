/**
 * Bootloader main (STM32F103C8T6) - register level, no HAL.
 *
 * Ported from kurui365/smart-robot-car (MIT). DFU state machine, flash
 * routines and boot decision logic are inherited unchanged; only the UART
 * was moved for the Blue Pill board:
 *   USART3 PB10/PB11  ->  USART1 PA9/PA10
 *   DFU LED   PB15    ->  board LED PC13
 * USART1 sits on APB2 (72 MHz): 72000000/115200 = 625 exactly, so the baud
 * rate has zero error (the original project traced OTA failures to baud
 * error between images -- both images here run the same 72 MHz tree).
 *
 * Responsibilities:
 *   - On reset, decide whether to run DFU (OTA) or jump to the application.
 *   - DFU mode talks to the host over USART1 using the shared framing in
 *     protocol.h: receive image, write flash, verify CRC32, jump.
 *
 * Build: Src/main.c + ../common/crc.c with the device startup and the
 * bootloader linker script (ORIGIN=0x08000000, LENGTH=12K). See Makefile.
 */
#include <stdint.h>
#include <string.h>
#include "stm32f1_reg.h"
#include "flash_layout.h"
#include "bootloader.h"
#include "protocol.h"
#include "crc.h"

/* ---------------- Clock / GPIO ---------------- */
void bl_system_init(void) {
    /* Run at 72 MHz (HSE 8 MHz -> PLL x9), the SAME clock tree as the app, so
     * USART1 (APB2, 72 MHz) divides exactly: BRR = 625, ~0% baud error. */
    RCC->CFGR = RCC_CFGR_SW_HSI;
    while ((RCC->CFGR & (3u << 2)) != 0) { }   /* wait SWS = HSI */
    RCC->CR &= ~RCC_CR_PLLON;                  /* PLL off */
    RCC->CR |= RCC_CR_HSEON;
    { volatile uint32_t to = 2000000u;
      while (!(RCC->CR & RCC_CR_HSERDY) && --to) { } }
    if (RCC->CR & RCC_CR_HSERDY) {
        FLASH->ACR = FLASH_ACR_LATENCY_2 | FLASH_ACR_PRFTBE;
        uint32_t cfg = RCC_CFGR_PLLSRC_HSE | RCC_CFGR_PLLMUL9 |
                       RCC_CFGR_PPRE1_DIV2 | RCC_CFGR_PPRE2_DIV1 |
                       RCC_CFGR_HPRE_DIV1;
        RCC->CFGR = cfg;                        /* SW still HSI for now */
        RCC->CR |= RCC_CR_PLLON;
        while (!(RCC->CR & RCC_CR_PLLRDY)) { }
        RCC->CFGR = cfg | RCC_CFGR_SW_PLL;
        while ((RCC->CFGR & (3u << 2)) != (2u << 2)) { } /* wait SWS = PLL */
    }
    /* If HSE failed we simply stay on HSI (degraded baud) -- still boots. */
    /* USART1 + GPIOA (PA9/PA10) + GPIOC (PC13 LED) on APB2. */
    RCC->APB2ENR |= RCC_APB2ENR_IOPAEN | RCC_APB2ENR_IOPCEN |
                    RCC_APB2ENR_AFIOEN | RCC_APB2ENR_USART1EN;
    /* PWR + BKP clocks required to read the OTA flag from backup register
     * DR1. Both bits must be set: DBP (in PWR_CR) lifts the write-protection,
     * but the BKP domain itself is clocked by BKPEN (RCC_APB1ENR) -- without
     * it the read returns garbage and the bootloader can miss the flag. */
    RCC->APB1ENR |= RCC_APB1ENR_PWREN | RCC_APB1ENR_BKPEN;
}

void bl_gpio_init(void) {
    /* USART1: PA9(TX, alt push-pull) / PA10(RX, input floating). */
    uint32_t crh_a = GPIOA->CRH;
    crh_a &= ~((0xFu << 4) | (0xFu << 8));   /* clear PA9, PA10 config */
    crh_a |=  (0xBu << 4);                   /* PA9(TX1): alt push-pull 50MHz (MODE=11,CNF=10) */
    crh_a |=  (0x4u << 8);                   /* PA10(RX1): input floating    (MODE=00,CNF=01) */
    GPIOA->CRH = crh_a;

    /* PC13 -> output push-pull 2 MHz (Blue Pill board LED, active low). */
    uint32_t crh_c = GPIOC->CRH;
    crh_c &= ~(0xFu << 20);                  /* clear PC13 config */
    crh_c |=  (0x2u << 20);                  /* output push-pull 2MHz (MODE=10,CNF=00) */
    GPIOC->CRH = crh_c;
    GPIOC->BSRR = (1u << 13);                /* LED off initially (active low) */
}

void bl_led_toggle(void) {
    GPIOC->ODR ^= (1u << 13);
}

/* ---------------- USART1 (BLE / USB-TTL OTA over PA9/PA10) ---------------- */
void bl_usart1_init(uint32_t baud) {
    /* PCLK2 = 72 MHz. 72000000 / 115200 = 625 exactly -> 0% baud error. */
    uint32_t pclk2 = 72000000u;
    USART1->BRR = pclk2 / baud;
    USART1->CR1 = 0;
    USART1->CR2 = 0;
    USART1->CR3 = 0;
    /* A software reset (APP_OTA_START) does NOT clear USART1 SR, so stale
     * RXNE/ORE/IDLE flags left by the app would corrupt DFU frame parsing.
     * Read SR then DR to clear them (STM32F1 RXNE/ORE clear sequence). */
    (void)USART1->SR;
    (void)USART1->DR;
    USART1->CR1 = USART_CR1_UE | USART_CR1_TE | USART_CR1_RE;
}

void bl_usart1_putc(uint8_t c) {
    while (!(USART1->SR & USART_SR_TXE));
    USART1->DR = c;
}

int bl_usart1_getc_timeout(uint32_t ms) {
    /* Crude busy-wait timeout (~1ms at 72 MHz, loop ~10 cycles). */
    volatile uint32_t t = ms * 7200u;
    while (!(USART1->SR & USART_SR_RXNE)) {
        if (t == 0) return -1;
        t--;
    }
    return (int)(USART1->DR & 0xFF);
}

/* ---------------- Flash ---------------- */
int bl_flash_unlock(void) {
    if (FLASH->CR & FLASH_CR_LOCK) {
        FLASH->KEYR = 0x45670123u;
        FLASH->KEYR = 0xCDEF89ABu;
    }
    return (FLASH->CR & FLASH_CR_LOCK) ? -1 : 0;
}

static void flash_wait(void) {
    while (FLASH->SR & FLASH_SR_BSY) { }
}

static int flash_finish(void) {
    flash_wait();
    uint32_t errors = FLASH->SR & (FLASH_SR_PGERR | FLASH_SR_WRPRTERR);
    FLASH->SR = FLASH_SR_EOP | FLASH_SR_PGERR | FLASH_SR_WRPRTERR;
    return errors ? -1 : 0;
}

int bl_flash_erase_app(void) {
    if (bl_flash_unlock() != 0) return -1;
    FLASH->SR = FLASH_SR_EOP | FLASH_SR_PGERR | FLASH_SR_WRPRTERR;

    for (uint32_t addr = APP_BASE; addr < config_page_addr(); addr += FLASH_PAGE_SIZE) {
        FLASH->CR = (FLASH->CR & ~(FLASH_CR_PG | FLASH_CR_PER)) | FLASH_CR_PER;
        FLASH->AR = addr;
        FLASH->CR |= FLASH_CR_STRT;
        if (flash_finish() != 0 || *(volatile uint16_t *)addr != 0xFFFFu) {
            FLASH->CR &= ~FLASH_CR_PER;
            FLASH->CR |= FLASH_CR_LOCK;
            return -2;
        }
    }

    FLASH->CR &= ~FLASH_CR_PER;
    FLASH->CR |= FLASH_CR_LOCK;
    return 0;
}

int bl_flash_write(uint32_t addr, const uint8_t *data, uint32_t len) {
    if (data == NULL || len == 0u || (addr & 1u) != 0u ||
        addr < APP_BASE || addr > config_page_addr() || len > (config_page_addr() - addr)) {
        return -2;
    }
    if (bl_flash_unlock() != 0) return -1;

    FLASH->SR = FLASH_SR_EOP | FLASH_SR_PGERR | FLASH_SR_WRPRTERR;
    FLASH->CR = (FLASH->CR & ~(FLASH_CR_PER | FLASH_CR_PG)) | FLASH_CR_PG;
    for (uint32_t i = 0; i < len; i += 2u) {
        uint16_t value = data[i];
        if ((i + 1u) < len) value |= (uint16_t)data[i + 1u] << 8;
        else value |= 0xFF00u;

        volatile uint16_t *dst = (volatile uint16_t *)(addr + i);
        *dst = value;
        if (flash_finish() != 0 || *dst != value) {
            FLASH->CR &= ~FLASH_CR_PG;
            FLASH->CR |= FLASH_CR_LOCK;
            return -3;
        }
    }

    FLASH->CR &= ~FLASH_CR_PG;
    FLASH->CR |= FLASH_CR_LOCK;
    return 0;
}

/* ---------------- Backup register OTA flag ---------------- */
int bl_set_ota_flag(uint32_t value) {
    PWR->CR |= PWR_CR_DBP;
    BKP->DR1 = (uint16_t)value;
    uint16_t readback = (uint16_t)BKP->DR1;
    PWR->CR &= ~PWR_CR_DBP;
    return (readback == (uint16_t)value) ? 0 : -1;
}
uint32_t bl_get_ota_flag(void) {
    PWR->CR |= PWR_CR_DBP;
    uint32_t v = BKP->DR1;
    PWR->CR &= ~PWR_CR_DBP;
    return v;
}

/* ---------------- App validation / jump ---------------- */
int bl_app_valid(void) {
    uint32_t sp = *(volatile uint32_t *)APP_BASE;
    uint32_t rv = *(volatile uint32_t *)(APP_BASE + 4);
    if (sp < SRAM_BASE_ADDR || sp > (SRAM_BASE_ADDR + SRAM_SIZE) || (sp & 3u)) return 0;
    if ((rv & 1u) == 0u || rv < APP_BASE || rv >= config_page_addr()) return 0;
    if (rv == 0xFFFFFFFFu) return 0;
    return 1;
}

void bl_jump_to_app(void) {
    /* Disable peripherals we touched (leave PWR/APB1 on for the app's BKP). */
    USART1->CR1 = 0;
    RCC->APB2ENR &= ~RCC_APB2ENR_USART1EN;

    uint32_t sp   = *(volatile uint32_t *)APP_BASE;
    uint32_t rv   = *(volatile uint32_t *)(APP_BASE + 4);
    /* Relocate vector table to the application. */
    SCB->VTOR = APP_BASE;
    /* Set main stack pointer and branch. */
    __set_MSP(sp);
    void (*app_entry)(void) = (void (*)(void))rv;
    app_entry();
    while (1);
}

/* ---------------- Frame I/O ---------------- */
void bl_send_response(uint8_t cmd, const uint8_t *payload, uint16_t len) {
    bl_usart1_putc(PROTO_SOF0);
    bl_usart1_putc(PROTO_SOF1);
    bl_usart1_putc((uint8_t)(cmd | 0x80));
    bl_usart1_putc((uint8_t)(len >> 8));
    bl_usart1_putc((uint8_t)(len & 0xFF));
    for (uint16_t i = 0; i < len; i++) bl_usart1_putc(payload[i]);
    /* CRC covers CMD..payload (echo CMD has 0x80 OR-ed in, matching the host).
     * Static so this 1 KB-class buffer never lives on the (small) stack. */
    static uint8_t buf[3 + PROTO_MAX_PAYLOAD];
    uint16_t n = 0;
    buf[n++] = (uint8_t)(cmd | 0x80);
    buf[n++] = (uint8_t)(len >> 8);
    buf[n++] = (uint8_t)(len & 0xFF);
    for (uint16_t i = 0; i < len; i++) buf[3 + i] = payload[i];
    uint16_t crc = crc16_modbus(buf, 3 + len);
    bl_usart1_putc((uint8_t)(crc >> 8));
    bl_usart1_putc((uint8_t)(crc & 0xFF));
}

/* OTA session state */
static uint32_t ota_expected_len = 0;
static uint32_t ota_received_len = 0;
static uint32_t ota_crc_state = 0;
static uint8_t ota_erased=0, ota_verified=0;

static void ota_reset_session(void) {
    ota_expected_len = 0;
    ota_received_len = 0;
    ota_crc_state = crc32_init();
    ota_erased = 0; ota_verified = 0;
}

void bl_process_frame(const uint8_t *p, uint16_t len, uint8_t cmd) {
    uint8_t resp[16];
    uint16_t rlen = 0;
    int err = PROTO_OK;

    switch (cmd) {
    case BL_QUERY: {
        if (len != 0u) { err = PROTO_ERR_PARAM; break; }
        /* payload: bl_ver(3: major,minor,patch) + app_base(4 BE) + max_size(4 BE) + page(4 BE) */
        resp[rlen++] = BL_VERSION_MAJOR;
        resp[rlen++] = BL_VERSION_MINOR;
        resp[rlen++] = BL_VERSION_PATCH;
        uint32_t v = APP_BASE;
        resp[rlen++] = (v >> 24); resp[rlen++] = (v >> 16);
        resp[rlen++] = (v >> 8);  resp[rlen++] = (v);
        v = app_max_size();
        resp[rlen++] = (v >> 24); resp[rlen++] = (v >> 16);
        resp[rlen++] = (v >> 8);  resp[rlen++] = (v);
        v = FLASH_PAGE_SIZE;
        resp[rlen++] = (v >> 24); resp[rlen++] = (v >> 16);
        resp[rlen++] = (v >> 8);  resp[rlen++] = (v);
        break;
    }
    case BL_START: {
        if (len != 4u) { err = PROTO_ERR_PARAM; break; }
        uint32_t total = ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
                         ((uint32_t)p[2] << 8)  | (uint32_t)p[3];
        if (total == 0u || total > app_max_size()) { err = PROTO_ERR_PARAM; break; }
        ota_reset_session();
        ota_expected_len = total;
        if (bl_set_ota_flag(OTA_UPDATE_MAGIC) != 0 || bl_flash_erase_app() != 0) {
            err = PROTO_ERR_FLASH;
            break;
        }
        ota_erased = 1;
        break;
    }
    case BL_DATA: {
        if (len <= 4u) { err = PROTO_ERR_PARAM; break; }
        uint32_t off = ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
                       ((uint32_t)p[2] << 8)  | (uint32_t)p[3];
        uint32_t chunk = (uint32_t)len - 4u;
        if (!ota_erased) { err = PROTO_ERR_GENERIC; break; }
        if (off != ota_received_len || (off & 1u) != 0u ||
            off > ota_expected_len || chunk > (ota_expected_len - off) ||
            ((off + chunk) < ota_expected_len && (chunk & 1u) != 0u)) {
            err = PROTO_ERR_PARAM;
            break;
        }
        const uint8_t *data = &p[4];
        int write_result = bl_flash_write(APP_BASE + off, data, chunk);
        if (write_result != 0) {
            err = (write_result == -2) ? PROTO_ERR_PARAM : PROTO_ERR_FLASH;
            break;
        }
        ota_crc_state = crc32_update(ota_crc_state, data, chunk);
        ota_received_len += chunk;
        break;
    }
    case BL_VERIFY: {
        if (len != 4u) { err = PROTO_ERR_PARAM; break; }
        uint32_t stream_crc = crc32_final(ota_crc_state);
        uint32_t expected_crc = ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
                                ((uint32_t)p[2] << 8)  | (uint32_t)p[3];
        if (!ota_erased || ota_received_len != ota_expected_len) {
            err = PROTO_ERR_GENERIC;
        } else if (stream_crc != expected_crc) {
            err = PROTO_ERR_CRC;
        } else {
            uint32_t flash_crc = crc32_final(crc32_update(
                crc32_init(), (const uint8_t *)APP_BASE, ota_expected_len));
            if (flash_crc != expected_crc) {
                err = PROTO_ERR_CRC;
            } else if (!bl_app_valid()) {
                err = PROTO_ERR_NOAPP;
            } else {
                ota_verified = 1;
                resp[rlen++] = (uint8_t)(flash_crc >> 24);
                resp[rlen++] = (uint8_t)(flash_crc >> 16);
                resp[rlen++] = (uint8_t)(flash_crc >> 8);
                resp[rlen++] = (uint8_t)flash_crc;
            }
        }
        break;
    }
    case BL_JUMP: {
        if (len != 0u) { err = PROTO_ERR_PARAM; break; }
        if (bl_get_ota_flag() == OTA_UPDATE_MAGIC && !ota_verified) {
            err = PROTO_ERR_CRC;
            break;
        }
        if (!bl_app_valid()) { err = PROTO_ERR_NOAPP; break; }
        if (bl_set_ota_flag(0) != 0) { err = PROTO_ERR_FLASH; break; }
        uint8_t ok[1] = { PROTO_OK };
        bl_send_response(cmd, ok, 1);
        for (volatile int i = 0; i < 50000; i++) { }
        bl_jump_to_app();
        break;
    }
    case BL_ABORT: {
        if (len != 0u) { err = PROTO_ERR_PARAM; break; }
        if (bl_get_ota_flag() == OTA_MAGIC && bl_app_valid()) {
            if (bl_set_ota_flag(0) != 0) { err = PROTO_ERR_FLASH; break; }
        }
        NVIC_SystemReset();
        break;
    }
    default:
        err = PROTO_ERR_GENERIC;
        break;
    }

    if (cmd == BL_JUMP && err == PROTO_OK) return; /* already jumped */
    uint8_t status[1] = { (uint8_t)err };
    if (rlen == 0) {
        bl_send_response(cmd, status, 1);
    } else {
        /* prepend status to payload */
        uint8_t out[16];
        out[0] = (uint8_t)err;
        for (uint16_t i = 0; i < rlen; i++) out[1 + i] = resp[i];
        bl_send_response(cmd, out, (uint16_t)(rlen + 1));
    }
}

/* ---------------- Frame receiver ---------------- */
#define FR_RXBUF  (PROTO_MAX_PAYLOAD + 16)
static uint8_t rxbuf[FR_RXBUF];

static int receive_frame(uint8_t *cmd_out, uint8_t *pl_out, uint16_t *pl_len) {
    /* Wait for SOF0,SOF1 */
    int c;
    uint8_t state = 0;
    while (1) {
        c = bl_usart1_getc_timeout(200);
        if (c < 0) { return -1; /* idle timeout */ }
        if (state == 0 && c == PROTO_SOF0) state = 1;
        else if (state == 1 && c == PROTO_SOF1) { state = 2; break; }
        else state = (c == PROTO_SOF0) ? 1 : 0;
    }
    int cmd = bl_usart1_getc_timeout(1000); if (cmd < 0) return -1;
    int lh = bl_usart1_getc_timeout(1000); if (lh < 0) return -1;
    int ll = bl_usart1_getc_timeout(1000); if (ll < 0) return -1;
    uint16_t plen = ((uint16_t)lh << 8) | (uint16_t)ll;
    if (plen > PROTO_MAX_PAYLOAD) return -1;
    for (uint16_t i = 0; i < plen; i++) {
        int d = bl_usart1_getc_timeout(2000); if (d < 0) return -1;
        rxbuf[i] = (uint8_t)d;
    }
    int ch = bl_usart1_getc_timeout(2000); if (ch < 0) return -1;
    int cl = bl_usart1_getc_timeout(2000); if (cl < 0) return -1;
    static uint8_t frame[3 + PROTO_MAX_PAYLOAD];
    frame[0] = (uint8_t)cmd;
    frame[1] = lh; frame[2] = ll;
    for (uint16_t i = 0; i < plen; i++) frame[3 + i] = rxbuf[i];
    uint16_t calc = crc16_modbus(frame, (uint16_t)(3 + plen));
    if (((calc >> 8) & 0xFF) != ((uint8_t)ch) || ((calc) & 0xFF) != ((uint8_t)cl)) {
        *cmd_out = (uint8_t)cmd;   /* echo the (corrupted) command back */
        return -2; /* CRC error */
    }
    *cmd_out = (uint8_t)cmd;
    *pl_len = plen;
    for (uint16_t i = 0; i < plen; i++) pl_out[i] = rxbuf[i];
    return 0;
}

/* ---------------- main ---------------- */
int main(void) {
    bl_system_init();
    bl_gpio_init();
    bl_usart1_init(BL_USART_BAUDRATE);
    ota_reset_session();

    uint32_t flag = bl_get_ota_flag();
    /* Jump straight to the app on power-up. Stay in DFU mode only when
     * (a) the app set the OTA flag and reset, or (b) there is no valid app
     * image at APP_BASE. Case (b) is the anti-brick recovery path: a bad
     * OTA or erased app cannot brick the board -- it falls through to DFU
     * so the host can re-flash it. */
    int dfu = (flag == OTA_MAGIC) || (flag == OTA_UPDATE_MAGIC) || (!bl_app_valid());

    if (!dfu) {
        bl_jump_to_app();   /* does not return */
    }

    /* DFU mode */
    bl_led_toggle();  /* steady blink heartbeat */
    uint8_t cmd = 0;
    static uint8_t pl[PROTO_MAX_PAYLOAD];   /* static: keep 1 KB off the stack */
    uint16_t plen = 0;
    for (;;) {
        int r = receive_frame(&cmd, pl, &plen);
        if (r == 0) {
            bl_process_frame(pl, plen, cmd);
        } else if (r == -2) {
            /* CRC error -> send generic error for the (unknown) command */
            uint8_t s = PROTO_ERR_CRC;
            bl_send_response(cmd, &s, 1);
        }
        /* -1 = idle timeout: keep LED heartbeat */
        static uint32_t hb = 0;
        if ((++hb & 0x3FFF) == 0) bl_led_toggle();
    }
}
