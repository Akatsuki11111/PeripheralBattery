# PeripheralBattery

Windows 外设电量托盘工具，Python / PySide6。当前双版本：**v2.6.0 正式版**、**v2.6.1-experimental.1 实验版**。

## 使用与更新

从 [GitHub Releases](https://github.com/Akatsuki11111/PeripheralBattery/releases) 下载对应EXE运行。新版软件内的检查与下载仅使用 [VersionHub服务器](http://updates.example.invalid:8089/)，不再请求GitHub更新。GitHub继续保存源码、标签及发布包。旧版更新地址已编译在旧程序中，首次迁移需要手动运行新版，或通过旧版原有GitHub通道获取本次迁移版。

正式版不包含电量适配实验、长期观察和实验映射运行模块；实验版保留。两版支持正式/实验更新通道、下载进度、取消、校验、重启替换和失败回滚。更新器不自动降级。现有设置与开机自启保留，新安装正式版默认仅正式通道；已有通道偏好不被覆盖。

服务器当前是HTTP。客户端内嵌发布RSA公钥，先校验绑定版本/通道/文件的签名，再核对EXE的SHA256及大小；拒绝重定向、无签名和被篡改的发布。管理账号、密码、token和私钥均不在程序或仓库中。签名保护更新完整性，不会加密HTTP管理登录；详见 [RELEASE_SERVER.md](RELEASE_SERVER.md)。

## M5 Lite 与实验方向

已适配瓦尔基里 **VK M5 Lite**：共享3151:5045接收器先执行官方RY F7状态与8F型号查询，只有型号3090匹配后才采用电量/品牌。实机拔线后确认无线在线、100%电量。休眠或切换USB后不把接收器保留的旧百分比当作实时读数；换配不同型号时清除旧缓存并分开历史片段。

官方USB路径直接初始化100%，不是实测电量，因此本程序不采用这个值，也不虚构未验证的充电标志。要读取M5 Lite电量，请保留2.4G接收器、拔掉USB数据线并唤醒鼠标。USB接入仍作为含电池设备识别。

实验版先识别可用状态协议：已有可靠电量就直接结束，不再要求1–2小时猜测。未知设备首次跳过空白/填充Feature包尝试其他已声明报告；锁定采样通道后不自动换通道。全部无有效数据则明确停止。长期观察仍只是相关性线索，不保证未知型号可适配。

## 其他功能

设备列表显示类型、品牌、电量、充电/连接状态及详情；休眠设备显示上次有效电量及原采样时间，刷新不会改写该时间。支持5/15/30/60秒刷新、开机自启、有线无电池标记、24小时历史和谨慎的续航估算。

目录包含77个品牌、859个明确ID，并支持通用HID键鼠和手柄识别。品牌识别不代表该品牌全部电量协议已支持。手柄支持XInput四档、Windows电池报告及部分Sony/Nintendo/八位堂被动电池字段；详见 [GAMEPADS.md](GAMEPADS.md)。北通KP50B/墨将彩虹2当前模式的专用精确电量仍待验证。

## 体积取舍

从v2.4.1约48.75MB缩至约28.6MB，减少约41%。其中压缩后的Python、Qt、绑定、SSL和程序归档约22.3MB。保留现有Python/PySide6独立运行及界面功能，10MB目标很难达到。本次没有继续强行裁剪。小启动器可小于10MB，但额外运行库仍需下载/安装；真正继续缩小需要重做原生GUI甚至重写实现。详见发布说明的取舍表。

## 源码与构建

Windows 10/11、Python 3.14，建议独立虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
python -m unittest discover -s tests
.\build.ps1 -Channel stable
.\build.ps1 -Channel experimental
```

正式构建会排除全部实验模块。网络、HID与实验查询运行在可终止后台进程，不读取键鼠按键或移动报告。手柄电池解析仅在内存中提取字段，不记录按键/摇杆。218项回归测试通过，覆盖签名篡改、下载校验、安装回滚、M5状态/型号、缓存与实验流程；两版独立程序也已核对。未逐一实物验证全部目录硬件。

## 版本与发布管理

使用SemVer标签，stable分支对应正式版，main对应实验开发。每版同时发布到GitHub和VersionHub，旧标签保留。服务器现有100MiB配额足够本次三份EXE；后续需扩容或明确清理策略，工具不自动删除旧版本。服务器签名发布工具位于tools/，不包含凭据；私钥仅在本机当前用户DPAPI保护的发布目录。

程序尚无商业EXE代码签名，更新内容的发布签名与Windows代码签名是两种不同机制。第三方组件与品牌素材许可见THIRD_PARTY_NOTICES.md、licenses/、battery_backends/LICENSE及assets/brands/SOURCES.json。公开仓库不改变各品牌商标权；本项目原创部分尚未指定统一开源许可证。


本次真实服务器升级验证通过：本机v2.5.1-experimental.1从VersionHub下载v2.6.1-experimental.1，取消后重试，通过签名与SHA256校验并替换重启；设置、自启动保持。服务器正式版实际代码2060001、下载ID6；实验版2060101、下载ID7。
