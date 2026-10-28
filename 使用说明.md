# PeripheralBattery

Windows 外设电量托盘工具，使用 Python / PySide6。

## 使用

在 [Releases](https://github.com/Akatsuki11111/PeripheralBattery/releases) 下载带版本号的 EXE。程序在通知区域显示有效设备电量，点击打开设备列表。首次运行 Windows 可能提示未签名应用；程序尚无商业代码签名。

支持按型号识别、部分设备电量与充电状态、5/15/30/60 秒刷新、有线无电池标记和设备管理。品牌识别不等于该品牌所有型号已支持电量。详情与可用选项以各版本代码为准。

## 实验功能

v2.2.0 起提供分步协议检查；v2.3.0 起提供 1/2 小时观察。实验只使用已知状态查询或描述符声明的 Feature GET，不读取键鼠 Input 数据，不扫描私有配置命令。未知型号不一定提供电量报告，长时间观察不保证完成适配。实验候选需手动确认，显示带 ? 的推测读数，不参与可信最低电量与提醒。未完成未知硬件的两小时实物验证。

v2.3.1 修正通用接收器型号展示，增加瓦尔基里官方目录标识和分项 HID 描述诊断。共享 OEM 标识不强制归为某品牌；具体未适配硬件仍需要 VID/PID 和诊断报告。

## 从源码运行与构建

Windows 10/11，Python 3.14。建议使用独立虚拟环境。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
python -m unittest discover -s tests
```

运行 `build.ps1` 构建对应版本的 EXE。后台查询在可终止的独立进程中运行。实验和缓存数据保存在当前用户的 `.peripheral-battery` 目录，只在本机使用；请先审阅诊断内容再分享。

## 版本管理

使用 `v主版本.次版本.修订号` 标签；实验版 Release 标为 Pre-release。v2.1.2、v2.2.0、v2.3.0 的标签由原交付源码归档重建，提交时间是导入时间，不表示原始开发提交历史。此仓库不含本机运行日志、设备历史、账户凭据或原始用户诊断。

## 第三方许可

第三方组件、协议后端及图标素材遵守各自许可，详见 THIRD_PARTY_NOTICES.md、licenses/、battery_backends/LICENSE 及 assets/brands/SOURCES.json。公开仓库不改变第三方版权及商标权；本项目原创部分暂未指定统一开源许可证。
