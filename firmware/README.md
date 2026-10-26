# Bootloader 源码（自动识别 64/128 KB Flash）

本目录是 `release/bootloader-v0.1.1.bin` 的源码。**只有一份 Bootloader**：
启动时读取芯片的 `F_SIZE` 寄存器（`0x1FFFF7E0`），在运行时选择 64 KB 或
128 KB 布局，不需要为两种芯片分别编译。

| 芯片 | App 区 | App 最大镜像 | 配置页 |
|---|---|---|---|
| 64 KB | `0x08003000`，51 KB | 52,224 B | `0x0800FC00` |
| 128 KB | `0x08003000`，115 KB | 117,760 B | `0x0801FC00` |

`F_SIZE` 读数不在 64..128 范围（例如某些克隆片返回 `0xFFFF`）时按 64 KB
保守处理，避免写到不存在的 Flash。

Bootloader 自身固定在 `0x08000000`，占用 12 KB；布局选择只影响 App 擦除/
写入的上界和配置页地址。App 源码不在本仓库范围内，`release/app-v0.1.38.bin`
是配套预编译镜像。

## 编译

需要 `arm-none-eabi-gcc` 和 `make`：

```bash
make -C firmware/bootloader
# 产物：firmware/bootloader/bl.bin（约 3.3 KB）
```

烧录到 `0x08000000`。例如 ST-Link：

```bash
st-flash write firmware/bootloader/bl.bin 0x08000000
st-flash reset
```

默认构建就是自动识别版，和 `release/bootloader-v0.1.1.bin` 对应。

## 64 KB 布局测试

在 128 KB 板上验证 64 KB 分支时，可以用同一份源码强制按 64 KB 编译：

```bash
make -C firmware/bootloader clean
make -C firmware/bootloader FLASH_SIZE_FORCE_KB=64
```

此时 `BL_QUERY` 返回 `max_size=52224`，60 KB 镜像会在主机侧被拒绝，
直接发 `BL_START` 也会返回 `PARAM`。

> 这个强制版本只用于验证，**不要**作为正式发布固件；正式版请用默认构建。
> 验证完成后记得重新编译并烧回默认的自动识别版。

## 目录

```
firmware/
├── common/
│   ├── flash_layout.h    # F_SIZE 读取、64/128KB 布局、配置页/上限
│   ├── protocol.h        # 线协议与版本号（Bootloader/App/主机共用）
│   ├── crc.c / crc.h     # CRC16-MODBUS / CRC32-IEEE
└── bootloader/
    ├── Src/main.c        # DFU 状态机、Flash 操作、USART1
    ├── Inc/              # bootloader.h / 寄存器定义
    ├── startup_stm32f103xb.s
    ├── STM32F103C8Tx_FLASH.ld
    └── Makefile
```

协议细节见 [../docs/04-protocol.md](../docs/04-protocol.md)。
