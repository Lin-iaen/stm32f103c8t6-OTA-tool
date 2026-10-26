/**
 * Linker script for the APPLICATION (STM32F103C8/CB).
 * Flash: ORIGIN = 0x08003000, LENGTH = 115 KB (0x1CC00).
 *
 * The image must fit the *smaller* 64KB layout if it has to run on a
 * genuine C8T6: the bootloader's BL_QUERY reports the real limit at
 * runtime (51 KB on 64KB parts, 115 KB on 128KB parts) and the host
 * refuses an image that does not fit. Linking to 115 KB here simply
 * lets a 128KB part use the upper half.
 *
 * The last 1KB page (0x0800FC00 on 64KB, 0x0801FC00 on 128KB) is the
 * config page; the app selects it at runtime from the flash-size register.
 * RAM: 0x20000000, LENGTH = 20 KB.
 *
 * No heap (bare-metal super-loop design); a 1 KB stack is reserved at the top
 * of RAM. ENTRY = Reset_Handler (per startup_stm32f103xb_app.s).
 */
ENTRY(Reset_Handler)

_estack = 0x20000000 + 20K;
_Min_Stack_Size = 0x400;

/* App region length: 115 KB for the 128KB layout. Forced-64KB test builds
 * pass -Wl,--defsym=APP_FLASH_LEN=0xCC00 (51 KB) so the linker enforces the
 * same limit the bootloader will use at runtime from F_SIZE. */
APP_FLASH_LEN = DEFINED(APP_FLASH_LEN) ? APP_FLASH_LEN : 0x1CC00;

MEMORY
{
  FLASH (rx)      : ORIGIN = 0x08003000, LENGTH = APP_FLASH_LEN
  RAM   (xrw)     : ORIGIN = 0x20000000, LENGTH = 20K
}

SECTIONS
{
  .isr_vector :
  {
    . = ALIGN(4);
    KEEP(*(.isr_vector))
    . = ALIGN(4);
  } >FLASH

  .text :
  {
    . = ALIGN(4);
    *(.text)
    *(.text.*)
    *(.glue_7)
    *(.glue_7t)
    *(.eh_frame)
    . = ALIGN(4);
    _etext = .;
  } >FLASH

  .rodata :
  {
    . = ALIGN(4);
    *(.rodata)
    *(.rodata.*)
    . = ALIGN(4);
  } >FLASH

  .ARM.extab   : { *(.ARM.extab* .gnu.linkonce.armextab.*) } >FLASH
  .ARM.exidx   : { __exidx_start = .; *(.ARM.exidx* .gnu.linkonce.armexidx.*); __exidx_end = .; } >FLASH

  _sidata = LOADADDR(.data);

  .data :
  {
    . = ALIGN(4);
    _sdata = .;
    *(.data)
    *(.data.*)
    . = ALIGN(4);
    _edata = .;
  } >RAM AT> FLASH

  .bss :
  {
    . = ALIGN(4);
    _sbss = .;
    *(.bss)
    *(.bss.*)
    *(COMMON)
    . = ALIGN(4);
    _ebss = .;
  } >RAM

  ._user_stack :
  {
    . = ALIGN(8);
    . = . + _Min_Stack_Size;
    . = ALIGN(8);
  } >RAM

  /* Provide an end symbol (no heap, but kept for compatibility). */
  PROVIDE ( end = . );

  /DISCARD/ : { *(.note .note.*) }
}

/* Fail the link instead of silently producing an image the bootloader will
 * refuse (or that would overlap the config page). */
ASSERT(_sidata + SIZEOF(.data) <= ORIGIN(FLASH) + LENGTH(FLASH),
       "app image does not fit the app region")
ASSERT(ORIGIN(FLASH) + LENGTH(FLASH) <= 0x0801FC00,
       "app region overlaps the 128KB config page")
