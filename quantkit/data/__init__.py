"""数据层：从 exchange-gateway 数据服务取 1d 行情，拼成 build_signal 要的面板。

* :mod:`quantkit.data.gateway_client` 封装官方 ref client（grpcurl）取历史 bars/funding
* :mod:`quantkit.data.panels`         把 raw bars 切成各 plugin 需要的 [date x symbol] 面板
"""
