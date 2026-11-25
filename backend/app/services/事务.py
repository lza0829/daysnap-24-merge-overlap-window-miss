from contextlib import contextmanager


@contextmanager
def 立即事务(conn):
    """SQLite 写事务：BEGIN IMMEDIATE 先取写锁，避免抽取与并户交错写。

    连接使用显式事务，退出时 COMMIT；异常时 ROLLBACK，保证并户的
    账户状态、快照归档/重算、流水改挂、差额处置同成败。
    """
    conn.isolation_level = None
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
