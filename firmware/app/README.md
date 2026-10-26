# App 源码（IO 控制台参考固件）

本目录是 `release/app-v0.1.40.bin` / `.hex` 的源码。它是一个寄存器级、
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

App 链接在 `0x08003000`，由 Bootloader 启动。Bootloader 已烧录时，首次
也可以直接把 App 烧到该地址；**不要**烧到 `0x08000000`，那是 Bootloader
的位置。

生成与版本号一致的发布文件（版本取自 `firmware/common/protocol.h`）：

```bash
make -C firmware/app release
# release/app-v0.1.40.bin
# release/app-v0.1.40.hex
```

修改 `APP_VERSION_MAJOR/MINOR/PATCH` 后重新构建即可得到新文件名。
`release` 目标会拒绝 `FLASH_SIZE_FORCE_KB` 测试构建，避免误发布。

## 配置页（v2）

App 运行时通过 `F_SIZE` 选择配置页，与 Bootloader 使用同一份
`firmware/common/flash_layout.h`：

| 芯片 | 配置页 | 保存内容 |
|---|---|---|
| 64 KB | `0x0800FC00` | `heartbeat_ms`(u16)、`vref_mv`(u16)、magic、version、CRC16 |
| 128 KB | `0x0801FC00` | 同上 |

页内布局（v2，12 字节有效）：

```
[0..3] magic 0x4B574348 | [4..5] version=2 | [6..7] CRC16-MODBUS(8..11)
[8..9] heartbeat_ms     | [10..11] vref_mv  | [12..1023] 保留
```

- CRC **只覆盖 8..11 这四个字节**，和注释一致（v1 注释写 `8..end` 但只算了 8 字节）。
- `APP_SET_PARAM` 写失败会回 `PROTO_ERR_FLASH`，不再"假成功"。
- 整页只有**一个**擦写入口：`config_save()` 擦整页、只写前 12 字节。若要在
  同一页存别的东西，必须并进同一个保存函数（或另选页面）。
- v1 → v2 时 magic/version 不匹配，参数会回一次默认值（1000 ms、3300 mV）。

## 64 KB 布局测试

在 128 KB 板上验证 64 KB 分支时，可以用同一份源码强制按 64 KB 编译：

```bash
make -C firmware/app clean
make -C firmware/app FLASH_SIZE_FORCE_KB=64
```

此时 App 把配置页写到 `0x0800FC00`，不会碰 128 KB 配置页；链接器同时把
App 区限制为 51 KB（`APP_FLASH_LEN=0xCC00`），镜像超限会**链接失败**而不是
悄悄越界。这个构建只用于验证，**不要**发布；正式版请用默认构建。

## 替换成自己的 App

1. 链接地址设为 `0x08003000`，向量表在启动时重定位到 `APP_BASE`
   （参考 `Src/main.c` 的 `SCB->VTOR = APP_BASE`）。
2. 保留 `APP_PING`（`0x10`）与 `APP_GET_VERSION`（`0x11`）。
3. 实现 `APP_OTA_START`（`0x13`）：收到 4 字节总长度后，先使能 PWR/BKP
   时钟并置位 `PWR->CR` 的 `PWR_CR_DBP`，在备份寄存器 `BKP->DR1` 写入
   `OTA_MAGIC`，然后 `NVIC_SystemReset()`。
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

## 本版修复（v0.1.39）

> v0.1.40 只同步了 Bootloader 版本常量，功能与 v0.1.39 相同。

| 项 | 改动 |
|---|---|
| 栈峰值 | 帧解析的 1027 B CRC 缓冲改为 `static`，栈需求变成常数 |
| 帧重同步 | `AA AA 55` 现在能把第二个 `AA` 当新帧头（原来整帧静默丢弃） |
| 遥测电压 | ADC 读失败不再报 0 mV：置 flags bit1（vbat invalid） |
| ADC 启动 | 置 `EXTTRIG | EXTSEL=SWSTART`，修掉"每隔一帧 vbat=0"的时序问题 |
| 参数保存 | `config_save()` 返回错误码，失败回 `PROTO_ERR_FLASH` |
| 参数截断 | `heartbeat_ms` 按 uint16 存，不再出现存 70000 读回 4464 |
| config CRC | 注释与实现一致（只覆盖 8..11），版本号升到 2 |
