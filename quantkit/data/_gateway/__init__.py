"""内置的 exchange-gateway 取数依赖（参考客户端 + proto）。

本子包把 exchange-gateway 仓库里的官方参考客户端
``examples/marketdata-fetch-client/exchange_gateway_ref_client.py`` 和它需要的
proto（``proto/common``、``proto/marketdata``、``proto/aggtrade_kline``）内置进来，
这样本包不再依赖外部 ``EXCHANGE_GATEWAY_DIR`` 仓库路径，可直接发给外部用户。

``ref_client`` 为**近乎原样 vendor**（便于与上游对齐）：其 ``find_proto_root()``
会从本目录向上找 ``proto/marketdata/v1/marketdata.proto``，因此 ``REPO_ROOT``
自动定位到本目录下的内置 ``proto/``，无需改源码。

更新方式：从 exchange-gateway 仓库重新拷贝
``examples/marketdata-fetch-client/exchange_gateway_ref_client.py`` 覆盖
``ref_client.py``，并同步 ``proto/`` 三个文件即可。
"""
