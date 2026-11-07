## Rules
- 遇到没有75%确定性的事要询问用户而不是自己想
- 你要知道一个项目不止为用户设计，而也为Github上访问项目的人
## The Project
- `"E:\Stm32&MC\egcodes"`是样例代码，不要动
- `RFA.md`给AI看；`FFA.md`给第一次见到项目的AI看
- `"E:\Stm32&MC\with_stm32"`是MCmod
- `"E:\Stm32&MC\Stm32Link_Keil"`是Keil项目
## About Push
- Git 代码提交必须带 tag；仅文档更新（README/AGENTS/文档）不打 tag，但仍提交推送。一个发布可含多个 commit，但最后推到 main 的代码 HEAD 必须有同版本 tag，不能“代码已推、tag 没推”。
- Git Tag Version == Minecraft mod version；Mod、STM、Hub 三个仓库用同一个版本号。

## 烧录
- 烧录走 **ST-Link / SWD**，不是 CH340 串口；CH340 只负责运行时协议。
- **不要写死 COM 口、USB 口或接口名**；板子可能换口插。按当前枚举到的 ST-Link 判断，例如 `Get-PnpDevice` 里 `FriendlyName` 含 `STM32 STLink`，或 `VID_0483&PID_3748`；不要用 COM3/COM5 判断。
- 如果同时有多个 ST-Link，先问用户用哪一个，不要猜。只看到 CH340、没有 ST-Link 时不能直接烧；需要 ST-Link/DAPLink 或 BOOT0 串口，先问。
- 在 `Stm32Link_Keil` 下烧录：
  ```bat
  "D:\Keil\UV4\UV4.exe" -f main.uvprojx -j0 -o flash.log
  ```
  `-b` 只编译；`-f` 下载并运行。换 USB 口不影响命令，重新枚举即可；换调试器则先确认 Keil 的 Debug 配置。
- 成功标志：`Erase Done.Programming Done.Verify OK.Application running ...`。失败先看 `flash.log`，检查 SWD 线、目标供电、ST-Link 驱动；不要改用 COM 口乱试。
- 烧录会复位板子，游戏串口会断一次；烧完重启游戏或等它重连。

## Tag / 发布
- 必要性：tag 是发布点和复现依据，Release 资产必须对应该 tag；main 可以领先，但发布不能没有 tag。
- 版本：`x.y.z`（不带 v）；修 bug 升 patch，新功能升 minor，破坏线协议/存档升 major。
- 更新方式：改 `with_stm32/gradle.properties` 的 `version` → 构建/测试 → 提交 → Mod/STM/Hub 各打 annotated tag `x.y.z` → 推 main 和 tags → Hub Release 附 `with_stm32.jar`/`main.hex`。
- Hub 的 tag 必须在 submodule 指针提交之后；Release 只从 tag 出，资产必须等于该 tag 的构建。
- 已发布 tag 不移动、不删除、不复用；发布有问题就发新 patch。dirty tree 不打 tag。