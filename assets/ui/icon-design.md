# 酒馆助手应用图标

使用内置 image_gen 工具生成；没有使用 API/CLI 后备方式。金色酒杯与两张卡牌构成主体，深蓝和青绿色与程序界面呼应。图案为本项目生成，不使用现有游戏商标。

- `app-icon.png`：透明背景原图。
- `app-icon.ico`：从原图转换的 Windows 多尺寸图标，用于 EXE、窗口和任务栏。

重新转换图标：`python scripts/build_icon.py`。只进行格式转换和尺寸缩放，保留透明通道。

最终提示词：

```
Use case: logo-brand. Create one polished original Windows desktop application icon for a Chinese tavern card-game helper named 酒馆助手. No text or letters anywhere. Square 1024x1024 composition. A bold warm golden tavern tankard with a clean ivory foam silhouette sits in front of two very simple overlapping playing-card backs, forming one compact cohesive badge. Deep ink navy rounded-square base with tasteful teal accents and a restrained brass rim. Icon fills about 85% of canvas with even comfortable margins, straight front view, symmetric balanced composition, very large readable shapes. Premium stylized game UI illustration, crisp edges, subtle dimensional shading, warm amber highlights, restrained detail; must remain recognizable at 16x16, 32x32 and 48x48. No scenery, characters, small decorative objects, lettering, watermark, or existing game logos. Outside the rounded-square base, the four corner regions should be transparent; preserve the base itself as opaque. Deliver a single finished icon, no mockup and no contact sheet.
```
