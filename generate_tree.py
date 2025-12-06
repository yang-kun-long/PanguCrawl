import os
from pathlib import Path

# ================= 配置区域 =================
# 你想扫描的根目录 ('.' 表示当前目录)
ROOT_DIR = '.'

# 需要忽略的文件夹 (完全匹配)
IGNORE_DIRS = {
    'node_modules',
    'venv',
    '.venv',
    '.git',
    '.idea',
    '__pycache__',
    '.vscode',
    'dist',
    'build',
    'pg_data',  # 数据库挂载目录
    'coverage',
    'site-packages'
}

# 需要忽略的文件 (完全匹配)
IGNORE_FILES = {
    '.DS_Store',
    'Thumbs.db',
    '.gitignore',
    'package-lock.json',
    'yarn.lock',
    'generate_tree.py'  # 不把自己也打印出来
}

# 需要忽略的文件扩展名
IGNORE_EXTENSIONS = {
    '.pyc',
    '.log',
    '.tmp',
    '.svg',  # 如果图标太多不想看，可以加上这个
}


# ===========================================

def print_tree(directory, prefix=''):
    path_obj = Path(directory)

    # 获取当前目录下所有文件和文件夹
    try:
        # 过滤掉忽略的文件和文件夹
        files = sorted([
            x for x in path_obj.iterdir()
            if x.name not in IGNORE_DIRS
               and x.name not in IGNORE_FILES
               and x.suffix not in IGNORE_EXTENSIONS
        ], key=lambda x: (x.is_file(), x.name.lower()))  # 文件夹排在前面
    except PermissionError:
        print(f"{prefix}[权限被拒绝]")
        return

    # 遍历所有项目
    total = len(files)
    for index, item in enumerate(files):
        connector = '├── ' if index < total - 1 else '└── '

        print(f"{prefix}{connector}{item.name}")

        if item.is_dir():
            # 递归调用
            extension = '│   ' if index < total - 1 else '    '
            print_tree(item, prefix + extension)


if __name__ == '__main__':
    print(f"📂 项目架构: {Path(ROOT_DIR).resolve().name}")
    print_tree(ROOT_DIR)

    # 可选：直接保存到文件
    # print("\n(提示：若要保存到文件，请在终端运行: python generate_tree.py > structure.txt)")