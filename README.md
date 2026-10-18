# 酒馆助手 / HearthstoneBGA 0.2.0

Windows 桌面程序，用于酒馆战棋的基础自动操作、界面识别与对局记录。当前是开发测试版，策略以流程可靠为先。

0.2.0 新增：**自动适配游戏窗口分辨率与比例、自动检测战网安装路径**。支持启动、暂停、继续、停止及本地历史记录。

[下载 Windows 便携版](https://github.com/youges/HearthstoneBGA/releases/tag/v0.2.0) · [查看自动构建](https://github.com/youges/HearthstoneBGA/actions)

首次发布需等待自动构建完成。本机完整测试为 140 项；公共仓库不包含私人实机截图，因此 CI 会跳过相应用例。

## 快速开始

1. 解压 Windows 便携包，保留整个 `HearthstoneBGA` 文件夹。
2. 双击 `HearthstoneBGA.exe`。不需要安装 Python。
3. 打开“运行设置”，检查自动检测出的战网路径；没有找到时点击“自动检测”或“选择…”。
4. 让游戏使用窗口模式，保留“自动适配分辨率与窗口比例”。
5. 新电脑先保留“只观察画面”，确认识别正确，再取消观察模式并开始一局。

F8 暂停，F9 停止。最多完成局数设为 0 时持续运行。程序只能操作可见的前台目标窗口。

## 分辨率适配的范围

程序读取目标显示器的可用空间及 DPI，在需要时将游戏客户区调整为校准比例，并在客户区内换算点击位置。它不修改 Windows 屏幕分辨率或显示缩放。

已通过 720p、1080p、1440p、4K 截图回放和本机 125% DPI 原生窗口测试。**没有完成另一台电脑上的完整对局验收**。语言、游戏布局、画质或版本改变仍可能需要校准。窗口必须可调整；客户区至少需要 960×540 物理像素，建议 1280×720 以上。

## 文档

- [详细使用说明](docs/使用说明.md)：安装、首次运行、设置、校准、记录和常见问题。
- [功能文档](docs/功能文档.md)：功能范围、执行流程、适配原理和限制。
- [0.2.0 更新说明](docs/版本说明-0.2.0.md)：新功能、验证范围和发布状态。
- [开发文档](docs/开发文档.md)：调研、技术栈、架构与历史验收记录。

## 从源码运行

需要 Windows 和 Python 3.11 以上。先创建虚拟环境，再安装项目：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe run.py
.\.venv\Scripts\python.exe -m pytest -q
.\scripts\build.ps1
```

运行数据在 `data`，校准在 `profiles`，图像模板在 `assets`。便携版在 EXE 同级目录保存这些文件。不要将日志、对局数据库和个人截图提交到公共仓库。第三方许可证和 OCR 模型说明见 `THIRD_PARTY_NOTICES`。

