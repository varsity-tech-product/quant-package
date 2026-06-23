"""quantkit —— 截面因子组合、回测提交、币安实盘部署工具包。

三大能力：
  * :mod:`quantkit.plugins`  加载因子 plugin，inspect 出 build_signal 需要的数据字段
  * :mod:`quantkit.compose`  把多个 plugin 信号合成为 composite，再生成截面权重
  * :mod:`quantkit.attribution`  对策略预测值做风格归因（多空桶 × 基础风格暴露）
  * :mod:`quantkit.backtest` 调策略回测服务（提交 + 轮询取结果）
  * :mod:`quantkit.data`     从 exchange-gateway 数据服务取 1d 面板
  * :mod:`quantkit.live`     币安实盘日度调仓引擎（基于 quanton 改造）
"""

__version__ = "0.1.0"
