/**
 * STM32F103C8T6 reference App (IO console) - register level, no HAL.
 *
 * A reusable IO-console firmware template. Any F103C8T6 board becomes
 * remotely operable over UART/BLE: GPIO read/write, ADC sample, PWM output,
 * live telemetry, and wireless OTA via the companion bootloader.
 *
 * This is the source of release/app-v0.1.38.bin. Replace it with your own
 * application if you like; it only has to answer APP_PING, APP_GET_VERSION
 * and APP_OTA_START (see docs/04-protocol.md and firmware/README.md).
 *
 * Architecture inherited from kurui365/smart-robot-car (MIT):
 *   - bare-metal super-loop (no RTOS, no locks: single consumer)
 *   - ISR-safe lock-free SPSC ring buffer for UART RX
 *   - byte-stream frame state machine + CRC16-MODBUS validation
 *   - OTA trigger via backup-register flag + reset into bootloader
 *
 * Board defaults (Blue Pill):
 *   UART1  PA9(TX)/PA10(RX) 115200 8N1  -- BLE module / USB-TTL
 *   LED    PC13 (active low)
 *   ADC    any channel 0..17 (PA0..PA7, PB0..PB1, temp, vref)
 *   PWM    TIM2 CH1-4 = PA0/PA1/PA2/PA3, TIM3 CH1-4 = PA6/PA7/PB0/PB1
 *          (channels on the same timer share one frequency)
 *
 * Build: make (see Makefile). Image is linked at APP_BASE 0x08003000.
 */
#include <stdint.h>
#include <stddef.h>
#include "stm32f1_reg.h"
#include "flash_layout.h"
#include "protocol.h"
#include "crc.h"

/* ================= System / clock / SysTick ================= */

volatile uint32_t g_ticks = 0;   /* ms since boot (SysTick) */

static void clock_init_72mhz(void) {
    /* HSE 8MHz -> PLL x9 = 72MHz. Same tree as the bootloader, so the UART
     * baud rate is identical in both images (a baud mismatch between BL and
     * App was the root cause of OTA failures in the original project). */
    RCC->CFGR = RCC_CFGR_SW_HSI;
    while ((RCC->CFGR & (3u << 2)) != 0) { }
    RCC->CR &= ~RCC_CR_PLLON;
    RCC->CR |= RCC_CR_HSEON;
    { volatile uint32_t to = 2000000u;
      while (!(RCC->CR & RCC_CR_HSERDY) && --to) { } }
    if (RCC->CR & RCC_CR_HSERDY) {
        FLASH->ACR = FLASH_ACR_LATENCY_2 | FLASH_ACR_PRFTBE;
        uint32_t cfg = RCC_CFGR_PLLSRC_HSE | RCC_CFGR_PLLMUL9 |
                       RCC_CFGR_PPRE1_DIV2 | RCC_CFGR_PPRE2_DIV1 |
                       RCC_CFGR_HPRE_DIV1;
        /* NOTE: no ADCPRE setting here -- some clone F103 parts' ADC
         * refuses to complete conversions when the prescaler divides the
         * clock (div4 is flaky, div6/div8 hang). The reset default div2
         * (=PCLK2/2 = 36MHz) works, though out of the genuine-F103 spec. */
        RCC->CFGR = cfg;
        RCC->CR |= RCC_CR_PLLON;
        while (!(RCC->CR & RCC_CR_PLLRDY)) { }
        RCC->CFGR = cfg | RCC_CFGR_SW_PLL;
        while ((RCC->CFGR & (3u << 2)) != (2u << 2)) { }
    }
}

void SystemInit(void) {
    clock_init_72mhz();
    SCB->VTOR = APP_BASE;          /* relocate vector table to the app image */
    /* SysTick: 72MHz core clock / 1000 = 1ms tick */
    SysTick->LOAD = 72000u - 1u;
    SysTick->VAL  = 0;
    SysTick->CTRL = 7u;            /* ENABLE | TICKINT | CLKSOURCE */
}

static void delay_ms(uint32_t ms) {
    uint32_t start = g_ticks;
    while ((g_ticks - start) < ms) { }
}

void SysTick_Handler(void) {
    g_ticks++;
}

/* ================= USART1 (PA9/PA10) ================= */

static void uart1_init(uint32_t baud) {
    RCC->APB2ENR |= RCC_APB2ENR_IOPAEN | RCC_APB2ENR_AFIOEN |
                    RCC_APB2ENR_USART1EN;
    uint32_t crh = GPIOA->CRH;
    crh &= ~((0xFu << 4) | (0xFu << 8));      /* PA9, PA10 */
    crh |=  (0xBu << 4);                      /* PA9 TX: AF push-pull 50MHz */
    crh |=  (0x4u << 8);                      /* PA10 RX: input floating */
    GPIOA->CRH = crh;

    USART1->BRR = 72000000u / baud;           /* 115200 -> 625 exactly */
    USART1->CR2 = 0;
    USART1->CR3 = 0;
    (void)USART1->SR; (void)USART1->DR;       /* clear stale RXNE/ORE */
    USART1->CR1 = USART_CR1_UE | USART_CR1_TE | USART_CR1_RE |
                  USART_CR1_RXNEIE;
    /* NVIC enable USART1 interrupt (IRQ 37) */
    NVIC->ISER[1] |= (1u << (37 - 32));
}

static void uart1_putc(uint8_t c) {
    while (!(USART1->SR & USART_SR_TXE)) { }
    USART1->DR = c;
}

static void uart1_drain_tx(void) {
    while (!(USART1->SR & USART_SR_TC)) { }   /* wait transmission complete */
}

/* ================= RX ring buffer (ISR -> main loop) =================
 * Lock-free single-producer (ISR) / single-consumer (main) ring. Pattern
 * inherited from smart-robot-car comm.c. */
#define RX_RING_SZ 2048                        /* power of two */
static uint8_t rx_ring[RX_RING_SZ];
static volatile uint16_t rx_head = 0;          /* written by ISR  */
static volatile uint16_t rx_tail = 0;          /* written by main */

static void comm_rx_byte(uint8_t b) {
    uint16_t next = (uint16_t)((rx_head + 1u) & (RX_RING_SZ - 1u));
    if (next != rx_tail) {
        rx_ring[rx_head] = b;
        rx_head = next;
    }
    /* overflow: drop the byte; the frame CRC will fail anyway */
}

static int rx_pop(uint8_t *out) {
    if (rx_head == rx_tail) return 0;
    *out = rx_ring[rx_tail];
    rx_tail = (uint16_t)((rx_tail + 1u) & (RX_RING_SZ - 1u));
    return 1;
}

void USART1_IRQHandler(void) {
    if (USART1->SR & USART_SR_RXNE) {
        comm_rx_byte((uint8_t)(USART1->DR & 0xFF));
    }
}

/* ================= Frame TX ================= */

static void send_frame(uint8_t cmd, const uint8_t *pl, uint16_t len) {
    static uint8_t buf[PROTO_MAX_PAYLOAD + 7u];   /* static: off the stack */
    uint16_t n = 0;
    buf[n++] = PROTO_SOF0;
    buf[n++] = PROTO_SOF1;
    buf[n++] = cmd;
    buf[n++] = (uint8_t)(len >> 8);
    buf[n++] = (uint8_t)(len & 0xFF);
    for (uint16_t i = 0; i < len; i++) buf[n++] = pl[i];
    uint16_t crc = crc16_modbus(&buf[2], (uint16_t)(3u + len));
    buf[n++] = (uint8_t)(crc >> 8);
    buf[n++] = (uint8_t)(crc & 0xFF);
    for (uint16_t i = 0; i < n; i++) uart1_putc(buf[i]);
}

static void respond(uint8_t cmd, uint8_t status, const uint8_t *extra, uint16_t extra_len) {
    if (extra_len > (PROTO_MAX_PAYLOAD - 1u)) return;
    uint8_t buf[PROTO_MAX_PAYLOAD];
    uint16_t n = 0;
    buf[n++] = status;
    for (uint16_t i = 0; i < extra_len; i++) buf[n++] = extra[i];
    send_frame((uint8_t)(cmd | 0x80), buf, n);
}

/* ================= GPIO console ================= */

#define GPIO_MODE_IN      0
#define GPIO_MODE_OUT     1
#define GPIO_MODE_AF      2
#define GPIO_MODE_ANALOG  3

static GPIO_TypeDef *gpio_port_by_index(uint8_t idx) {
    switch (idx) {
    case 0: return GPIOA;
    case 1: return GPIOB;
    case 2: return GPIOC;
    default: return NULL;
    }
}

/* Configure one pin. mode/pull semantics: see protocol.h APP_GPIO_CONFIG. */
static int gpio_config_pin(uint8_t port, uint8_t pin, uint8_t mode, uint8_t pull) {
    if (port > 2 || pin > 15) return -1;
    GPIO_TypeDef *g = gpio_port_by_index(port);
    if (g == NULL) return -1;

    /* Guard: PA9/PA10 belong to the console UART. */
    if (port == 0 && (pin == 9 || pin == 10)) return -1;

    /* Enable the port clock (idempotent). */
    RCC->APB2ENR |= (1u << (2 + port));   /* IOPAEN/IOPBEN/IOPCEN */

    volatile uint32_t *cr = (pin < 8) ? &g->CRL : &g->CRH;
    uint32_t shift = (pin & 7u) * 4u;
    uint32_t cfg = 0;

    switch (mode) {
    case GPIO_MODE_IN:
        if (pull == 1)      cfg = 0x8;   /* input with pull-up   (CNF=10, ODR=1) */
        else if (pull == 2) cfg = 0x8;   /* input with pull-down (CNF=10, ODR=0) */
        else                cfg = 0x4;   /* input floating       (CNF=01) */
        break;
    case GPIO_MODE_OUT:     cfg = 0x3;   /* output push-pull 50MHz */
        break;
    case GPIO_MODE_AF:      cfg = 0xB;   /* AF push-pull 50MHz */
        break;
    case GPIO_MODE_ANALOG:  cfg = 0x0;   /* analog (CNF=00, MODE=00) */
        break;
    default: return -1;
    }

    uint32_t v = *cr;
    v &= ~(0xFu << shift);
    v |= (cfg << shift);
    *cr = v;

    if (mode == GPIO_MODE_IN && pull != 0) {
        if (pull == 1) g->BSRR = (1u << pin);       /* ODR=1: pull-up   */
        else           g->BRR   = (1u << pin);      /* ODR=0: pull-down */
    }
    return 0;
}

static int gpio_write_pin(uint8_t port, uint8_t pin, uint8_t value) {
    if (port > 2 || pin > 15) return -1;
    GPIO_TypeDef *g = gpio_port_by_index(port);
    if (g == NULL) return -1;
    if (port == 0 && (pin == 9 || pin == 10)) return -1;
    if (value) g->BSRR = (1u << pin);
    else       g->BRR   = (1u << pin);
    return 0;
}

static int gpio_read_pin(uint8_t port, uint8_t pin, uint8_t *value) {
    if (port > 2 || pin > 15) return -1;
    GPIO_TypeDef *g = gpio_port_by_index(port);
    if (g == NULL) return -1;
    *value = (g->IDR & (1u << pin)) ? 1 : 0;
    return 0;
}

/* ================= Runtime params (persisted to config page) ================= */
static uint16_t g_heartbeat_ms = 1000;
static uint16_t g_vref_mv = 3300;

/* ================= Config page (flash persistence) =================
 * 1KB at config_page_addr() (0x0800FC00 on 64KB, 0x0801FC00 on 128KB),
 * selected at runtime from F_SIZE. Managed by the App. Layout:
 *   [0..3]   magic (0x4B574348 = "WORK")
 *   [4..5]   version (uint16, for future migrations)
 *   [6..7]   CRC16-MODBUS of bytes 8..end
 *   [8..11]  heartbeat_ms (uint32)
 *   [12..15] vref_mv (uint32)
 * The rest of the page is reserved for future params. */

#define CONFIG_MAGIC    0x4B574348U
#define CONFIG_VERSION  1

typedef struct {
    uint32_t magic;
    uint16_t version;
    uint16_t crc16;
    uint32_t heartbeat_ms;
    uint32_t vref_mv;
} config_page_t;

static int flash_unlock(void) {
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

static int flash_erase_config_page(void) {
    if (flash_unlock() != 0) return -1;
    FLASH->SR = FLASH_SR_EOP | FLASH_SR_PGERR | FLASH_SR_WRPRTERR;
    FLASH->CR = (FLASH->CR & ~(FLASH_CR_PG | FLASH_CR_PER)) | FLASH_CR_PER;
    FLASH->AR = config_page_addr();
    FLASH->CR |= FLASH_CR_STRT;
    int r = flash_finish();
    FLASH->CR &= ~FLASH_CR_PER;
    FLASH->CR |= FLASH_CR_LOCK;
    if (r != 0) return r;
    if (*(volatile uint16_t *)config_page_addr() != 0xFFFFu) return -2;
    return 0;
}

static int flash_write_halfwords(uint32_t addr, const uint16_t *data, uint16_t count) {
    if (addr < config_page_addr() || addr + count * 2u > config_page_addr() + CONFIG_PAGE_SIZE) {
        return -2;
    }
    if (flash_unlock() != 0) return -1;
    FLASH->SR = FLASH_SR_EOP | FLASH_SR_PGERR | FLASH_SR_WRPRTERR;
    FLASH->CR = (FLASH->CR & ~(FLASH_CR_PER | FLASH_CR_PG)) | FLASH_CR_PG;
    for (uint16_t i = 0; i < count; i++) {
        volatile uint16_t *dst = (volatile uint16_t *)(addr + i * 2u);
        *dst = data[i];
        if (flash_finish() != 0 || *dst != data[i]) {
            FLASH->CR &= ~FLASH_CR_PG;
            FLASH->CR |= FLASH_CR_LOCK;
            return -3;
        }
    }
    FLASH->CR &= ~FLASH_CR_PG;
    FLASH->CR |= FLASH_CR_LOCK;
    return 0;
}

static void config_load(void) {
    const volatile config_page_t *cp = (const volatile config_page_t *)config_page_addr();
    if (cp->magic != CONFIG_MAGIC) return;
    if (cp->version != CONFIG_VERSION) return;

    uint8_t crcbuf[8];
    crcbuf[0] = (uint8_t)(cp->heartbeat_ms >> 24);
    crcbuf[1] = (uint8_t)(cp->heartbeat_ms >> 16);
    crcbuf[2] = (uint8_t)(cp->heartbeat_ms >> 8);
    crcbuf[3] = (uint8_t)(cp->heartbeat_ms);
    crcbuf[4] = (uint8_t)(cp->vref_mv >> 24);
    crcbuf[5] = (uint8_t)(cp->vref_mv >> 16);
    crcbuf[6] = (uint8_t)(cp->vref_mv >> 8);
    crcbuf[7] = (uint8_t)(cp->vref_mv);
    if (crc16_modbus(crcbuf, 8) != cp->crc16) return;

    g_heartbeat_ms = (uint16_t)cp->heartbeat_ms;
    g_vref_mv       = (uint16_t)cp->vref_mv;
}

static void config_save(void) {
    /* Disable UART1 RXNE interrupt during flash ops so we don't lose bytes
     * while the flash bus is stalled. */
    USART1->CR1 &= ~USART_CR1_RXNEIE;

    if (flash_erase_config_page() != 0) goto done;

    uint8_t crcbuf[8];
    crcbuf[0] = (uint8_t)(g_heartbeat_ms >> 24);
    crcbuf[1] = (uint8_t)(g_heartbeat_ms >> 16);
    crcbuf[2] = (uint8_t)(g_heartbeat_ms >> 8);
    crcbuf[3] = (uint8_t)(g_heartbeat_ms);
    crcbuf[4] = (uint8_t)(g_vref_mv >> 24);
    crcbuf[5] = (uint8_t)(g_vref_mv >> 16);
    crcbuf[6] = (uint8_t)(g_vref_mv >> 8);
    crcbuf[7] = (uint8_t)(g_vref_mv);

    uint16_t hw[8];
    hw[0] = (uint16_t)(CONFIG_MAGIC & 0xFFFF);
    hw[1] = (uint16_t)(CONFIG_MAGIC >> 16);
    hw[2] = CONFIG_VERSION;
    hw[3] = crc16_modbus(crcbuf, 8);
    /* heartbeat_ms as two halfwords */
    uint32_t hm = (uint32_t)g_heartbeat_ms;
    hw[4] = (uint16_t)(hm & 0xFFFF);
    hw[5] = (uint16_t)(hm >> 16);
    /* vref_mv as two halfwords */
    uint32_t vm = (uint32_t)g_vref_mv;
    hw[6] = (uint16_t)(vm & 0xFFFF);
    hw[7] = (uint16_t)(vm >> 16);

    flash_write_halfwords(config_page_addr(), hw, 8);

done:
    USART1->CR1 |= USART_CR1_RXNEIE;
}

/* ================= ADC (on-demand single-shot) ================= */

static int adc_read_mv(uint8_t channel, uint16_t *mv) {
    if (channel > 17 || channel == 10 || channel == 11 ||
        (channel >= 12 && channel <= 15)) {
        return -1;                       /* reserved channels on F103C8 */
    }
    RCC->APB2ENR |= RCC_APB2ENR_ADC1EN | RCC_APB2ENR_IOPAEN | RCC_APB2ENR_IOPBEN;

    ADC1->SQR1 = 0;                      /* 1 conversion in sequence */
    ADC1->SMPR1 = 0; ADC1->SMPR2 = 0;
    if (channel < 10) ADC1->SMPR2 |= (7u << (channel * 3));        /* 239.5 cyc */
    else              ADC1->SMPR1 |= (7u << ((channel - 10) * 3));
    ADC1->SQR3 = channel;

    ADC1->CR1 = 0;
    ADC1->CR2 = ADC_CR2_ADON;            /* wake up */
    /* Internal channels 16 (temp) / 17 (VREFINT) need TSVREFE. Set AFTER the
     * plain ADON store above (a plain store would clear it). No CAL: on this
     * clone the calibration corrupts the following sample. */
    if (channel >= 16) ADC1->CR2 |= ADC_CR2_TSVREFE;
    delay_ms(2);                         /* tSTAB */

    ADC1->CR2 |= ADC_CR2_SWSTART;
    { volatile uint32_t to = 400000u;
      while (!(ADC1->SR & ADC_SR_EOC) && --to) { } }
    if (!(ADC1->SR & ADC_SR_EOC)) return -2;
    uint16_t raw = (uint16_t)(ADC1->DR & 0xFFF);
    ADC1->CR2 = 0;                       /* power down between reads */

    uint32_t val = ((uint32_t)raw * g_vref_mv + 2047u) / 4095u;
    *mv = (uint16_t)val;
    return 0;
}

/* ================= PWM (TIM2/TIM3, 8 channels) =================
 * ch 0..3 = TIM2 CH1..CH4 (PA0/PA1/PA2/PA3)
 * ch 4..7 = TIM3 CH1..CH4 (PA6/PA7/PB0/PB1)
 * Channels on the same timer share the frequency (one PSC/ARR per timer). */

typedef struct {
    TIM_TypeDef *tim;
    uint8_t      gpio_port;              /* 0=A 1=B */
    uint8_t      gpio_pin;
    uint8_t      ccmr_shift;             /* CCMR1: ch1/2  CCMR2: ch3/4 */
} pwm_ch_t;

static const pwm_ch_t PWM_CH[8] = {
    { TIM2, 0, 0, 0  },  /* ch0: TIM2_CH1 PA0  (CCMR1) */
    { TIM2, 0, 1, 4  },  /* ch1: TIM2_CH2 PA1  (CCMR1) */
    { TIM2, 0, 2, 0  },  /* ch2: TIM2_CH3 PA2  (CCMR2) */
    { TIM2, 0, 3, 4  },  /* ch3: TIM2_CH4 PA3  (CCMR2) */
    { TIM3, 0, 6, 0  },  /* ch4: TIM3_CH1 PA6  (CCMR1) */
    { TIM3, 0, 7, 4  },  /* ch5: TIM3_CH2 PA7  (CCMR1) */
    { TIM3, 1, 0, 0  },  /* ch6: TIM3_CH3 PB0  (CCMR2) */
    { TIM3, 1, 1, 4  },  /* ch7: TIM3_CH4 PB1  (CCMR2) */
};

/* CCER enable bit per channel index within its timer (1..4). */
static const uint32_t PWM_CCER_BIT[4] = { (1u << 0), (1u << 4), (1u << 8), (1u << 12) };

static uint8_t g_pwm_active[8] = { 0 };

static int pwm_set(uint8_t ch, uint32_t freq_hz, uint16_t duty_permille) {
    if (ch >= 8 || freq_hz == 0u || freq_hz > 1000000u || duty_permille > 1000u) {
        return -1;
    }
    const pwm_ch_t *p = &PWM_CH[ch];
    uint8_t tim_ch = (ch & 3u);                       /* 0..3 = CH1..CH4 */

    /* Timer clock: TIM2/TIM3 on APB1 with prescaler 2 -> 2x PCLK1 = 72MHz. */
    const uint32_t timclk = 72000000u;
    uint32_t psc = timclk / freq_hz / 65536u;
    if (psc > 65534u) psc = 65534u;
    uint32_t arr = timclk / ((psc + 1u) * freq_hz);
    if (arr == 0u) arr = 1u;
    if (arr > 65535u) return -1;                      /* freq too low */
    arr -= 1u;

    if (!(p->tim->CR1 & TIM_CR1_CEN)) {               /* first use: bring up */
        if (p->tim == TIM2) RCC->APB1ENR |= RCC_APB1ENR_TIM2EN;
        else                RCC->APB1ENR |= RCC_APB1ENR_TIM3EN;
        p->tim->CR1 = 0;
        p->tim->CCER = 0;
        p->tim->PSC = psc;
        p->tim->ARR = arr;
        p->tim->EGR = 2;                              /* UG: force update */
        (void)p->tim->CNT;
    } else {
        p->tim->PSC = psc;                            /* freq applies timer-wide */
        p->tim->ARR = arr;
        p->tim->EGR = 2;
        (void)p->tim->CNT;
    }

    /* Pin to AF push-pull. */
    {
        GPIO_TypeDef *g = gpio_port_by_index(p->gpio_port);
        volatile uint32_t *cr = (p->gpio_pin < 8) ? &g->CRL : &g->CRH;
        uint32_t shift = (p->gpio_pin & 7u) * 4u;
        uint32_t v = *cr;
        v &= ~(0xFu << shift);
        v |= (0xBu << shift);                          /* AF push-pull 50MHz */
        *cr = v;
    }

    uint32_t ccr = ((arr + 1u) * duty_permille) / 1000u;
    if (tim_ch == 0)      p->tim->CCR1 = ccr;
    else if (tim_ch == 1) p->tim->CCR2 = ccr;
    else if (tim_ch == 2) p->tim->CCR3 = ccr;
    else                  p->tim->CCR4 = ccr;

    /* CCMR: PWM mode 1 (OCxM=110) + preload enable. */
    volatile uint32_t *ccmr = (tim_ch < 2) ? &p->tim->CCMR1 : &p->tim->CCMR2;
    uint32_t shift = (tim_ch & 1u) * 8u;
    uint32_t v = *ccmr;
    v &= ~(0xFFu << shift);
    v |= ((0x60u | 0x08u) << shift);                   /* OCxM=110 PWM1, OCxPE */
    *ccmr = v;

    /* CCER: enable output, active high. */
    p->tim->CCER |= PWM_CCER_BIT[tim_ch];

    /* CR1: ARPE + enable. */
    p->tim->CR1 |= TIM_CR1_ARPE | TIM_CR1_CEN;

    g_pwm_active[ch] = 1;
    return 0;
}

static int pwm_stop(uint8_t ch) {
    if (ch >= 8) return -1;
    const pwm_ch_t *p = &PWM_CH[ch];
    p->tim->CCER &= ~PWM_CCER_BIT[ch & 3u];
    g_pwm_active[ch] = 0;
    return 0;
}

static uint8_t pwm_any_active(void) {
    for (int i = 0; i < 8; i++) if (g_pwm_active[i]) return 1;
    return 0;
}

/* ================= Telemetry ================= */

/* APP_TELEMETRY_REPORT (0x9A) payload: uptime_ms(4 BE) | vbat_mv(2 BE) | flags(1) */
static void send_telemetry(void) {
    uint8_t buf[7];
    uint32_t up = g_ticks;
    buf[0] = (uint8_t)(up >> 24); buf[1] = (uint8_t)(up >> 16);
    buf[2] = (uint8_t)(up >> 8);  buf[3] = (uint8_t)(up);
    uint16_t mv = 0;
    (void)adc_read_mv(0, &mv);         /* PA0 by default; see docs if PA0 is PWM */
    buf[4] = (uint8_t)(mv >> 8); buf[5] = (uint8_t)(mv);
    buf[6] = pwm_any_active() ? 0x01 : 0x00;
    send_frame(APP_TELEMETRY_REPORT, buf, 7);
}

/* ================= OTA trigger + misc ================= */

static void trigger_ota(void) {
    /* Set the OTA flag in backup register DR1, then reset. The bootloader
     * sees OTA_MAGIC on boot and stays in DFU mode. Requires PWR + BKP
     * clocks and the DBP bit (same sequence as the bootloader). */
    RCC->APB1ENR |= RCC_APB1ENR_PWREN | RCC_APB1ENR_BKPEN;
    PWR->CR |= PWR_CR_DBP;
    BKP->DR1 = OTA_MAGIC;
    PWR->CR &= ~PWR_CR_DBP;
}

static void led_init(void) {
    RCC->APB2ENR |= RCC_APB2ENR_IOPCEN;
    uint32_t crh = GPIOC->CRH;
    crh &= ~(0xFu << 20);
    crh |=  (0x2u << 20);              /* PC13: output push-pull 2MHz */
    GPIOC->CRH = crh;
    GPIOC->BSRR = (1u << 13);          /* off (active low) */
}

static void led_set(uint8_t on) {
    if (on) GPIOC->BRR   = (1u << 13); /* low = LED on  */
    else    GPIOC->BSRR = (1u << 13);  /* high = LED off */
}

/* ================= Frame parser state machine ================= */

enum { ST_SOF0, ST_SOF1, ST_CMD, ST_LEN_H, ST_LEN_L, ST_PAYLOAD, ST_CRC_H, ST_CRC_L };
static uint8_t  f_state = ST_SOF0;
static uint8_t  f_cmd = 0;
static uint16_t f_len = 0;
static uint16_t f_idx = 0;
static uint8_t  f_payload[PROTO_MAX_PAYLOAD];
static uint8_t  f_crc_h = 0, f_crc_l = 0;
static uint32_t f_last_byte_ms = 0;

static void dispatch(uint8_t cmd, const uint8_t *p, uint16_t len);

static void comm_feed(void) {
    uint8_t b;
    while (rx_pop(&b)) {
        uint32_t now = g_ticks;
        /* Inter-byte timeout: restart the frame if the stream stalled. */
        if (f_state != ST_SOF0 && (now - f_last_byte_ms) > 100u) {
            f_state = ST_SOF0;
        }
        f_last_byte_ms = now;

        switch (f_state) {
        case ST_SOF0: if (b == PROTO_SOF0) f_state = ST_SOF1; break;
        case ST_SOF1:
            if (b == PROTO_SOF1) f_state = ST_CMD;
            else f_state = (b == PROTO_SOF0) ? ST_SOF0 : ST_SOF0;
            break;
        case ST_CMD:     f_cmd = b; f_state = ST_LEN_H; break;
        case ST_LEN_H:   f_len = (uint16_t)b << 8; f_state = ST_LEN_L; break;
        case ST_LEN_L:
            f_len |= b;
            if (f_len > PROTO_MAX_PAYLOAD) { f_state = ST_SOF0; break; }
            f_idx = 0;
            f_state = (f_len == 0u) ? ST_CRC_H : ST_PAYLOAD;
            break;
        case ST_PAYLOAD:
            f_payload[f_idx++] = b;
            if (f_idx == f_len) f_state = ST_CRC_H;
            break;
        case ST_CRC_H:   f_crc_h = b; f_state = ST_CRC_L; break;
        case ST_CRC_L: {
            f_crc_l = b;
            uint8_t crcbuf[3 + PROTO_MAX_PAYLOAD];
            crcbuf[0] = f_cmd;
            crcbuf[1] = (uint8_t)(f_len >> 8);
            crcbuf[2] = (uint8_t)(f_len & 0xFF);
            for (uint16_t i = 0; i < f_len; i++) crcbuf[3 + i] = f_payload[i];
            uint16_t calc = crc16_modbus(crcbuf, (uint16_t)(3u + f_len));
            f_state = ST_SOF0;
            if (((calc >> 8) & 0xFF) == f_crc_h && (calc & 0xFF) == f_crc_l) {
                dispatch(f_cmd, f_payload, f_len);
            } else {
                uint8_t s = PROTO_ERR_CRC;
                send_frame((uint8_t)(f_cmd | 0x80), &s, 1);
            }
            break;
        }
        default: f_state = ST_SOF0; break;
        }
    }
}

/* ================= Command dispatch (generic IO console) ================= */

static uint8_t reboot_pending = 0;
static uint8_t ota_pending = 0;

static void dispatch(uint8_t cmd, const uint8_t *p, uint16_t len) {
    uint8_t extra[8];
    uint16_t elen = 0;

    switch (cmd) {
    case APP_PING:
        if (len != 0u) { respond(cmd, PROTO_ERR_PARAM, NULL, 0); return; }
        respond(cmd, PROTO_OK, NULL, 0);
        return;

    case APP_GET_VERSION:
        if (len != 0u) { respond(cmd, PROTO_ERR_PARAM, NULL, 0); return; }
        extra[0] = BL_VERSION_MAJOR;  extra[1] = BL_VERSION_MINOR;  extra[2] = BL_VERSION_PATCH;
        extra[3] = APP_VERSION_MAJOR; extra[4] = APP_VERSION_MINOR; extra[5] = APP_VERSION_PATCH;
        respond(cmd, PROTO_OK, extra, 6);
        return;

    case APP_REBOOT:
        if (len != 0u) { respond(cmd, PROTO_ERR_PARAM, NULL, 0); return; }
        respond(cmd, PROTO_OK, NULL, 0);
        uart1_drain_tx();
        reboot_pending = 1;
        return;

    case APP_OTA_START: {
        if (len != 4u) { respond(cmd, PROTO_ERR_PARAM, NULL, 0); return; }
        respond(cmd, PROTO_OK, NULL, 0);
        uart1_drain_tx();
        ota_pending = 1;               /* actual reset deferred to the loop */
        return;
    }

    case APP_GPIO_CONFIG:
        if (len != 4u || p[3] > 2u) { respond(cmd, PROTO_ERR_PARAM, NULL, 0); return; }
        respond(cmd,
                gpio_config_pin(p[0], p[1], p[2], p[3]) == 0 ? PROTO_OK : PROTO_ERR_PARAM,
                NULL, 0);
        return;

    case APP_GPIO_WRITE:
        if (len != 3u || p[2] > 1u) { respond(cmd, PROTO_ERR_PARAM, NULL, 0); return; }
        respond(cmd,
                gpio_write_pin(p[0], p[1], p[2]) == 0 ? PROTO_OK : PROTO_ERR_PARAM,
                NULL, 0);
        return;

    case APP_GPIO_READ: {
        uint8_t value = 0;
        if (len != 2u) { respond(cmd, PROTO_ERR_PARAM, NULL, 0); return; }
        if (gpio_read_pin(p[0], p[1], &value) != 0) {
            respond(cmd, PROTO_ERR_PARAM, NULL, 0); return;
        }
        extra[0] = value;
        respond(cmd, PROTO_OK, extra, 1);
        return;
    }

    case APP_ADC_READ: {
        uint16_t mv = 0;
        if (len != 1u) { respond(cmd, PROTO_ERR_PARAM, NULL, 0); return; }
        int r = adc_read_mv(p[0], &mv);
        if (r != 0) { respond(cmd, PROTO_ERR_PARAM, NULL, 0); return; }
        extra[0] = (uint8_t)(mv >> 8); extra[1] = (uint8_t)(mv);
        respond(cmd, PROTO_OK, extra, 2);
        return;
    }

    case APP_PWM_SET: {
        if (len != 7u) { respond(cmd, PROTO_ERR_PARAM, NULL, 0); return; }
        uint32_t freq = ((uint32_t)p[1] << 24) | ((uint32_t)p[2] << 16) |
                        ((uint32_t)p[3] << 8)  |  (uint32_t)p[4];
        uint16_t duty = (uint16_t)(((uint16_t)p[5] << 8) | p[6]);
        respond(cmd,
                pwm_set(p[0], freq, duty) == 0 ? PROTO_OK : PROTO_ERR_PARAM,
                NULL, 0);
        return;
    }

    case APP_PWM_STOP:
        if (len != 1u) { respond(cmd, PROTO_ERR_PARAM, NULL, 0); return; }
        respond(cmd,
                pwm_stop(p[0]) == 0 ? PROTO_OK : PROTO_ERR_PARAM,
                NULL, 0);
        return;

    case APP_GET_TELEMETRY:
        /* 0x1A|0x80 == 0x9A == APP_TELEMETRY_REPORT: respond with the report
         * frame itself, never an echo (convention from the original project). */
        send_telemetry();
        return;

    case APP_SET_PARAM: {
        if (len != 5u) { respond(cmd, PROTO_ERR_PARAM, NULL, 0); return; }
        uint32_t value = ((uint32_t)p[1] << 24) | ((uint32_t)p[2] << 16) |
                         ((uint32_t)p[3] << 8)  |  (uint32_t)p[4];
        switch (p[0]) {
        case PARAM_HEARTBEAT_MS:
            if (value > 60000u) { respond(cmd, PROTO_ERR_PARAM, NULL, 0); return; }
            g_heartbeat_ms = (uint16_t)value;
            break;
        case PARAM_VREF_MV:
            if (value < 1000u || value > 5000u) { respond(cmd, PROTO_ERR_PARAM, NULL, 0); return; }
            g_vref_mv = (uint16_t)value;
            break;
        default:
            respond(cmd, PROTO_ERR_PARAM, NULL, 0);
            return;
        }
        config_save();   /* persist to flash */
        respond(cmd, PROTO_OK, NULL, 0);
        return;
    }

    case APP_GET_PARAM: {
        uint32_t value = 0;
        if (len != 1u) { respond(cmd, PROTO_ERR_PARAM, NULL, 0); return; }
        switch (p[0]) {
        case PARAM_HEARTBEAT_MS: value = g_heartbeat_ms; break;
        case PARAM_VREF_MV:      value = g_vref_mv;      break;
        default:
            respond(cmd, PROTO_ERR_PARAM, NULL, 0);
            return;
        }
        extra[0] = (uint8_t)(value >> 24); extra[1] = (uint8_t)(value >> 16);
        extra[2] = (uint8_t)(value >> 8);  extra[3] = (uint8_t)(value);
        respond(cmd, PROTO_OK, extra, 4);
        return;
    }

    case APP_SET_IO:
        if (len != 3u) { respond(cmd, PROTO_ERR_PARAM, NULL, 0); return; }
        led_set(p[0] ? 1 : 0);
        respond(cmd, PROTO_OK, NULL, 0);
        return;

    default:
        respond(cmd, PROTO_ERR_GENERIC, NULL, 0);
        return;
    }
    (void)extra; (void)elen;
}

/* ================= Watchdog ================= */

static void iwdg_init(uint32_t ms) {
    /* LSI ~40kHz: prescaler /32 -> 1250 Hz. */
    IWDG->KR  = 0xCCCCu;               /* enable */
    IWDG->KR  = 0x5555u;               /* allow config */
    IWDG->PR  = 3u;                    /* /32 */
    IWDG->RLR = (uint16_t)((ms * 1250u) / 1000u);
    while (IWDG->SR) { }
    IWDG->KR  = 0xAAAAu;               /* reload */
}

static void iwdg_feed(void) {
    IWDG->KR = 0xAAAAu;
}

/* ================= main ================= */

int main(void) {
    led_init();
    uart1_init(115200);
    config_load();   /* restore saved params from flash config page */

    /* Freeze IWDG while the core is halted under SWD debugging. */
    DBGMCU->CR |= DBGMCU_CR_IWDG_STOP;

#if !defined(APP_NO_IWDG)
    iwdg_init(1000);
#endif

    uint32_t last_report = 0;

    while (1) {
        comm_feed();

        /* Distinctive "double-blink" heartbeat every 2s (on 0-200ms, on
         * 400-600ms, else off): makes a freshly OTA'd image unmistakable when
         * SWD is disconnected (the only flash path is the wireless OTA). */
        uint32_t t = g_ticks % 2000u;
        if (t < 200u || (t >= 400u && t < 600u)) led_set(0);   /* ON */
        else                                     led_set(1);   /* OFF */

        if (g_heartbeat_ms != 0u && (g_ticks - last_report) >= g_heartbeat_ms) {
            last_report = g_ticks;
            send_telemetry();
        }

        if (reboot_pending) {
            delay_ms(10);
            NVIC_SystemReset();
        }
        if (ota_pending) {
            delay_ms(10);
            trigger_ota();
            NVIC_SystemReset();
        }

#if !defined(APP_NO_IWDG)
        iwdg_feed();
#endif
        delay_ms(2);   /* ~500 Hz console loop (no motion control to ramp) */
    }
}
