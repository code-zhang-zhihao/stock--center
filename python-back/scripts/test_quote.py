from mootdx.quotes import Quotes

# 手动指定你已经测通的IP+端口
client = Quotes.factory(
    market="std",
    ip="119.147.171.199",
    port=7709,
    timeout=15
)

# 测试单只quote
res = client.quote(symbol="600036")
print("quote结果：")
print(res)