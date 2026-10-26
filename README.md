# traceview

**把一次模型调用的链路摊平成时间线。**

`traceview` —— 把调用事件按阶段排成时间线，标出最慢的环节与可能的重试。

- 零依赖，Python 3.10+ 标准库即可运行
- 单文件，`traceview.py` 拷走就能用
- 不联网、不写文件

<!-- ipos:install -->
## 安装

零依赖，Python 3.10+ 即可：

```bash
pip install ewerle-traceview
```

装完直接用命令名调用：

```bash
traceview --help
```

也可以不用安装，直接把 `traceview.py` 拷走用——它只依赖标准库。

## 为什么需要它

追踪工具多给瀑布图；traceview 明确标出「等待」与「计算」的差别，并从时间线里识别疑似重试。

它遵守下面几条自己定的规矩：

1. **等待和计算要分开**。网络在等和模型在算，排查方式完全不同。
2. **重试要认出来**。间隔大得像重试的位置必须标出来。
3. **不接任何监控后端**。吃一份事件日志就行。

## 用法

```bash
python traceview.py --events trace.json
python traceview.py --events trace.json --json
```

加 `--json` 可以拿到机器可读的结果，便于接到流水线里。

## 已知局限

- 只读已记录的事件，不做采集。
- 时间线是按事件自带时间戳排的，不做时钟校正。
- 不判断因果，只呈现先后与重叠。

## 跑测试

```bash
python test_traceview.py
```

测试用独立的断言与临时数据，不污染工作目录。

## 来源与参考

- Python 标准库文档：<https://docs.python.org/3/>
- GitHub 仓库：<https://github.com/ewerle/traceview>

---

## 关于作者

ewerle 做模型调用链路观测相关的问题。这个工具先替你回答一个具体问题，再谈别的。

- 个人主页：<https://ewerle.github.io>
- 仓库：<https://github.com/ewerle/traceview>

## 许可

MIT，见 [LICENSE](LICENSE)。
