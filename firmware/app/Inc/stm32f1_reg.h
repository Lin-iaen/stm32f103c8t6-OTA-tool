/**
 * stm32f1_reg.h - Self-contained register definitions for the APPLICATION
 * (STM32F103xB, Cortex-M3). No HAL, no CMSIS, no CubeF1 dependency.
 *
 * Extends the bootloader's minimal header with TIM / ADC / IWDG / NVIC /
 * SysTick / AFIO so the application can drive PWM motors, sensors, USART3,
 * battery ADC and the watchdog entirely from registers.
 *
 * Build requirement: only arm-none-eabi-gcc + this header + the bundled
 * startup_stm32f103xb_app.s.
 */
#ifndef STM32F1_REG_H
#define STM32F1_REG_H

#include <stdint.h>

/* ---------------- Peripheral base addresses ---------------- */
#define GPIOA_BASE   0x40010800U
#define GPIOB_BASE   0x40010C00U
#define GPIOC_BASE   0x40011000U
#define USART1_BASE  0x40013800U
#define USART2_BASE  0x40004400U
#define USART3_BASE  0x40004800U
#define RCC_BASE     0x40021000U
#define FLASH_R_BASE 0x40022000U   /* flash control peripheral, NOT code flash */
#define PWR_BASE     0x40007000U
#define BKP_BASE     0x40006C00U
#define AFIO_BASE    0x40010000U
#define TIM1_BASE    0x40012C00U   /* APB2 */
#define TIM2_BASE    0x40000000U   /* APB1 */
#define TIM3_BASE    0x40000400U   /* APB1 */
#define TIM4_BASE    0x40000800U   /* APB1 */
#define ADC1_BASE    0x40012400U
#define IWDG_BASE    0x40003000U
#define NVIC_BASE    0xE000E100U
#define SCB_BASE     0xE000ED00U
#define SYSTICK_BASE 0xE000E010U

/* ---------------- Structs ---------------- */
typedef struct {
    volatile uint32_t CRL;
    volatile uint32_t CRH;
    volatile uint32_t IDR;
    volatile uint32_t ODR;
    volatile uint32_t BSRR;
    volatile uint32_t BRR;
    volatile uint32_t LCKR;
} GPIO_TypeDef;

typedef struct {
    volatile uint32_t CR;
    volatile uint32_t CFGR;
    volatile uint32_t CIR;
    volatile uint32_t APB2RSTR;
    volatile uint32_t APB1RSTR;
    volatile uint32_t AHBENR;
    volatile uint32_t APB2ENR;
    volatile uint32_t APB1ENR;
    volatile uint32_t BDCR;
    volatile uint32_t CSR;
} RCC_TypeDef;

typedef struct {
    volatile uint32_t SR;
    volatile uint32_t DR;
    volatile uint32_t BRR;
    volatile uint32_t CR1;
    volatile uint32_t CR2;
    volatile uint32_t CR3;
    volatile uint32_t GTPR;
} USART_TypeDef;

typedef struct {
    volatile uint32_t ACR;
    volatile uint32_t KEYR;
    volatile uint32_t OPTKEYR;
    volatile uint32_t SR;
    volatile uint32_t CR;
    volatile uint32_t AR;
    volatile uint32_t RESERVED0;
    volatile uint32_t OBR;
    volatile uint32_t WRPR;
} FLASH_TypeDef;

typedef struct {
    volatile uint32_t CR;
    volatile uint32_t CSR;
} PWR_TypeDef;

typedef struct {
    volatile uint32_t RESERVED0;  /* 0x00: BKP base has no register here */
    volatile uint32_t DR1;        /* 0x04 */
    volatile uint32_t DR2;        /* 0x08 */
    volatile uint32_t DR3;        /* 0x0C */
    volatile uint32_t DR4;        /* 0x10 */
    volatile uint32_t DR5;        /* 0x14 */
    volatile uint32_t DR6;        /* 0x18 */
    volatile uint32_t DR7;        /* 0x1C */
    volatile uint32_t DR8;        /* 0x20 */
    volatile uint32_t DR9;        /* 0x24 */
    volatile uint32_t DR10;       /* 0x28 */
} BKP_TypeDef;

typedef struct {
    volatile uint32_t MAPR;
    volatile uint32_t EXTICR[4];
    volatile uint32_t RESERVED0;
    volatile uint32_t MAPR2;
} AFIO_TypeDef;

typedef struct {
    volatile uint32_t CR1;
    volatile uint32_t CR2;
    volatile uint32_t SMCR;
    volatile uint32_t DIER;
    volatile uint32_t SR;
    volatile uint32_t EGR;
    volatile uint32_t CCMR1;
    volatile uint32_t CCMR2;
    volatile uint32_t CCER;
    volatile uint32_t CNT;
    volatile uint32_t PSC;
    volatile uint32_t ARR;
    volatile uint32_t RCR;
    volatile uint32_t CCR1;
    volatile uint32_t CCR2;
    volatile uint32_t CCR3;
    volatile uint32_t CCR4;
    volatile uint32_t BDTR;
    volatile uint32_t DCR;
    volatile uint32_t DMAR;
} TIM_TypeDef;

typedef struct {
    volatile uint32_t SR;
    volatile uint32_t CR1;
    volatile uint32_t CR2;
    volatile uint32_t SMPR1;
    volatile uint32_t SMPR2;
    volatile uint32_t JOFR1;
    volatile uint32_t JOFR2;
    volatile uint32_t JOFR3;
    volatile uint32_t JOFR4;
    volatile uint32_t HTR;
    volatile uint32_t LTR;
    volatile uint32_t SQR1;
    volatile uint32_t SQR2;
    volatile uint32_t SQR3;
    volatile uint32_t JSQR;
    volatile uint32_t JDR1;
    volatile uint32_t JDR2;
    volatile uint32_t JDR3;
    volatile uint32_t JDR4;
    volatile uint32_t DR;
} ADC_TypeDef;

typedef struct {
    volatile uint32_t KR;
    volatile uint32_t PR;
    volatile uint32_t RLR;
    volatile uint32_t SR;
} IWDG_TypeDef;

typedef struct {
    volatile uint32_t ISER[8];
    volatile uint32_t ICER[8];
    volatile uint32_t ISPR[8];
    volatile uint32_t ICPR[8];
    volatile uint32_t IABR[8];
    volatile uint32_t RESERVED0[56];
    volatile uint8_t  IPR[60];
    volatile uint32_t RESERVED1[644];
    volatile uint32_t STIR;
} NVIC_TypeDef;

typedef struct {
    volatile uint32_t CTRL;
    volatile uint32_t LOAD;
    volatile uint32_t VAL;
    volatile uint32_t CALIB;
} SysTick_TypeDef;

typedef struct {
    volatile uint32_t CPUID;
    volatile uint32_t ICSR;
    volatile uint32_t VTOR;
    volatile uint32_t AIRCR;
    volatile uint32_t SCR;
    volatile uint32_t CCR;
    volatile uint8_t  SHP[12];
    volatile uint32_t SHCSR;
    volatile uint32_t CFSR;
    volatile uint32_t HFSR;
    volatile uint32_t DFSR;
    volatile uint32_t MMFAR;
    volatile uint32_t BFAR;
    volatile uint32_t AFSR;
} SCB_TypeDef;

/* ---------------- Pointers ---------------- */
#define GPIOA  ((GPIO_TypeDef *)GPIOA_BASE)
#define GPIOB  ((GPIO_TypeDef *)GPIOB_BASE)
#define GPIOC  ((GPIO_TypeDef *)GPIOC_BASE)
#define USART1 ((USART_TypeDef *)USART1_BASE)
#define USART2 ((USART_TypeDef *)USART2_BASE)
#define USART3 ((USART_TypeDef *)USART3_BASE)
#define RCC    ((RCC_TypeDef *)RCC_BASE)
#define FLASH  ((FLASH_TypeDef *)FLASH_R_BASE)
#define PWR    ((PWR_TypeDef *)PWR_BASE)
#define BKP    ((BKP_TypeDef *)BKP_BASE)
#define AFIO   ((AFIO_TypeDef *)AFIO_BASE)
#define TIM1   ((TIM_TypeDef *)TIM1_BASE)
#define TIM2   ((TIM_TypeDef *)TIM2_BASE)
#define TIM3   ((TIM_TypeDef *)TIM3_BASE)
#define TIM4   ((TIM_TypeDef *)TIM4_BASE)
#define ADC1   ((ADC_TypeDef *)ADC1_BASE)
#define IWDG   ((IWDG_TypeDef *)IWDG_BASE)
#define NVIC   ((NVIC_TypeDef *)NVIC_BASE)
#define SCB    ((SCB_TypeDef *)SCB_BASE)
#define SysTick ((SysTick_TypeDef *)SYSTICK_BASE)

/* ---------------- GPIO pin macros ---------------- */
#define GPIO_PIN_0    (1U << 0)
#define GPIO_PIN_1    (1U << 1)
#define GPIO_PIN_2    (1U << 2)
#define GPIO_PIN_3    (1U << 3)
#define GPIO_PIN_4    (1U << 4)
#define GPIO_PIN_5    (1U << 5)
#define GPIO_PIN_6    (1U << 6)
#define GPIO_PIN_7    (1U << 7)
#define GPIO_PIN_8    (1U << 8)
#define GPIO_PIN_9    (1U << 9)
#define GPIO_PIN_10   (1U << 10)
#define GPIO_PIN_11   (1U << 11)
#define GPIO_PIN_12   (1U << 12)
#define GPIO_PIN_13   (1U << 13)
#define GPIO_PIN_14   (1U << 14)
#define GPIO_PIN_15   (1U << 15)

/* ---------------- GPIO CNF/MODE helpers (4-bit field per pin) ---------------- */
/* MODE: 00=input 01=10MHz 10=2MHz 11=50MHz ; CNF depends on mode.            */
#define GPIO_CNF_MODE_IN_ANALOG   0x0U  /* input, analog            */
#define GPIO_CNF_MODE_IN_FLOAT    0x4U  /* input, floating          */
#define GPIO_CNF_MODE_IN_PULL     0x8U  /* input, pull up/down      */
#define GPIO_CNF_MODE_OUT_PP_2    0x2U  /* output PP 2MHz            */
#define GPIO_CNF_MODE_OUT_PP_10   0x1U  /* output PP 10MHz           */
#define GPIO_CNF_MODE_OUT_PP_50   0x3U  /* output PP 50MHz           */
#define GPIO_CNF_MODE_OUT_OD_50   0x7U  /* output OD 50MHz           */
#define GPIO_CNF_MODE_AF_PP_50    0xBU  /* alt func PP 50MHz         */
#define GPIO_CNF_MODE_AF_OD_50    0xFU  /* alt func OD 50MHz         */

/* ---------------- RCC CR/CFGR bits ---------------- */
#define RCC_CR_HSION      (1U << 0)
#define RCC_CR_HSIRDY     (1U << 1)
#define RCC_CR_HSEON      (1U << 16)
#define RCC_CR_HSERDY     (1U << 17)
#define RCC_CR_PLLON      (1U << 24)
#define RCC_CR_PLLRDY     (1U << 25)

#define RCC_CFGR_SW_HSI   (0U << 0)
#define RCC_CFGR_SW_HSE   (1U << 0)
#define RCC_CFGR_SW_PLL   (2U << 0)
#define RCC_CFGR_SWS_HSI  (0U << 2)
#define RCC_CFGR_SWS_HSE  (1U << 2)
#define RCC_CFGR_SWS_PLL  (2U << 2)
#define RCC_CFGR_HPRE_DIV1 (0U << 4)
#define RCC_CFGR_PPRE1_DIV1 (0U << 8)
#define RCC_CFGR_PPRE1_DIV2 (4U << 8)
#define RCC_CFGR_PPRE2_DIV1 (0U << 11)
#define RCC_CFGR_ADCPRE_DIV4 (1U << 14)
#define RCC_CFGR_ADCPRE_DIV6 (2U << 14)
#define RCC_CFGR_PLLSRC_HSE (1U << 16)
#define RCC_CFGR_PLLMUL9   (7U << 18)   /* x9 */

/* ---------------- RCC APB2ENR bits ---------------- */
#define RCC_APB2ENR_AFIOEN   (1U << 0)
#define RCC_APB2ENR_IOPAEN   (1U << 2)
#define RCC_APB2ENR_IOPBEN   (1U << 3)
#define RCC_APB2ENR_IOPCEN   (1U << 4)
#define RCC_APB2ENR_ADC1EN   (1U << 9)
#define RCC_APB2ENR_TIM1EN   (1U << 11)
#define RCC_APB2ENR_USART1EN (1U << 14)

/* ---------------- RCC APB1ENR bits ---------------- */
#define RCC_APB1ENR_TIM2EN   (1U << 0)
#define RCC_APB1ENR_TIM3EN   (1U << 1)
#define RCC_APB1ENR_TIM4EN   (1U << 2)
#define RCC_APB1ENR_USART2EN (1U << 17)
#define RCC_APB1ENR_USART3EN (1U << 18)
#define RCC_APB1ENR_PWREN    (1U << 28)
#define RCC_APB1ENR_BKPEN    (1U << 27)

/* ---------------- FLASH ACR/CR/SR bits ---------------- */
#define FLASH_ACR_LATENCY_0  (0U << 0)
#define FLASH_ACR_LATENCY_1  (1U << 0)
#define FLASH_ACR_LATENCY_2  (2U << 0)
#define FLASH_ACR_PRFTBE     (1U << 4)

#define FLASH_CR_PG    (1U << 0)
#define FLASH_CR_PER   (1U << 1)
#define FLASH_CR_MER   (1U << 2)
#define FLASH_CR_STRT  (1U << 6)
#define FLASH_CR_LOCK  (1U << 7)
#define FLASH_SR_BSY      (1U << 0)
#define FLASH_SR_PGERR    (1U << 2)
#define FLASH_SR_WRPRTERR (1U << 4)
#define FLASH_SR_EOP      (1U << 5)

/* ---------------- PWR CR bits ---------------- */
#define PWR_CR_DBP     (1U << 8)

/* ---------------- AFIO MAPR SWJ config ---------------- */
#define AFIO_MAPR_SWJ_MASK   (7U << 24)
#define AFIO_MAPR_SWJ_NOJTAG (1U << 24)   /* JTAG-DP disabled, SW-DP enabled */

/* ---------------- DBGMCU (debug peripheral) ---------------- */
/* Lets the debugger freeze the independent watchdog / timers while the core
 * is halted, so SWD inspection is possible without the IWDG resetting the MCU
 * out from under us. Harmless in production (only matters when a debugger is
 * actually attached). */
#define DBGMCU_BASE    0xE0042000U
typedef struct {
    volatile uint32_t CR;        /* only CR is used here */
    volatile uint32_t RESERVED[3];
} DBGMCU_TypeDef;
#define DBGMCU  ((DBGMCU_TypeDef *)DBGMCU_BASE)
#define DBGMCU_CR_IWDG_STOP  (1U << 8)   /* freeze IWDG when core halted */

/* ---------------- USART SR/CR1/CR2/CR3 bits ---------------- */
#define USART_SR_RXNE (1U << 5)
#define USART_SR_TXE  (1U << 7)
#define USART_SR_TC   (1U << 6)
#define USART_SR_PE   (1U << 0)
#define USART_SR_FE   (1U << 1)
#define USART_SR_NE   (1U << 2)
#define USART_SR_ORE  (1U << 3)
#define USART_SR_RX_ERRORS (USART_SR_PE | USART_SR_FE | USART_SR_NE | USART_SR_ORE)
#define USART_CR1_UE  (1U << 13)
#define USART_CR1_TE  (1U << 3)
#define USART_CR1_RE  (1U << 2)
#define USART_CR1_RXNEIE (1U << 5)
#define USART_CR1_TCIE   (1U << 6)
#define USART_CR2_STOP1  (0U << 12)  /* 1 stop bit */

/* ---------------- TIM CR1/CR2/EGR/CCER/CCMR bits ---------------- */
#define TIM_CR1_CEN   (1U << 0)
#define TIM_CR1_ARPE  (1U << 7)
#define TIM_CR2_MMS_RESET (0U << 4)  /* master mode: reset on trigger */
#define TIM_EGR_UG    (1U << 0)
#define TIM_CCER_CC1E (1U << 0)
#define TIM_CCER_CC2E (1U << 4)
#define TIM_CCER_CC3E (1U << 8)
#define TIM_CCER_CC4E (1U << 12)
/* CCMR: output compare mode 110 = PWM mode 1, with preload enable */
#define TIM_CCMR_OCM_PWM1_PE  ((6U << 4) | (1U << 3))   /* for CH1 (bits 4-6 =110, 3=PE) */
#define TIM_CCMR_OCM_PWM1_PE_CH2 ((6U << 12) | (1U << 11))

/* ---------------- TIM channel identifiers ---------------- */
#define TIM_CHANNEL_1  1U
#define TIM_CHANNEL_2  2U
#define TIM_CHANNEL_3  3U
#define TIM_CHANNEL_4  4U

/* ---------------- ADC CR/SR/SMPR bits ---------------- */
#define ADC_SR_EOC     (1U << 1)
#define ADC_CR2_ADON   (1U << 0)
#define ADC_CR2_CAL    (1U << 2)
#define ADC_CR2_RSTCAL (1U << 3)
#define ADC_CR2_SWSTART (1U << 22)
#define ADC_CR2_TSVREFE (1U << 23)  /* enable internal temp sensor + VREFINT channels */
#define ADC_CR2_EXTSEL_SWSTART (7U << 17)  /* software start */
#define ADC_CR2_EXTTRIG (1U << 20)
#define ADC_SQR1_L_1CONV (0U << 20)
#define ADC_SQR3_SQ1_CH0 (0U << 0)
#define ADC_SMPR2_SMP0_239_5 (7U << 0)  /* channel 0 sample time 239.5 cycles */

/* ---------------- IWDG bits ---------------- */
#define IWDG_KR_ACCESS  0x5555U
#define IWDG_KR_RELOAD  0xAAAAU
#define IWDG_KR_START   0xCCCCU

/* ---------------- NVIC helpers ---------------- */
#define NVIC_EnableIRQ(irq)  (NVIC->ISER[(irq) >> 5] |= (1U << ((irq) & 0x1F)))
#define NVIC_DisableIRQ(irq) (NVIC->ICER[(irq) >> 5] |= (1U << ((irq) & 0x1F)))

/* IRQ numbers (subset used by the app) */
#define USART1_IRQn  37
#define USART3_IRQn  39

/* ---------------- SysTick bits ---------------- */
#define SYSTICK_CTRL_ENABLE   (1U << 0)
#define SYSTICK_CTRL_TICKINT  (1U << 1)
#define SYSTICK_CTRL_CLKSOURCE (1U << 2)  /* 1 = core clock */

/* ---------------- CMSIS-style helpers (normally in core_cm3) ---------------- */
__attribute__((always_inline)) static inline void __set_MSP(uint32_t topOfMainStack) {
    __asm volatile ("msr msp, %0" : : "r" (topOfMainStack) : );
}

__attribute__((always_inline)) static inline void NVIC_SystemReset(void) {
    __asm volatile ("dsb 0xF" ::: "memory");
    SCB->AIRCR = (uint32_t)((0x05FAUL << 16) | (1UL << 2));  /* SYSRESETREQ */
    __asm volatile ("dsb 0xF" ::: "memory");
    for (;;) { }
}

#endif /* STM32F1_REG_H */
