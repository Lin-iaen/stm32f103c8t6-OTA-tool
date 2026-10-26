/**
 * Linker script for the BOOTLOADER (STM32F103C8T6, 64KB Flash).
 * Flash: 0x08000000, length 12 KB. RAM: 0x20000000, length 20 KB.
 *
 * Minimal: the register-level bootloader needs only .isr_vector/.text/.rodata
 * plus .data/.bss (kept for safety) and the heap/stack region.
 */
ENTRY(Reset_Handler)

_estack = 0x20000000 + 20K;
_Min_Heap_Size = 0x0;
/* 2 KB stack. The DFU code keeps 1 KB-class buffers on the stack
 * (pl[] in main, buf[] in bl_send_response) only for the duration of a
 * single frame; 1 KB was too small and overflowed into .bss, corrupting
 * buffered data and CRC calculations. 2 KB is safe with RAM to spare. */
_Min_Stack_Size = 0x800;

MEMORY
{
  FLASH (rx)      : ORIGIN = 0x08000000, LENGTH = 12K
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

  ._user_heap_stack :
  {
    . = ALIGN(8);
    PROVIDE ( end = . );
    . = . + _Min_Heap_Size;
    . = . + _Min_Stack_Size;
    . = ALIGN(8);
  } >RAM

  /DISCARD/ : { *(.note .note.*) }
}
