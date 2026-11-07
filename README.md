# WithSTM32 — Minecraft ⇄ STM32 串口互联

一个 Fabric 1.21.8 模组 + STM32C8T6 固件的组合项目：MC 里的方块和真实世界通过一条 CH340 串口线实时互通。

> **代码仓库（本仓库以 submodule 固定版本）**
> - Minecraft Mod：<https://github.com/qwaszxopklnmso/Stm32Link-Mod> → `with_stm32/`
>   - 中文 README：<https://github.com/qwaszxopklnmso/Stm32Link-Mod/blob/main/README.zh-CN.md>
> - STM32 固件（Keil）：<https://github.com/qwaszxopklnmso/Stm32Link-STM> → `Stm32Link_Keil/`
>   - 中文 README：<https://github.com/qwaszxopklnmso/Stm32Link-STM/blob/main/README.zh-CN.md>
> - 本仓库：项目入口 / 文档 / 两个 submodule
>
> 克隆时请带子模块：
> ```bash
> git clone --recurse-submodules https://github.com/qwaszxopklnmso/Stm32Link.git
> ```
> 已克隆但没带子模块时：`git submodule update --init --recursive`。

> **接线 / 烧录 / 串口配置看 [STM32_Set.md](STM32_Set.md)**，这里只讲玩法。

## 功能一览

### 联控灯（红 / 绿 / 蓝）
类似红石灯的方块，但是三色，且与 STM32 板上的 LED1~LED3 **实时双向同步**：
- 板上 B1 → 只切红色联控灯；B2/B3 是接收器输入，不再切灯
- 右键不再切换灯（该功能已删除；控制入口是红石，B1 只本地切红灯）
- 红石行为与原版红石灯**完全一致**（点亮瞬时、熄灭延迟 4 刻、放置时自动检测旁边信号、活塞推动等边界同原版）
- 放置即同步：旁边有信号或板上此路 LED 本来就亮 → 放下就是亮的；**拆掉**亮着的灯 → 板上 LED 跟着灭
- 红石点亮的灯不会被板子"同步熄灭"（红石一直供着就一直亮）
- 进世界 / 串口重连时，**以世界里的灯为准**把状态推回板子（B1 红灯按钮仍可本地切；绿灯/蓝灯由红石或串口控制）

### 遥测接收器（STM32 → MC，三种）
三种接收器各用一个板上按键，互不抢输入：

- **电平接收器**：输出跟随 **B4**，持续 **15 级红石**；按一下开、再按一下关。适合门、灯、活塞。
- **脉冲接收器**：每按一次 **B2** 发一个短脉冲（2 刻），适合边沿触发、计数器、脉冲门。
- **触发接收器**：每按一次 **B3** 翻转输出锁存，适合做开关、双稳态、远程电灯。
- **B1** 只切红色联控灯；**B2/B3 不再切灯**，避免一个按键既切灯又发接收器事件。绿灯/蓝灯由红石或串口控制。

进世界/重连时第一次 B4 只做状态同步，不会误触发脉冲或翻转。三种接收器配方不同：
电平用铁+红石，脉冲加中继器，触发加拉杆。

### 遥测发射器（MC → STM32）
给这个方块红石信号 → 板上 PA4 的 T-LED 点亮（没接 LED 也能听到**蜂鸣器短响一声**确认）。
红石一断就熄灭。可以用拉杆、压力板、侦测器等任何红石源驱动。
多个发射器共用一路 T：**任意一个**有信号板上就亮；进世界/重连后会自动把当前状态同步回板子。

### 曲哨
手持**右键**（对着空气或方块都行）：播放 **8bit 琵琶曲**（四声部）——用 `tools/chiptune_to_mid.py` 把你的 8bit 琵琶曲 m4s
逐层剥离转谱出来的四声部曲谱（中间产物 `tools/pipa_8bit.mid` 可拖进任何 MIDI 播放器人工验收）。
双端同步：游戏内四种音符盒音色 + 4 个蜂鸣器（板子没连也不影响游戏内声音）。5 秒冷却。
玩家死亡时蜂鸣器还会奏一段"安慰旋律"（彩蛋）。

> 板子上只有这一首歌，所有播放入口（`M`/`M1`/`M2`/`tune`/`tune2`/曲哨）都是它。
> Summer Express 转谱版因"听不出原曲"已按你的要求移除。

### PCM 原声片段（`/stm32link audio`）
蜂鸣器除了合成音符还能**直接播放录音**：固件里存了 **8.2 秒 4-bit IMA ADPCM**（8kHz 采样、
1.4 倍速、约 32KB），且经过**中置抵消消人声**（立体声 L−R，人声通常在正中）。通过 PWM 占空比回放，
音色鼓点全在。想换片段/换歌/调速度/调长度：
`D:\Python3.12.0\python.exe tools\pcm_convert.py <音频文件> [输出秒数] [倍速]`
（当前 8.2s×1.4×=32KB，flash 余量约 14KB；不加速的话上限约 11.5 秒），
重新编译烧录即可。`tools/pcm_preview.wav` 是消人声版试听，`pcm_preview_novocal_off.wav` 是未消人声的 A/B 对照。

> ⚠ 这段 PCM 只有**电磁式/动圈**蜂鸣器能放。压电片（如 MH-FMD）是窄带谐振器件，只能发接近谐振点的单音，
> 播不了 PCM/录音——用 Audacity 导出的音频也一样，不是固件坏了。

## 指令

| 指令 | 说明 |
|---|---|
| `/stm32link status` | 连接状态、心跳、LED/按键镜像 |
| `/stm32link beep` | 蜂鸣器测试音（验串口方向最方便） |
| `/stm32link audio` | 蜂鸣器播放 5 秒 PCM 原声片段（真正录音，非合成） |
| `/stm32link tune` / `tune2` | 播放 8bit 琵琶曲（四声部，同曲哨） |
| `/stm32link reconnect` | 重连串口（OP） |
| `/stm32link port COM3` | 手动指定串口（OP），留空 `""` 恢复自动扫描 |

## 安装

1. 固件烧进板子（`Stm32Link_Keil\`，见 STM32_Set.md）
2. 把 `with_stm32\build\libs\with_stm32-1.0.0.jar` 放进
   `D:\MC\.minecraft\versions\1.21.8WithSTM\mods\`（已放好）
3. 启动 `1.21.8WithSTM` 实例，进世界后聊天栏出现 `STM32 已连接` 即可
   - 串口自动扫描 CH340；识别失败再手动 `/stm32link port COMx`
   - 配置文件：`versions\1.21.8WithSTM\config\with_stm32.json`

获取模组物品：创造模式物品栏 **「STM32 互联」** 标签页，或
`/give @s with_stm32:link_lamp_red` 等。

## 文件地图

```
E:\Stm32&MC\
├── FFA.md                  需求单
├── README.md               本文件（玩法）
├── STM32_Set.md            接线/烧录教程
├── .gitignore
├── Stm32Link_Keil\         STM32 固件（Keil 工程，StdPeriph，江协风格驱动）
│   ├── User\main.c             主循环（初始化 + 心跳）
│   ├── User\Protocol.c         行协议解析（L/T/N/W/Y/P/S/M 命令）
│   ├── Hardware\Serial.c       115200 + 中断环形缓冲
│   ├── Hardware\Led.c          LED1-3 (PA1-3) + T-LED (PA4)
│   ├── Hardware\Buzz.c         4 声部蜂鸣器 + PCM 播放（V1-V3 高触发、V4 低触发，可按声部切极性）
│   ├── Hardware\Key.c          4 按键消抖轮询（PB12~15）
│   ├── Hardware\Song.c         离线四声部播放器
│   └── Heads\Tick.c            TIM3 毫秒时基
├── with_stm32\             Fabric 1.21.8 模组源码（Mojmap）
│   └── src\main\java\qw\with_stm32\
│       ├── SerialLink.java       串口线程/自动扫描CH340/断线重连
│       ├── LinkState.java        协议状态镜像
│       ├── LinkRegistry.java     方块/物品注册 + 状态同步进世界
│       ├── LinkSavedData.java    方块位置持久化（Codec/SavedDataType）
│       ├── MelodyPlayer.java     服务端tick双端同步播放器
│       ├── block\                联控灯/接收器/发射器
│       └── item\TuneWhistleItem  曲哨
├── tools\                  音频扒带、材质生成脚本（D:\Python3.12.0 运行）
└── 琵琶曲dj.m4s            原曲（已加进 .gitignore，不入库）
```

## 串口协议

115200-8N1，行协议（`\n` 结尾），完整表见 [STM32_Set.md](STM32_Set.md) 第 6 节。
模组端在 `SerialLink.java`，固件端在 `User\Protocol.c` 的 `Line_Parse`，两端对称可改。

## 常见问题

- **连不上 / 秒断**：TX/RX 交叉了吗（PA9→RXD）？共地了吗？设备管理器 COM 号对吗？
- **蜂鸣器没声**：固件默认 **V1-V3 高电平触发（NPN 电磁）、V4 低电平触发（压电）**；V1-V3 拉高才响，V4 拉低才响。先看接法（STM32_Set.md 2.4）；无源压电/电磁式都必须方波驱动；电磁式要用三极管；若 V1-V3 改用 PNP/低触发，发 `Y<1-4>:1`；电磁式低音偏小是正常的
- **压电测试**：压电接 V4(PA5) 低触发，串口发 `N4:4000,120` 或触发遥测发射器 T，会 4kHz 短响；响说明接线对了。V1~V3 接压电只能听个响，旋律会缺低频、发闷，不推荐；旋律/PCM 用电磁式
- **灯不跟手**：`/stm32link status` 看心跳是否"正常"；心跳正常但不同步说明 LED 接线检查 PA1~PA3
- **旋律不好听**：这是扒带的，调 `tools/melody_extract2.py` 参数重新生成，或者直接改 `Song.c`/`Stm32Melody.java` 里的音符表（`{频率Hz, 毫秒}`，0 频率 = 休止）

## ...
- `FFA.md`其实是这个项目第一次给AI(`glm-5.3-flash`)发的信息
### AI 使用

| Model | Version | Agent |
| :--- | :--- | :--- |
| `deepseek-flash` | 4.1 flash | `Deepseek harness` |
| `glm-5.3-flash` | 5.3 flash | `Zcode` |

## License

Hub docs, scripts and original code are MIT; see [LICENSE](LICENSE). The
submodules have their own licenses: the mod is MIT, and the STM32 firmware is
MIT with ST third-party notices.