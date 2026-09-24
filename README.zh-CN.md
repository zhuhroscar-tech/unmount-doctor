[![English](https://img.shields.io/badge/English-555555?style=flat)](README.md) [![简体中文](https://img.shields.io/badge/简体中文-555555?style=flat)](README.zh-CN.md)

# unmount-doctor

将 Linux 的 `umount: target is busy` 错误整理为按进程列出的报告。`unmount-doctor` 解读 `fuser`/`lsof` 输出，显示 PID、可获取的用户名、命令，以及路径被占用的原因：打开的文件、当前工作目录、可执行文件、内存映射等。

**默认只读**。发送进程信号或 lazy unmount 都需要显式参数，并由用户确认。

## 安装与检查

需要 Linux 和 Python 3.8+。请安装 `fuser`（通常来自 `psmisc`）；可选的 `lsof` 能补充细节。Debian/Ubuntu 示例：

```bash
sudo apt-get install psmisc lsof
git clone https://github.com/zhuhroscar-tech/unmount-doctor.git
cd unmount-doctor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
unmount-doctor /mnt/usb
```

目标可以是挂载点、目录或设备路径。全部参数见 `unmount-doctor --help`。也可从 [Releases](https://github.com/zhuhroscar-tech/unmount-doctor/releases) 下载独立 `.pyz`，执行前请核对对应版本的校验和。发布历史见 [CHANGELOG.md](CHANGELOG.md)。

## 谨慎处理占用

优先正常关闭报告中的应用。如果 shell 的工作目录位于挂载点中，先 `cd` 到其他位置。重新检查后，再尝试正常卸载。

只有理解后果时，才使用以下会改变系统状态的可选命令：

```bash
unmount-doctor /mnt/usb --kill 4213       # SIGTERM；需要确认
unmount-doctor /mnt/usb --force-kill 4213 # SIGKILL；可能丢失未保存的数据
unmount-doctor /mnt/usb --lazy-unmount   # 确认后执行 umount -l
```

请将示例 PID 替换为当前报告中的进程；工具会拒绝未列出的 PID。`--yes` 会跳过确认，不建议在交互排障时使用。Lazy unmount 立即从命名空间中分离文件系统，但不表示所有引用已关闭，也不表示可以安全拔盘。

## 限制与权限

空报告不等于文件系统空闲。普通用户可能看不到其他用户的进程，底层命令失败也会导致信息不完整。若仍无法卸载，请检查嵌套挂载、swap 和 loop 设备。`lsof +D` 递归检查目录可能比较耗时。

CLI 仅面向 Linux，无遥测和网络调用，使用当前用户的权限。仅诊断时，即使发现占用或工具错误也可能返回 `0`；请阅读报告，不要把退出码当作健康状态。

## 预览与开发

[输出截图](docs/images/example-output.png) · [演示视频](docs/demo.mp4)

```bash
python -m unittest discover -s tests -v
```

[实现](src/unmount_doctor/cli.py) · [CI](.github/workflows/ci.yml) · [MIT 许可证](LICENSE)
