# 固件源码（自动识别 64/128 KB Flash）

本目录是 `release/bootloader-v0.1.2.bin` 与 `release/app-v0.1.39.bin`
的源码。**Bootloader 和 App 各只有一份**：启动时读取芯片的 `F_SIZE`
寄存器（`0x1FFFF7E0`），在运行时选择 64 KB 或 128 KB 布局，不需要为
两种芯片分别编译。

| 芯片 | App 区 | App 最大镜像 | 配置页 |
|---|---|---|---|
| 64 KB | `0x08003000`，51 KB | 52,224 B | `0x0800FC00` |
| 128 KB | `0x08003000`，115 KB | 117,760 B | `0x0801FC00` |

`F_SIZE` 读数不在 64..128 范围（例如某些克隆片返回 `0xFFFF`）时按 64 KB
保守处理，避免写到不存在的 Flash。

Bootloader 自身固定在 `0x08000000`，占用 12 KB；布局选择只影响 App 擦除/
写入的上界和配置页地址。`firmware/app` 是配套的 IO 控制台参考固件，
也可以替换成自己的 App——只需实现 `APP_PING`、`APP_GET_VERSION` 和
`APP_OTA_START`，详见 [app/README.md](app/README.md)。

## 编译

需要 `arm-none-eabi-gcc` 和 `make`：

```bash
make -C firmware/bootloader
# 产物：firmware/bootloader/bl.bin（约 3.3 KB）

make -C firmware/app
# 产物：firmware/app/app.bin / app.hex（约 4.6 KB）

make -C firmware/app release
# 产物：release/app-v0.1.39.bin / .hex（版本取自 protocol.h）
```

把 Bootloader 烧录到 `0x08000000`。例如 ST-Link：

```bash
st-flash write firmware/bootloader/bl.bin 0x08000000
st-flash reset
```

App 正常通过 OTA 写入；首次也可以直接烧到 `0x08003000`（必须在
Bootloader 之后）。默认构建就是自动识别版，和 `release/` 中的预编译
镜像对应。

## 64 KB 布局测试

在 128 KB 板上验证 64 KB 分支时，可以用同一份源码强制按 64 KB 编译：

```bash
make -C firmware/bootloader clean
make -C firmware/bootloader FLASH_SIZE_FORCE_KB=64

make -C firmware/app clean
make -C firmware/app FLASH_SIZE_FORCE_KB=64
```

此时 `BL_QUERY` 返回 `max_size=52224`，60 KB 镜像会在主机侧被拒绝，
直接发 `BL_START` 也会返回 `PARAM`；App 则把配置页写到 `0x0800FC00`，
不会碰 128 KB 的配置页。强制 64 KB 构建还会给链接器传
`--defsym=APP_FLASH_LEN=0xCC00`，**镜像超过 51 KB 会直接链接失败**，
不会再出现"链接器按 115 KB 放行、运行期却按 51 KB 擦写"的两套上限。

> 这个强制版本只用于验证，**不要**作为正式发布固件；`make release`
> 会拒绝这种构建。验证完成后记得重新编译并烧回默认的自动识别版。

## 目录

```
firmware/
├── common/
│   ├── flash_layout.h    # F_SIZE 读取、64/128KB 布局、配置页/上限
│   ├── protocol.h        # 线协议与版本号（Bootloader/App/主机共用）
│   ├── crc.c / crc.h     # CRC16-MODBUS / CRC32-IEEE
├── bootloader/
│   ├── Src/main.c        # DFU 状态机、Flash 操作、USART1
│   ├── Inc/              # bootloader.h / 寄存器定义
│   ├── startup_stm32f103xb.s
│   ├── STM32F103C8Tx_FLASH.ld
│   └── Makefile
└── app/
    ├── Src/main.c        # IO 控制台 + OTA 触发
    ├── Inc/              # 寄存器定义
    ├── startup_stm32f103xb_app.s
    ├── STM32F103C8Tx_FLASH.ld
    ├── Makefile
    └── README.md
```

协议细节见 [../docs/04-protocol.md](../docs/04-protocol.md)。

## 版本变更

### Bootloader v0.1.2

- **`BL_ABORT` 现在真的能中止升级**：原来只清 `OTA_MAGIC`（App 请求 DFU 时写的值），
  而 `BL_START` 写的是 `OTA_UPDATE_MAGIC`，所以"升级到一半取消"永远清不掉标志，
  复位后又进 DFU。现在无条件清标志再复位；App 无效时 `main()` 仍停在 DFU，
  不会误启动半截镜像。

### App v0.1.39

见 [app/README.md](app/README.md#本版修复v0139)：栈峰值、帧重同步、遥测电压、
ADC 启动时序、参数保存错误上报、uint16 参数、config 页 CRC 与版本。
