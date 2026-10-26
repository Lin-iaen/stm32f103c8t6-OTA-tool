# App 源码（IO 控制台参考固件）

本目录是 `release/app-v0.1.38.bin` / `.hex` 的源码。它是一个寄存器级、
无 HAL 的参考应用，把 F103C8T6 变成一个可通过 UART/BLE 远程操作的
IO 控制台：

- GPIO 配置 / 读写
- ADC 单次采样（0..17 通道，返回 mV）
- TIM2/TIM3 共 8 路 PWM
- 周期遥测（运行时间、PA0 电压、PWM 状态）
- 参数持久化（心跳周期、ADC 参考电压）
- 接收 `APP_OTA_START` 后置 OTA 标志并复位，进入配套 Bootloader

它同时是 OTA 的**最小接口示例**：自定义 App 只要实现 `APP_PING`、
`APP_GET_VERSION`、`APP_OTA_START` 三个命令，就能被 `fwb ota` 升级。
完整命令表见 [../../docs/04-protocol.md](../../docs/04-protocol.md)。

## 编译

需要 `arm-none-eabi-gcc` 和 `make`：

```bash
make -C firmware/app
# 产物：
#   firmware/app/app.bin   （约 4.6 KB）
#   firmware/app/app.hex
```

App 链接在 `0x08003000`，由 Bootloader 启动；首次也可以直接烧到该地址。
**不要**烧到 `0x08000000`，那是 Bootloader 的位置。

生成与版本号一致的发布文件（版本取自 `firmware/common/protocol.h`）：

```bash
make -C firmware/app release
# release/app-v0.1.38.bin
# release/app-v0.1.38.hex
```

修改 `APP_VERSION_MAJOR/MINOR/PATCH` 后重新构建即可得到新文件名。
`release` 目标会拒绝 `FLASH_SIZE_FORCE_KB` 测试构建，避免误发布。

## 配置页

App 运行时通过 `F_SIZE` 选择配置页，与 Bootloader 使用同一份
`firmware/common/flash_layout.h`：

| 芯片 | 配置页 | 保存内容 |
|---|---|---|
| 64 KB | `0x0800FC00` | `heartbeat_ms`、`vref_mv`、magic、版本、CRC16 |
| 128 KB | `0x0801FC00` | 同上 |

`APP_SET_PARAM` 修改参数后立即擦写配置页；上电时 `config_load()` 校验
magic / 版本 / CRC16，任一不符就回退到默认值（1000 ms、3300 mV）。

## 64 KB 布局测试

在 128 KB 板上验证 64 KB 分支时，可以用同一份源码强制按 64 KB 编译：

```bash
make -C firmware/app clean
make -C firmware/app FLASH_SIZE_FORCE_KB=64
```

此时 App 把配置页写到 `0x0800FC00`，不会碰 128 KB 配置页。这个构建
只用于验证，**不要**发布；正式版请用默认构建。

## 替换成自己的 App

1. 链接地址设为 `0x08003000`，向量表在启动时重定位到 `APP_BASE`
   （参考 `Src/main.c` 的 `SCB->VTOR = APP_BASE`）。
2. 保留 `APP_PING`（`0x10`）与 `APP_GET_VERSION`（`0x11`）。
3. 实现 `APP_OTA_START`（`0x13`）：收到 4 字节总长度后，在备份寄存器
   `BKP->DR1` 写入 `OTA_MAGIC`，然后 `NVIC_SystemReset()`。
4. 镜像大小不要超过 `BL_QUERY` 报告的实际上限（64 KB 芯片 52,224 B，
   128 KB 芯片 117,760 B）。
5. 链接脚本可直接复用 `STM32F103C8Tx_FLASH.ld`。

## 目录

```
firmware/app/
├── Src/main.c                    # 全部应用逻辑（IO 控制台 + OTA 触发）
├── Inc/stm32f1_reg.h             # 寄存器定义
├── startup_stm32f103xb_app.s     # 向量表 / 启动代码
├── STM32F103C8Tx_FLASH.ld        # 链接到 0x08003000
├── Makefile
└── README.md
```
