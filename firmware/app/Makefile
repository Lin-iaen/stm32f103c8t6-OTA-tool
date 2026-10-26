# STM32F103C8T6 reference App Makefile (register-level, no HAL).
# Self-contained: Src/main.c is the whole application.
# Requires only arm-none-eabi-gcc in PATH.

CC      = arm-none-eabi-gcc
OBJCOPY = arm-none-eabi-objcopy
SIZE    = arm-none-eabi-size
CPU     = -mcpu=cortex-m3 -mthumb -mfloat-abi=soft
CFLAGS  = $(CPU) -O2 -Wall -Wextra -fno-common \
          -ffunction-sections -fdata-sections -IInc -I../common \
          -MMD -MP

# Test hook: compile the same source as if F_SIZE reported 64KB, so the app
# writes its config page at 0x0800FC00. Example: make FLASH_SIZE_FORCE_KB=64
ifdef FLASH_SIZE_FORCE_KB
CFLAGS += -DFLASH_SIZE_FORCE_KB=$(FLASH_SIZE_FORCE_KB)
endif
LDFLAGS = $(CPU) -TSTM32F103C8Tx_FLASH.ld -Wl,-Map=app.map -Wl,--gc-sections
STARTUP = startup_stm32f103xb_app.s
SRC     = Src/main.c ../common/crc.c
OBJ     = $(SRC:.c=.o)
DEPS    = $(OBJ:.o=.d)

# Version comes from firmware/common/protocol.h (single source of truth).
APP_VERSION = $(shell sed -n 's/^#define APP_VERSION_MAJOR[[:space:]]*//p' ../common/protocol.h).$(shell sed -n 's/^#define APP_VERSION_MINOR[[:space:]]*//p' ../common/protocol.h).$(shell sed -n 's/^#define APP_VERSION_PATCH[[:space:]]*//p' ../common/protocol.h)

all: app.elf app.bin app.hex

app.elf: $(OBJ) $(STARTUP) STM32F103C8Tx_FLASH.ld
	$(CC) $(LDFLAGS) -o $@ $(STARTUP) $(OBJ) -lm

app.bin: app.elf
	$(OBJCOPY) -O binary $< $@
	$(SIZE) $<

app.hex: app.elf
	$(OBJCOPY) -O ihex $< $@

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

-include $(DEPS)

# OTA release artifact: release/app-vX.Y.Z.bin/.hex
release: app.bin app.hex
	@if [ -n "$(FLASH_SIZE_FORCE_KB)" ]; then \
		echo "release: refusing to publish a FLASH_SIZE_FORCE_KB test build" >&2; \
		exit 1; \
	fi
	@mkdir -p ../../release
	cp app.bin ../../release/app-v$(APP_VERSION).bin
	cp app.hex ../../release/app-v$(APP_VERSION).hex
	@echo "release: ../../release/app-v$(APP_VERSION).bin"
	@echo "release: ../../release/app-v$(APP_VERSION).hex"

clean:
	rm -f app.elf app.bin app.hex app.map $(OBJ) $(DEPS)

.PHONY: all clean release
