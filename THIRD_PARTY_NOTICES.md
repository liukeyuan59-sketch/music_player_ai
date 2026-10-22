# 第三方组件

随听 0.1 使用如下第三方组件；各组件的许可证和版权声明保留在 `licenses` 目录与运行包中。
这份列表不改变任何组件的许可条款。

| 组件 | 用途 | 许可 |
|---|---|---|
| Python 3.12 | 应用运行环境 | Python Software Foundation License |
| Tcl/Tk 8.6 | 桌面窗口 | Tcl/Tk license |
| pygame 2.5.2 及随附 SDL 组件 | 音频播放 | LGPL 2.1 / 各依赖各自许可证 |
| mutagen 1.48.1 | 只读解析音乐元信息 | GPL 2.0 or later |
| PyInstaller bootloader | 打包启动 | GPL 2.0 or later with bootloader exception |

随听应用源码在同包 `source` 文件夹提供，以 GPL 2.0 or later 发布，详见 GPL-2.0.txt。
本版本没有修改第三方组件。对应源码地址：

- Python：https://www.python.org/downloads/source/
- Tcl/Tk：https://www.tcl.tk/software/tcltk/
- pygame：https://github.com/pygame/pygame/tree/2.5.2
- SDL：https://github.com/libsdl-org/SDL
- SDL_mixer：https://github.com/libsdl-org/SDL_mixer
- mutagen：https://github.com/quodlibet/mutagen/tree/release-1.48.1
- PyInstaller：https://github.com/pyinstaller/pyinstaller/tree/v6.22.3

运行包为目录形式，可替换其中的第三方动态库；请保持版本兼容。
