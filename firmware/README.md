# 固件源码（自动识别 64/128 KB Flash）

本目录是 `release/bootloader-v0.1.3.bin` 与 `release/app-v0.1.40.bin`
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
# 产物：release/app-v0.1.40.bin / .hex（版本取自 protocol.h）
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

### Bootloader v0.1.3

> ⚠️ **v0.1.2 有退化，请勿使用**：那一版让 `BL_ABORT` 无条件清标志。升级中途
> 取消时 App 区已被 `BL_START` 擦掉，标志一清，`main()` 就落到
> `bl_app_valid()`；它只看前两个向量，而第一个 512 B 数据块恰好包含这两个
> 向量，于是被判定为"有效"，跳进一个代码已被擦除的镜像 → HardFault →
> **只能 SWD 救**。这是上板实测到的，不是推断。

v0.1.3 的规则按标志语义区分：

| 场景 | 标志 | `BL_ABORT` 行为 |
|---|---|---|
| App 请求 DFU（`APP_OTA_START`） | `OTA_MAGIC` | 清标志 → 复位 → **回原 App** |
| 升级中途（`BL_START` 之后） | `OTA_UPDATE_MAGIC` | **保留**标志 → 复位 → 留在 DFU |

升级中途 App 区已经被擦除，没有"原 App"可回；留在 DFU 才是正确且可恢复的
状态（再发一次 OTA 即可）。主机在镜像超限时发的 `BL_ABORT` 发生在 `BL_START`
之前，走第一行，所以"拒绝过大镜像后自动回原 App"仍然成立。

另外 `bl_app_valid()` 增加一条检查：复位向量指向的地址必须是真实代码
（半字不是 `0xFFFF`）。这样即使 `BKP` 标志因掉电丢失，也不会跳进半截镜像。

### App v0.1.40

只把版本常量同步到 Bootloader v0.1.3（App 模式下 `fwb info` 报告的 BL 版本
来自 App 内编译的常量，不同步会显示旧版本）。功能与 v0.1.39 相同，见
[app/README.md](app/README.md#本版修复v0139)。

## 验证状态

| 项 | 结果 |
|---|---|
| 构建 | 干净 clone 重编与 `release/` 逐字节一致；CI 通过 |
| 128 KB 板（ST-Link V2 + BLE 透传） | `bootloader v0.1.3, app v0.1.40`；`BL_QUERY` 报 117,760 B（115 KB） |
| OTA | 4788 B 镜像 10 个 512 B 分块，erase→write→verify→jump 全部通过 |
| 遥测 | 连看 14 帧 `vbat` 稳定 565–596 mV，无 `ADC invalid`（ADC 交替超时的修复生效） |
| 参数 | `param set 1 70000` 被拒；`set 1 3000` 后复位仍为 3000；config 页 v2 布局正确 |
| 中途取消 | App 请求 DFU 后取消 → 回 App；`BL_START` 后取消 → 留在 DFU，再 OTA 可恢复 |
| 防砖 | 全片擦除后只写 512 B App 前缀 → 停在 DFU，未跳转 |
| 64 KB 真板 | **未验证**，只有强制 64 KB 构建的链接期检查 |
