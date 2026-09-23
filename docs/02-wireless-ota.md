# 02 - 无线 OTA 升级

## 一条命令

```powershell
fwb ota app.bin --ble AA:BB:CC:DD:EE:FF
```

`.bin` 和 `.hex` 都支持；`.hex` 会自动提取 App 区的记录。

## 输出解读

```
image: app.bin (4604 bytes)
[probe ]   1%                          ← 探测当前是否在 Bootloader
[probe ]   3% triggering OTA start ... ← 若在 App，令其置标志并复位
[erase ]   2% erasing 51 KB app region ← 擦除 App 区
[write ]  ...  4604/4604 bytes         ← 分块写入 512B
[verify]  92% CRC32 0xXXXXXXXX         ← CRC 校验
[jump  ]  96%                          ← 跳转新 App
[done  ] 100% App now (0, 1, 25)       ← 重新 PING 确认
OTA complete: app v0.1.25
```

看到 `OTA complete` 即成功。

## 背后发生了什么

```
主机                                  设备
────                                  ────
BL_QUERY ───────────────────────────▶ App 不响应（不认 Bootloader 命令）
APP_OTA_START(total_len) ───────────▶ App: 备份寄存器 DR1 = 0x4F54，复位
                                      Bootloader 启动，读到标志 → DFU 模式
BL_QUERY（重试） ───────────────────▶ 返回版本 / app_base / 分区大小
BL_START(total_len) ────────────────▶ 置 in-progress 标志 + 擦除 App 区
BL_DATA(offset, chunk) × N ─────────▶ 逐块写入（offset 必须偶数连续）
BL_VERIFY(crc32) ───────────────────▶ 传输流 CRC == 回读 CRC == 主机 CRC？
BL_JUMP ────────────────────────────▶ 清标志 → 校验向量表 → 跳转
PING / GET_VERSION ─────────────────▶ 新 App 应答
```

## 分区布局

```
0x08000000 ┌──────────────────┐
           │ Bootloader 12KB  │  常驻，OTA 不动它
0x08003000 ├──────────────────┤
           │ App 51KB         │  OTA 目标
0x0800FC00 ├──────────────────┤
           │ Config 1KB       │  参数持久化
0x08010000 └──────────────────┘
```

## 断电不变砖的原理

1. **擦除前置标志**：`BL_START` 先写标志再擦。若擦除中断电，重启后
   Bootloader 看到标志直接进 DFU，不会跳转到半成品。
2. **验证后跳转**：`BL_JUMP` 只在 CRC 校验通过后执行；未验证时拒绝。
3. **向量表兜底**：跳转前检查 App 首 8 字节（SP 在 SRAM 范围、Reset 为
   Thumb 且落在 App 分区）。
4. **三重 CRC**：传输流、Flash 回读、主机计算三者必须一致。

因此任意时刻断电，最坏情况是设备停在 DFU 模式，重新运行 `fwb ota` 即可。

## 传输方式对比

| 方式 | 参数 | 说明 |
|---|---|---|
| BLE 透传 | `--ble ADDR` | 无线，最常用 |
| USB-TTL | `--port COM5` | 有线，最稳定 |
| 经典蓝牙 SPP | `--port COM5` | 配对后表现为串口，无线 |

三种方式协议完全相同，`fwb` 命令可以互换。

## 镜像长度与补偶

Flash 按 16 位写入，镜像长度会被自动补 `0xFF` 到偶数。主机和设备对
补齐后的数据计算同一个 CRC32，所以校验语义不受影响。

## 升级到自己的固件

任何链接到 `0x08003000` 的应用都可以通过这套 OTA 烧入，无需修改工具。
自定义 App 只需：

1. 使用匹配的链接脚本（起始地址 `0x08003000`）。
2. 正确处理向量表重定位（见工程的启动文件）。
3. 若想从 App 运行状态直接 OTA，保留对 `APP_OTA_START` 的处理逻辑
   （置备份寄存器标志 + 复位）。

不需要支持其他命令的固件同样可以 OTA —— 工具只依赖 `BL_*` 命令和
`APP_OTA_START`。
