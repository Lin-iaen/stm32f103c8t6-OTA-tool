# f103-workbench Bootloader Makefile (register-level, no HAL).
# Requires only arm-none-eabi-gcc in PATH.
#
# Ported from kurui365/smart-robot-car (MIT). Changes vs original:
#   - USART3 -> USART1 for Blue Pill (PA9/PA10)

CC      = arm-none-eabi-gcc
OBJCOPY = arm-none-eabi-objcopy
SIZE    = arm-none-eabi-size
CPU     = -mcpu=cortex-m3 -mthumb -mfloat-abi=soft
CFLAGS  = $(CPU) -O2 -Wall -Wextra -fno-common \
          -ffunction-sections -fdata-sections -IInc -I../common \
          -MMD -MP

# Test hook: compile the same source as if F_SIZE reported 64KB.
# Example: make FLASH_SIZE_FORCE_KB=64
ifdef FLASH_SIZE_FORCE_KB
CFLAGS += -DFLASH_SIZE_FORCE_KB=$(FLASH_SIZE_FORCE_KB)
endif
LDFLAGS = $(CPU) -TSTM32F103C8Tx_FLASH.ld -Wl,-Map=bl.map -Wl,--gc-sections
STARTUP = startup_stm32f103xb.s
SRC     = Src/main.c ../common/crc.c
OBJ     = $(SRC:.c=.o)
DEPS    = $(OBJ:.o=.d)

all: bl.elf bl.bin

bl.elf: $(OBJ) $(STARTUP) STM32F103C8Tx_FLASH.ld
	$(CC) $(LDFLAGS) -o $@ $(STARTUP) $(OBJ) -lm

bl.bin: bl.elf
	$(OBJCOPY) -O binary $< $@
	$(SIZE) $<

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

-include $(DEPS)

clean:
	rm -f bl.elf bl.bin bl.map $(OBJ) $(DEPS)

.PHONY: all clean
