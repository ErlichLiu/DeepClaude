"""
SQLite数据库连接池实现
"""

import sqlite3
import threading
import time
import logging
from typing import List, Optional, Dict
import os

# 设置日志
logger = logging.getLogger("db_pool")

class SQLiteConnectionPool:
    """SQLite数据库连接池"""

    def __init__(self, db_path: str, max_connections: int = 5, check_interval: int = 60):
        """初始化连接池

        Args:
            db_path: 数据库文件路径
            max_connections: 最大连接数
            check_interval: 连接健康检查间隔（秒）
        """
        self.db_path = db_path
        self.max_connections = max_connections
        self.check_interval = check_interval

        # 确保数据库目录存在
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

        # 连接池
        self.pool: List[sqlite3.Connection] = []
        # 可用连接索引
        self.available: List[int] = []
        # 连接使用状态
        self.in_use: Dict[int, bool] = {}
        # 连接创建时间
        self.created_time: Dict[int, float] = {}
        # 连接最后使用时间
        self.last_used: Dict[int, float] = {}

        # 线程锁，保证线程安全
        self.lock = threading.RLock()

        # 初始化连接池
        self._initialize_pool()

        # 启动健康检查线程
        self.checker_thread = threading.Thread(target=self._connection_health_check, daemon=True)
        self.checker_thread.start()

        logger.info("SQLite连接池初始化完成，最大连接数: %s", max_connections)

    def _initialize_pool(self):
        """初始化连接池"""
        with self.lock:
            for i in range(self.max_connections):
                try:
                    conn = sqlite3.connect(self.db_path, check_same_thread=False)
                    # 启用外键约束
                    conn.execute("PRAGMA foreign_keys = ON")
                    # 设置行工厂，返回字典而不是元组
                    conn.row_factory = sqlite3.Row

                    self.pool.append(conn)
                    self.available.append(i)
                    self.in_use[i] = False
                    self.created_time[i] = time.time()
                    self.last_used[i] = time.time()

                    logger.debug("创建连接 #%s", i)
                except sqlite3.Error as e:
                    logger.error("初始化连接 #%s 失败: %s", i, e)

    def _connection_health_check(self):
        """连接健康检查线程"""
        while True:
            try:
                time.sleep(self.check_interval)
                self._check_connections()
            except sqlite3.Error as e:
                logger.error("连接健康检查异常: %s", e)

    def _check_connections(self):
        """检查所有连接的健康状态"""
        with self.lock:
            current_time = time.time()
            for i, conn in enumerate(self.pool):
                # 跳过正在使用的连接
                if self.in_use.get(i, False):
                    continue

                try:
                    # 执行简单查询测试连接
                    cursor = conn.cursor()
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
                    cursor.close()
                    logger.debug("连接 #%s 健康检查通过", i)
                except sqlite3.Error as e:
                    logger.warning("连接 #%s 健康检查失败: %s，尝试重新创建", i, e)
                    try:
                        try:
                        # 关闭旧连接
                            conn.close()
                        except sqlite3.Error:
                            pass

                        # 创建新连接
                        new_conn = sqlite3.connect(self.db_path, check_same_thread=False)
                        new_conn.execute("PRAGMA foreign_keys = ON")
                        new_conn.row_factory = sqlite3.Row

                        # 更新连接池
                        self.pool[i] = new_conn
                        self.created_time[i] = current_time
                        self.last_used[i] = current_time

                        # 如果之前不在可用列表中，添加到可用列表
                        if i not in self.available:
                            self.available.append(i)
                            self.in_use[i] = False

                        logger.info("连接 #%s 已重新创建", i)
                    except sqlite3.Error as e2:
                        logger.error("重新创建连接 #%s 失败: %s", i, e2)

    def get_connection(self, max_wait=5, retry_interval=0.1) -> Optional[sqlite3.Connection]:
        """获取一个可用的数据库连接，如果没有可用连接则等待

        Args:
            max_wait: 最大等待时间（秒）
            retry_interval: 重试间隔（秒）

        Returns:
            Optional[sqlite3.Connection]: 数据库连接，如果超时仍无可用连接则返回None
        """
        wait_time = 0
        while wait_time < max_wait:
            with self.lock:
                if self.available:
                    index = self.available.pop(0)
                    self.in_use[index] = True
                    self.last_used[index] = time.time()

                    logger.debug("获取连接 #%s，剩余可用连接: %s", index, len(self.available))
                    return self.pool[index]

            # 没有可用连接，等待后重试
            time.sleep(retry_interval)
            wait_time += retry_interval

        logger.warning("等待可用连接超时(%s秒)", max_wait)
        return None

    def release_connection(self, conn: sqlite3.Connection):
        """释放连接回连接池

        Args:
            conn: 要释放的连接
        """
        with self.lock:
            for i, pool_conn in enumerate(self.pool):
                if pool_conn is conn:
                    if i not in self.available:
                        self.available.append(i)
                    self.in_use[i] = False
                    self.last_used[i] = time.time()
                    logger.debug("释放连接 #%s，当前可用连接: %s", i, len(self.available))
                    return

            logger.warning("尝试释放不属于连接池的连接")

    def close_all(self):
        """关闭所有连接"""
        with self.lock:
            for i, conn in enumerate(self.pool):
                try:
                    conn.close()
                    logger.debug("关闭连接 #%s", i)
                except sqlite3.Error as e:
                    logger.error("关闭连接 #%s 失败: %s", i, e)

            self.pool.clear()
            self.available.clear()
            self.in_use.clear()
            self.created_time.clear()
            self.last_used.clear()

            logger.info("所有数据库连接已关闭")


class DBConnection:
    """数据库连接包装器，用于自动获取和释放连接"""

    def __init__(self, pool: SQLiteConnectionPool):
        """初始化

        Args:
            pool: 数据库连接池
        """
        self.pool = pool
        self.conn = None
        self.cursor = None

    def __enter__(self):
        """进入上下文时获取连接"""
        self.conn = self.pool.get_connection()
        if self.conn:
            self.cursor = self.conn.cursor()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文时释放连接"""
        if self.cursor:
            self.cursor.close()

        if self.conn:
            if exc_type:
                # 发生异常，回滚事务
                try:
                    self.conn.rollback()
                except sqlite3.Error:
                    pass
            else:
                # 正常退出，提交事务
                try:
                    self.conn.commit()
                except sqlite3.Error:
                    pass

            self.pool.release_connection(self.conn)

        self.cursor = None
        self.conn = None

    def execute(self, sql, params=None):
        """执行SQL语句

        Args:
            sql: SQL语句
            params: 参数

        Returns:
            cursor对象
        """
        if not self.cursor:
            raise sqlite3.Error("数据库连接未初始化")

        if params:
            return self.cursor.execute(sql, params)
        else:
            return self.cursor.execute(sql)

    def fetchone(self):
        """获取一条记录"""
        if not self.cursor:
            raise sqlite3.Error("数据库连接未初始化")
        return self.cursor.fetchone()

    def fetchall(self):
        """获取所有记录"""
        if not self.cursor:
            raise sqlite3.Error("数据库连接未初始化")
        return self.cursor.fetchall()

    def commit(self):
        """提交事务"""
        if not self.conn:
            raise sqlite3.Error("数据库连接未初始化")
        self.conn.commit()

    def rollback(self):
        """回滚事务"""
        if not self.conn:
            raise sqlite3.Error("数据库连接未初始化")
        self.conn.rollback()


# 全局连接池实例
DB_POOL = None

def get_db_pool(db_path=None, max_connections=5, check_interval=60):
    """获取全局数据库连接池实例

    Args:
        db_path: 数据库文件路径，仅在首次调用时有效
        max_connections: 最大连接数，仅在首次调用时有效
        check_interval: 连接健康检查间隔（秒），仅在首次调用时有效

    Returns:
        SQLiteConnectionPool: 数据库连接池实例
    """
    pool = globals()["DB_POOL"]
    if pool is None:
        if db_path is None:
            # 默认数据库路径
            db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "deepclaude.db")
        globals()["DB_POOL"] = SQLiteConnectionPool(db_path, max_connections, check_interval)
    return globals()["DB_POOL"]

def get_db_connection():
    """获取数据库连接

    Returns:
        DBConnection: 数据库连接包装器
    """
    return DBConnection(get_db_pool())

def close_db_pool():
    """关闭数据库连接池"""
    pool = globals()["DB_POOL"]
    if pool:
        pool.close_all()
        globals()["DB_POOL"] = None
