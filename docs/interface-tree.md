# Python 接口树

`ChatTodo` 的 CLI 应保持薄入口；实质能力应放在可 import 的 Python 函数、类或 service 层里。

## 包入口

```python
from chattodo import __version__
```

## 待补接口

```text
chattodo
├── cli.py          # Click 入口，只做参数解析和输出
└── <service>.py    # 放包的核心可调用能力
```

## 更新清单

- 每个实质 CLI 命令都要能映射到 importable API。
- 文档里的函数签名应和代码一致。
- 对外输出默认不要泄漏 token、cookie、内部 URL 或人员信息。
