"""
VikingDB 迁移占位说明（合规开通后使用）。

运行: python -m backend.scripts.memory_vikingdb_migration_stub
"""
from backend.memory.vikingdb_backend import migration_note


def main():
    print(migration_note())
    print(
        "\n导出建议：从 SQLite memory_items 与 Chroma collection layered_memory_items "
        "读取 id / search_text / metadata，批量调用 VikingDB UpsertData。"
    )


if __name__ == "__main__":
    main()
