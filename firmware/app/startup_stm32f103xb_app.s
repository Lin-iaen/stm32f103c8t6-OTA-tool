/**
 * startup_stm32f103xb_app.s - Startup for the APPLICATION (STM32F103C8T6).
 *
 * Unlike the bootloader, the application has initialized .data and .bss, so
 * Reset_Handler copies .data from flash to RAM and zeroes .bss before calling
 * SystemInit()/main(). Full external interrupt vector table (medium-density
 * F103xB). Every handler defaults to an infinite loop unless overridden.
 */
  .syntax unified
  .cpu cortex-m3
  .thumb

  .section .isr_vector, "a"
  .type g_pfnVectors, %object

g_pfnVectors:
  .word _estack
  .word Reset_Handler
  .word NMI_Handler
  .word HardFault_Handler
  .word MemManage_Handler
  .word BusFault_Handler
  .word UsageFault_Handler
  .word 0
  .word 0
  .word 0
  .word 0
  .word SVC_Handler
  .word DebugMon_Handler
  .word 0
  .word PendSV_Handler
  .word SysTick_Handler

  /* External Interrupts (STM32F103xB, IRQ0..IRQ59) */
  .word WWDG_IRQHandler
  .word PVD_IRQHandler
  .word TAMPER_IRQHandler
  .word RTC_IRQHandler
  .word FLASH_IRQHandler
  .word RCC_IRQHandler
  .word EXTI0_IRQHandler
  .word EXTI1_IRQHandler
  .word EXTI2_IRQHandler
  .word EXTI3_IRQHandler
  .word EXTI4_IRQHandler
  .word DMA1_Channel1_IRQHandler
  .word DMA1_Channel2_IRQHandler
  .word DMA1_Channel3_IRQHandler
  .word DMA1_Channel4_IRQHandler
  .word DMA1_Channel5_IRQHandler
  .word DMA1_Channel6_IRQHandler
  .word DMA1_Channel7_IRQHandler
  .word ADC1_2_IRQHandler
  .word USB_HP_CAN1_TX_IRQHandler
  .word USB_LP_CAN1_RX0_IRQHandler
  .word CAN1_RX1_IRQHandler
  .word CAN1_SCE_IRQHandler
  .word EXTI9_5_IRQHandler
  .word TIM1_BRK_IRQHandler
  .word TIM1_UP_IRQHandler
  .word TIM1_TRG_COM_IRQHandler
  .word TIM1_CC_IRQHandler
  .word TIM2_IRQHandler
  .word TIM3_IRQHandler
  .word TIM4_IRQHandler
  .word I2C1_EV_IRQHandler
  .word I2C1_ER_IRQHandler
  .word I2C2_EV_IRQHandler
  .word I2C2_ER_IRQHandler
  .word SPI1_IRQHandler
  .word SPI2_IRQHandler
  .word USART1_IRQHandler
  .word USART2_IRQHandler
  .word USART3_IRQHandler
  .word EXTI15_10_IRQHandler
  .word RTC_Alarm_IRQHandler
  .word USBWakeUp_IRQHandler
  .word TIM8_BRK_IRQHandler
  .word TIM8_UP_IRQHandler
  .word TIM8_TRG_COM_IRQHandler
  .word TIM8_CC_IRQHandler
  .word ADC3_IRQHandler
  .word FSMC_IRQHandler
  .word SDIO_IRQHandler
  .word TIM5_IRQHandler
  .word SPI3_IRQHandler
  .word UART4_IRQHandler
  .word UART5_IRQHandler
  .word TIM6_IRQHandler
  .word TIM7_IRQHandler
  .word DMA2_Channel1_IRQHandler
  .word DMA2_Channel2_IRQHandler
  .word DMA2_Channel3_IRQHandler
  .word DMA2_Channel4_5_IRQHandler
  .size g_pfnVectors, . - g_pfnVectors

  .section .text.Reset_Handler, "ax"
  .global Reset_Handler
  .type Reset_Handler, %function
Reset_Handler:
  ldr  sp, =_estack

  /* Copy .data from its LMA (in flash) to its VMA (in RAM). */
  ldr  r0, =_sdata
  ldr  r1, =_edata
  ldr  r2, =_sidata
  b    2f
1:
  ldr  r3, [r2], #4
  str  r3, [r0], #4
2:
  cmp  r0, r1
  bcc  1b

  /* Zero .bss. */
  ldr  r0, =_sbss
  ldr  r1, =_ebss
  movs r3, #0
3:
  cmp  r0, r1
  bcs  4f
  str  r3, [r0], #4
  b    3b
4:
  bl   SystemInit
  bl   main
  b    .

  .section .text.Default_Handler, "ax"
  .global Default_Handler
  .type Default_Handler, %function
Default_Handler:
  b    .
  .size Default_Handler, . - Default_Handler

  /* Weak aliases: every handler falls back to Default_Handler */
  .weak NMI_Handler
  .set  NMI_Handler, Default_Handler
  .weak HardFault_Handler
  .set  HardFault_Handler, Default_Handler
  .weak MemManage_Handler
  .set  MemManage_Handler, Default_Handler
  .weak BusFault_Handler
  .set  BusFault_Handler, Default_Handler
  .weak UsageFault_Handler
  .set  UsageFault_Handler, Default_Handler
  .weak SVC_Handler
  .set  SVC_Handler, Default_Handler
  .weak DebugMon_Handler
  .set  DebugMon_Handler, Default_Handler
  .weak PendSV_Handler
  .set  PendSV_Handler, Default_Handler
  .weak SysTick_Handler
  .set  SysTick_Handler, Default_Handler

  .weak WWDG_IRQHandler
  .set  WWDG_IRQHandler, Default_Handler
  .weak PVD_IRQHandler
  .set  PVD_IRQHandler, Default_Handler
  .weak TAMPER_IRQHandler
  .set  TAMPER_IRQHandler, Default_Handler
  .weak RTC_IRQHandler
  .set  RTC_IRQHandler, Default_Handler
  .weak FLASH_IRQHandler
  .set  FLASH_IRQHandler, Default_Handler
  .weak RCC_IRQHandler
  .set  RCC_IRQHandler, Default_Handler
  .weak EXTI0_IRQHandler
  .set  EXTI0_IRQHandler, Default_Handler
  .weak EXTI1_IRQHandler
  .set  EXTI1_IRQHandler, Default_Handler
  .weak EXTI2_IRQHandler
  .set  EXTI2_IRQHandler, Default_Handler
  .weak EXTI3_IRQHandler
  .set  EXTI3_IRQHandler, Default_Handler
  .weak EXTI4_IRQHandler
  .set  EXTI4_IRQHandler, Default_Handler
  .weak DMA1_Channel1_IRQHandler
  .set  DMA1_Channel1_IRQHandler, Default_Handler
  .weak DMA1_Channel2_IRQHandler
  .set  DMA1_Channel2_IRQHandler, Default_Handler
  .weak DMA1_Channel3_IRQHandler
  .set  DMA1_Channel3_IRQHandler, Default_Handler
  .weak DMA1_Channel4_IRQHandler
  .set  DMA1_Channel4_IRQHandler, Default_Handler
  .weak DMA1_Channel5_IRQHandler
  .set  DMA1_Channel5_IRQHandler, Default_Handler
  .weak DMA1_Channel6_IRQHandler
  .set  DMA1_Channel6_IRQHandler, Default_Handler
  .weak DMA1_Channel7_IRQHandler
  .set  DMA1_Channel7_IRQHandler, Default_Handler
  .weak ADC1_2_IRQHandler
  .set  ADC1_2_IRQHandler, Default_Handler
  .weak USB_HP_CAN1_TX_IRQHandler
  .set  USB_HP_CAN1_TX_IRQHandler, Default_Handler
  .weak USB_LP_CAN1_RX0_IRQHandler
  .set  USB_LP_CAN1_RX0_IRQHandler, Default_Handler
  .weak CAN1_RX1_IRQHandler
  .set  CAN1_RX1_IRQHandler, Default_Handler
  .weak CAN1_SCE_IRQHandler
  .set  CAN1_SCE_IRQHandler, Default_Handler
  .weak EXTI9_5_IRQHandler
  .set  EXTI9_5_IRQHandler, Default_Handler
  .weak TIM1_BRK_IRQHandler
  .set  TIM1_BRK_IRQHandler, Default_Handler
  .weak TIM1_UP_IRQHandler
  .set  TIM1_UP_IRQHandler, Default_Handler
  .weak TIM1_TRG_COM_IRQHandler
  .set  TIM1_TRG_COM_IRQHandler, Default_Handler
  .weak TIM1_CC_IRQHandler
  .set  TIM1_CC_IRQHandler, Default_Handler
  .weak TIM2_IRQHandler
  .set  TIM2_IRQHandler, Default_Handler
  .weak TIM3_IRQHandler
  .set  TIM3_IRQHandler, Default_Handler
  .weak TIM4_IRQHandler
  .set  TIM4_IRQHandler, Default_Handler
  .weak I2C1_EV_IRQHandler
  .set  I2C1_EV_IRQHandler, Default_Handler
  .weak I2C1_ER_IRQHandler
  .set  I2C1_ER_IRQHandler, Default_Handler
  .weak I2C2_EV_IRQHandler
  .set  I2C2_EV_IRQHandler, Default_Handler
  .weak I2C2_ER_IRQHandler
  .set  I2C2_ER_IRQHandler, Default_Handler
  .weak SPI1_IRQHandler
  .set  SPI1_IRQHandler, Default_Handler
  .weak SPI2_IRQHandler
  .set  SPI2_IRQHandler, Default_Handler
  .weak USART1_IRQHandler
  .set  USART1_IRQHandler, Default_Handler
  .weak USART2_IRQHandler
  .set  USART2_IRQHandler, Default_Handler
  .weak USART3_IRQHandler
  .set  USART3_IRQHandler, Default_Handler
  .weak EXTI15_10_IRQHandler
  .set  EXTI15_10_IRQHandler, Default_Handler
  .weak RTC_Alarm_IRQHandler
  .set  RTC_Alarm_IRQHandler, Default_Handler
  .weak USBWakeUp_IRQHandler
  .set  USBWakeUp_IRQHandler, Default_Handler
  .weak TIM8_BRK_IRQHandler
  .set  TIM8_BRK_IRQHandler, Default_Handler
  .weak TIM8_UP_IRQHandler
  .set  TIM8_UP_IRQHandler, Default_Handler
  .weak TIM8_TRG_COM_IRQHandler
  .set  TIM8_TRG_COM_IRQHandler, Default_Handler
  .weak TIM8_CC_IRQHandler
  .set  TIM8_CC_IRQHandler, Default_Handler
  .weak ADC3_IRQHandler
  .set  ADC3_IRQHandler, Default_Handler
  .weak FSMC_IRQHandler
  .set  FSMC_IRQHandler, Default_Handler
  .weak SDIO_IRQHandler
  .set  SDIO_IRQHandler, Default_Handler
  .weak TIM5_IRQHandler
  .set  TIM5_IRQHandler, Default_Handler
  .weak SPI3_IRQHandler
  .set  SPI3_IRQHandler, Default_Handler
  .weak UART4_IRQHandler
  .set  UART4_IRQHandler, Default_Handler
  .weak UART5_IRQHandler
  .set  UART5_IRQHandler, Default_Handler
  .weak TIM6_IRQHandler
  .set  TIM6_IRQHandler, Default_Handler
  .weak TIM7_IRQHandler
  .set  TIM7_IRQHandler, Default_Handler
  .weak DMA2_Channel1_IRQHandler
  .set  DMA2_Channel1_IRQHandler, Default_Handler
  .weak DMA2_Channel2_IRQHandler
  .set  DMA2_Channel2_IRQHandler, Default_Handler
  .weak DMA2_Channel3_IRQHandler
  .set  DMA2_Channel3_IRQHandler, Default_Handler
  .weak DMA2_Channel4_5_IRQHandler
  .set  DMA2_Channel4_5_IRQHandler, Default_Handler

  .end
