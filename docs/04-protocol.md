# 04 - 协议规格

本文件是主机工具与设备固件之间的**线级契约**。`fwb_tool/protocol.py`
与固件 `firmware/common/protocol.h` 必须与本文件一致。

## 帧格式

```
[SOF0][SOF1][CMD][LEN_H][LEN_L][PAYLOAD...][CRC16_H][CRC16_L]
 0xAA  0x55
```

- `LEN`：payload 长度，大端，`0..1024`。
- `CRC16-MODBUS`：覆盖 `CMD + LEN_H + LEN_L + PAYLOAD`（不含 SOF），大端。
- 响应约定：命令码 `CMD | 0x80`，payload 首字节为状态码。
- 例外：`GET_TELEMETRY` 的响应直接是遥测帧 `0x9A`，不再额外回 echo。

## CRC 参数

| 算法 | 参数 | 标准向量 `"123456789"` |
|---|---|---|
| CRC16 | MODBUS（poly 0xA001，初值 0xFFFF，反射） | `0x4B37` |
| CRC32 | IEEE（poly 0xEDB88320，初值 0xFFFFFFFF，xorout 0xFFFFFFFF） | `0xCBF43926` |

## Bootloader 命令（0x01..0x0F）

| 码 | 名称 | 请求 payload | 响应 |
|---|---|---|---|
| `0x01` | `BL_QUERY` | 无 | status + bl_ver(3) + app_base(4,BE) + max_size(4,BE) + page(4,BE) |
| `0x02` | `BL_START` | total_len(4,BE) | status；置标志并擦除 App 区 |
| `0x03` | `BL_DATA` | offset(4,BE) + chunk | status；offset 必须偶数且连续 |
| `0x04` | `BL_VERIFY` | crc32(4,BE) | status；三重校验 |
| `0x05` | `BL_JUMP` | 无 | status；仅在 verify 成功后允许 |
| `0x06` | `BL_ABORT` | 无 | status；App 有效时清标志并复位 |

`OTA_MAGIC = 0x4F54`（16 位，"OT"），写入 STM32F1 备份寄存器 DR1，用于
标记"下次启动进入 DFU"。F1 的 BKP_DRx 为 16 位，故该常量必须 ≤ 0xFFFF。

> `app_base` 固定为 `0x08003000`，`page=1024`。`max_size` 由 Bootloader
> 读取芯片 `F_SIZE`（`0x1FFFF7E0`）后决定：64 KB 芯片为 `52224`（51 KB），
> 128 KB 芯片为 `117760`（115 KB）；读数不在 64..128 范围时按 64 KB 处理。
> 主机先按 115 KB 上限接收镜像，真正的上限由 `BL_QUERY` 在擦除前检查：
> 超限镜像会让 `BL_START` 返回 `PARAM`，现有 App 不会被擦除。

## 应用命令（0x10..0x2F）

| 码 | 名称 | 请求 payload | 响应 |
|---|---|---|---|
| `0x10` | `APP_PING` | 无 | status |
| `0x11` | `APP_GET_VERSION` | 无 | status + bl_ver(3) + app_ver(3) |
| `0x12` | `APP_REBOOT` | 无 | status 后复位 |
| `0x13` | `APP_OTA_START` | total_len(4,BE) | status 后置标志并复位进 BL |
| `0x14` | `APP_GPIO_CONFIG` | port(1) pin(1) mode(1) pull(1) | status |
| `0x15` | `APP_GPIO_WRITE` | port(1) pin(1) value(1) | status |
| `0x16` | `APP_GPIO_READ` | port(1) pin(1) | status + value(1) |
| `0x17` | `APP_ADC_READ` | channel(1) | status + mv(2,BE) |
| `0x18` | `APP_PWM_SET` | ch(1) freq(4,BE) duty(2,BE 0..1000) | status |
| `0x19` | `APP_PWM_STOP` | ch(1) | status |
| `0x1A` | `APP_GET_TELEMETRY` | 无 | 遥测帧 `0x9A` |
| `0x1B` | `APP_SET_PARAM` | param_id(1) value(4,BE) | status |
| `0x1C` | `APP_GET_PARAM` | param_id(1) | status + value(4,BE) |
| `0x1D` | `APP_SET_IO` | led(1) rsv(1) rsv(1) | status |

遥测帧 `0x9A` payload（7 字节）：

```
uptime_ms(4,BE) | vbat_mv(2,BE) | flags(1)
flags.bit0 = 任一 PWM 通道激活
```

## 状态码

| 值 | 名称 | 含义 |
|---|---|---|
| `0x00` | `OK` | 成功 |
| `0x01` | `GENERIC` | 通用错误 |
| `0x02` | `BUSY` | 忙 |
| `0x03` | `PARAM` | 参数错误 |
| `0x04` | `CRC` | 校验失败 |
| `0x05` | `NOAPP` | 无可跳转的 App |
| `0x06` | `FLASH` | Flash 操作失败 |
| `0x07` | `MODE` | 引脚模式不匹配该操作 |

## 参数 ID

| 值 | 名称 | 范围 | 默认 |
|---|---|---|---|
| `0x01` | `HEARTBEAT_MS` | 0..60000（0=关） | 1000 |
| `0x02` | `VREF_MV` | 1000..5000 | 3300 |

## GPIO 模式 / 上下拉

```
mode: 0=input 1=output 2=alternate 3=analog
pull: 0=none  1=up     2=down      (仅输入有效)
```

端口：`0=GPIOA 1=GPIOB 2=GPIOC`。PA9/PA10 被控制台 UART 占用，固件会拒绝
对它们的 GPIO 操作。

## 版本

以固件 `firmware/common/protocol.h` 的 `BL_VERSION_*` / `APP_VERSION_*`
为单一真相源。当前：bootloader `0.1.2`，app `0.1.39`。

## 与自定义固件对接

任何固件只要满足以下条件即可被本工具 OTA：

1. 实现 `BL_QUERY / BL_START / BL_DATA / BL_VERIFY / BL_JUMP`。
2. 处理 `APP_OTA_START`：置 `OTA_MAGIC` 到备份寄存器并复位。
3. 链接到 `BL_QUERY` 返回的 `app_base`（默认 `0x08003000`）。
4. 保持 CRC 与帧格式一致。

只实现上述命令的固件即可被 OTA，`fwb` 不依赖其他 App 命令。
