import logging
import colorlog
import sys


def setup_logger(name: str = "DeepClaude") -> logging.Logger:
    """设置一个彩色的logger

    Args:
        name (str, optional): logger的名称. Defaults to "DeepClaude".

    Returns:
        logging.Logger: 配置好的logger实例
    """
    logger_instance = colorlog.getLogger(name)

    if logger_instance.handlers:
        return logger_instance

    # 设置日志级别
    logger_instance.setLevel(logging.DEBUG)

    # 创建控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)

    # 设置彩色日志格式
    formatter = colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "red,bg_white",
        },
    )

    console_handler.setFormatter(formatter)
    logger_instance.addHandler(console_handler)

    return logger_instance


# 创建一个默认的logger实例
logger = setup_logger()
