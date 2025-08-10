# 演示相对导入的限制

# ===== 项目结构 =====
"""
project/
├── main.py          # 顶层脚本（直接运行的文件）
├── package/
│   ├── __init__.py
│   ├── module_a.py
│   └── subpackage/
│       ├── __init__.py
│       └── module_b.py
"""

# ===== 什么是脚本 =====
"""
脚本：直接用 python 命令运行的 .py 文件
例如：python main.py

当文件作为脚本运行时：
- __name__ == "__main__"
- __package__ == None
- 不能使用相对导入
"""

# ===== 相对导入的工作条件 =====
"""
在 package/subpackage/module_b.py 中：

# ✅ 正确：作为模块导入时可以使用相对导入
from ..module_a import some_function    # 上级包的模块
from . import __init__                  # 当前包的__init__

# ❌ 错误：如果直接运行 python module_b.py
# 会报错：ImportError: attempted relative import with no known parent package
"""

# ===== 为什么有这个限制 =====
"""
原因：
1. 脚本运行时，Python不知道它在包层次结构中的位置
2. __package__ 为 None，无法计算相对路径
3. 相对导入需要明确的包上下文

解决方案：
1. 使用绝对导入：from project.package.module_a import function
2. 作为模块运行：python -m package.subpackage.module_b
3. 在顶层脚本中导入后使用
"""

# ===== 实际项目中的用法 =====
"""
在你的项目中：

# ✅ 正确：在 src/api/server.py 中
from ..tools.registry import ALL_TOOLS_LIST  # 相对导入

# ✅ 正确：运行方式
python main.py                    # main.py 是顶层脚本
python -m src.api.server          # 作为模块运行

# ❌ 错误：运行方式
cd src/api && python server.py    # 直接运行，会报相对导入错误
"""

print("这个文件演示了相对导入的使用限制") 