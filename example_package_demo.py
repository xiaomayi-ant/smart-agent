# 演示__init__.py的各种用法

# ===== 例子1: 预加载模块 =====
# 在 mypackage/__init__.py 中：
"""
# 预加载常用模块，用户导入包时自动可用
from .database import DatabaseManager
from .utils import helper_function
from .config import DEFAULT_CONFIG

# 用户只需要 import mypackage 就能直接使用
# mypackage.DatabaseManager()
# mypackage.helper_function()
"""

# ===== 例子2: 设置包变量 =====
# 在 mypackage/__init__.py 中：
"""
# 包级别常量
VERSION = "1.0.0"
DEBUG = False
DEFAULT_TIMEOUT = 30

# 包级别配置
CONFIG = {
    'database_url': 'sqlite:///default.db',
    'max_connections': 10
}
"""

# ===== 例子3: 控制导入行为 =====
# 在 mypackage/__init__.py 中：
"""
from .core import CoreClass
from .utils import public_function
from .internal import _private_function

# 只有这些会被 from mypackage import * 导入
__all__ = [
    'CoreClass',
    'public_function',
    'VERSION'
]

VERSION = "1.0.0"

# _private_function 不在 __all__ 中，
# 所以 from mypackage import * 不会导入它
# 但仍可以显式导入: from mypackage.internal import _private_function
"""

# ===== 例子4: 空的__init__.py =====
# 很多项目的 __init__.py 是空的，原因：
"""
# 1. 避免循环导入
# 2. 避免加载重型依赖
# 3. 让用户显式导入需要的模块

# 空的__init__.py只是将目录标记为包
# 用户需要: from mypackage.specific_module import function
"""

print("这是一个演示文件，展示了__init__.py的各种用法") 