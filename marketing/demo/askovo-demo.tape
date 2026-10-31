# Askovo 首屏 demo GIF 录制脚本（vhs 格式）
#
# 用法（推荐，产物直接可嵌 README）：
#   brew install vhs && vhs marketing/demo/askovo-demo.tape
#   产物落在本文件 Output 指定的路径；录制前确保 askovo 已 pipx/pip 安装。
#   录完把 GIF 拷到 assets/demo/askovo-demo.gif，再放开 README 中对应的注释位。
#
# 备选（无 vhs）：asciinema rec + agg
#   asciinema rec -c bash marketing/demo/demo.cast   # 手动按本文件顺序执行命令
#   agg marketing/demo/demo.cast assets/demo/askovo-demo.gif --font-size 16
#
# 原则：脚本里只放真实命令与真实输出，不做任何摆拍剪辑。

Output marketing/demo/askovo-demo.gif

Set FontSize 15
Set Width 1100
Set Height 560
Set Shell bash
Set Theme "Dracula"
Set TypingSpeed 40ms

# 1) 安装（PyPI 发布后有效；未发布时改为 pipx install git+https://github.com/roy-tong/askovo.git）
Type@40ms "pip install askovo"
Sleep 500ms
Enter
Sleep 3s

# 2) 一句话需求 → 自动路由与推理链骨架（只路由不写文件）
Type@40ms "askovo do \"家用摄像头夜间告警误报，想验证样机\" --dry-run"
Sleep 500ms
Enter
Sleep 4s

# 3) 离线合成样例：审计超证结论
Type@40ms "askovo demo"
Sleep 500ms
Enter
Sleep 6s

# 4) 收尾停在关键结果上：status: pass / supported: 1 / overclaims: 0
Sleep 4s
