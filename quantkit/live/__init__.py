"""币安实盘日度调仓引擎（基于 quanton 改造）。

与 quanton 的唯一大区别：数据获取走 exchange-gateway 数据服务（只用 1d），
不再连币安 WebSocket / REST 行情。下单仍走币安 Futures REST。

组件：
* :mod:`quantkit.live.config`      配置（.env + strategy.json 注入）
* :mod:`quantkit.live.factor`      跑多 plugin 组合 -> 最新截面目标权重
* :mod:`quantkit.live.executor`    币安 Futures 下单执行器（复用 quanton 逻辑）
* :mod:`quantkit.live.rebalancer`  日度调仓主流程
* :mod:`quantkit.live.main`        入口 + APScheduler 日度触发
"""
