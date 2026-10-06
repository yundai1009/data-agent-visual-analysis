# -*- coding: utf-8 -*-
"""阶段 54-8 · MySQL 初始化数据库（对齐 sqlite_repo.初始化数据库 的表集合）。

职责（幂等，重复调用安全，不 DROP 任何表）：
1. 16 张业务表 ``CREATE TABLE IF NOT EXISTS``——正确 DDL（VARCHAR 主键、UNIQUE、
   索引、列宽对齐）；对已存在的迁移产物表是 no-op；
2. 幂等**升级**既有表（走查时由 migrate 脚本生成、0 行的表）：
   - users.username/email → VARCHAR + UNIQUE（对齐 SQLite UNIQUE 约束，验收 5）
   - favorites.user_id/report_id 宽 191 → 255（对齐 users/reports 主键宽度）
   - datasets/reports 等补 user_id 索引（压测 P0：列表查询全表扫描）
   - 全部时间列 datetime(6) → VARCHAR(64)（**业务契约**：repo 层时间即 ISO 字符串
     原文——lexical 比较 + ``fromisoformat`` 需要带偏移；DATETIME 读回是 naive，
     auth.py 的 aware/naive 比较、事件导出的 astimezone、分享到期判断会崩）

升级全部先查 information_schema 再执行，任意时刻重跑安全。
"""
from __future__ import annotations

import logging
from typing import List

logger = logging.getLogger(__name__)

# ---- 16 张业务表的建表 DDL（对齐 sqlite 各仓储初始化，MySQL 方言） ----

_建表DDL: List[str] = [
    """
    CREATE TABLE IF NOT EXISTS `datasets` (
        `dataset_id`    VARCHAR(255) NOT NULL,
        `user_id`       VARCHAR(255) NOT NULL DEFAULT 'demo',
        `file_name`     VARCHAR(255) NOT NULL,
        `stored_path`   VARCHAR(512) NOT NULL,
        `rows_count`    INT NOT NULL,
        `cols_count`    INT NOT NULL,
        `df_json`       LONGTEXT NOT NULL,
        `profile_json`  LONGTEXT NOT NULL,
        `created_at`    VARCHAR(64) NOT NULL,
        `updated_at`    VARCHAR(64) NOT NULL,
        `parent_id`     VARCHAR(255),
        `data_path`     VARCHAR(512),
        PRIMARY KEY (`dataset_id`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS `users` (
        `user_id`            VARCHAR(255) NOT NULL,
        `username`           VARCHAR(255) NOT NULL COLLATE utf8mb4_bin,
        `password_hash`      VARCHAR(255) NOT NULL,
        `role`               VARCHAR(64) NOT NULL,
        `email`              VARCHAR(255) COLLATE utf8mb4_bin,
        `created_at`         VARCHAR(64) NOT NULL,
        `updated_at`         VARCHAR(64) NOT NULL,
        `status`             VARCHAR(32) NOT NULL DEFAULT 'active',
        `llm_api_key`        TEXT,
        `llm_custom_providers` TEXT,
        `token_version`      INT NOT NULL DEFAULT 0,
        PRIMARY KEY (`user_id`),
        UNIQUE KEY `idx_users_username` (`username`),
        UNIQUE KEY `idx_users_email` (`email`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS `email_codes` (
        `email`           VARCHAR(255) NOT NULL,
        `code_hash`       VARCHAR(255) NOT NULL,
        `expires_at`      VARCHAR(64) NOT NULL,
        `used`            INT NOT NULL DEFAULT 0,
        `verify_attempts` INT NOT NULL DEFAULT 0,
        `last_sent_at`    VARCHAR(64) NOT NULL,
        `created_at`      VARCHAR(64) NOT NULL,
        PRIMARY KEY (`email`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS `reports` (
        `report_id`   VARCHAR(255) NOT NULL,
        `user_id`     VARCHAR(255) NOT NULL,
        `dataset_id`  VARCHAR(255) NOT NULL,
        `title`       VARCHAR(512) NOT NULL,
        `chart_type`  VARCHAR(64) NOT NULL,
        `report_json` LONGTEXT NOT NULL,
        `created_at`  VARCHAR(64) NOT NULL,
        PRIMARY KEY (`report_id`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS `report_templates` (
        `template_id`  VARCHAR(255) NOT NULL,
        `user_id`      VARCHAR(255) NOT NULL,
        `name`         VARCHAR(255) NOT NULL,
        `dataset_id`   VARCHAR(255) NOT NULL,
        `payload_json` LONGTEXT NOT NULL,
        `created_at`   VARCHAR(64) NOT NULL,
        `updated_at`   VARCHAR(64) NOT NULL,
        PRIMARY KEY (`template_id`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS `dashboards` (
        `dashboard_id` VARCHAR(255) NOT NULL,
        `user_id`      VARCHAR(255) NOT NULL,
        `name`         VARCHAR(255) NOT NULL,
        `report_ids`   LONGTEXT NOT NULL,
        `created_at`   VARCHAR(64) NOT NULL,
        `updated_at`   VARCHAR(64) NOT NULL,
        PRIMARY KEY (`dashboard_id`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS `share_links` (
        `share_id`      VARCHAR(255) NOT NULL,
        `user_id`       VARCHAR(255) NOT NULL,
        `report_id`     VARCHAR(255) NOT NULL,
        `expires_at`    VARCHAR(64) NOT NULL,
        `created_at`    VARCHAR(64) NOT NULL,
        `password`      VARCHAR(255),
        `collaborators` TEXT,
        `view_count`    INT NOT NULL DEFAULT 0,
        `target_type`   VARCHAR(32) NOT NULL DEFAULT 'report',
        PRIMARY KEY (`share_id`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS `favorites` (
        `user_id`    VARCHAR(255) NOT NULL,
        `report_id`  VARCHAR(255) NOT NULL,
        `created_at` VARCHAR(64) NOT NULL,
        PRIMARY KEY (`user_id`, `report_id`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS `audit_log` (
        `id`          INT AUTO_INCREMENT PRIMARY KEY,
        `user_id`     VARCHAR(255) NOT NULL,
        `username`    VARCHAR(255) NOT NULL DEFAULT '',
        `action`      VARCHAR(255) NOT NULL,
        `target_type` VARCHAR(64) NOT NULL DEFAULT '',
        `target_id`   VARCHAR(255) NOT NULL DEFAULT '',
        `detail`      TEXT NOT NULL,
        `created_at`  VARCHAR(64) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS `feedback` (
        `id`         INT AUTO_INCREMENT PRIMARY KEY,
        `user_id`    VARCHAR(255) NOT NULL,
        `task_id`    VARCHAR(255) NOT NULL DEFAULT '',
        `score`      INT NOT NULL,
        `correction` TEXT NOT NULL,
        `sync_kb`    INT NOT NULL DEFAULT 0,
        `created_at` VARCHAR(64) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS `llm_usage` (
        `id`                INT AUTO_INCREMENT PRIMARY KEY,
        `user_id`           VARCHAR(255) NOT NULL,
        `provider`          VARCHAR(128) NOT NULL DEFAULT '',
        `model`             VARCHAR(128) NOT NULL DEFAULT '',
        `prompt_tokens`     INT NOT NULL DEFAULT 0,
        `completion_tokens` INT NOT NULL DEFAULT 0,
        `total_tokens`      INT NOT NULL DEFAULT 0,
        `created_at`        VARCHAR(64) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS `scheduled_jobs` (
        `job_id`      VARCHAR(255) NOT NULL,
        `user_id`     VARCHAR(255) NOT NULL,
        `template_id` VARCHAR(255) NOT NULL,
        `cron_expr`   VARCHAR(128) NOT NULL,
        `enabled`     INT NOT NULL DEFAULT 1,
        `last_run_at` VARCHAR(64),
        `last_status` VARCHAR(64),
        `created_at`  VARCHAR(64) NOT NULL,
        PRIMARY KEY (`job_id`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS `event_register` (
        `id`            INT AUTO_INCREMENT PRIMARY KEY,
        `user_id`       VARCHAR(255) NOT NULL,
        `register_time` VARCHAR(64) NOT NULL,
        `channel`       VARCHAR(64),
        `device_type`   VARCHAR(64),
        `city_tier`     VARCHAR(64),
        `user_source`   VARCHAR(64)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS `event_gen` (
        `id`            INT AUTO_INCREMENT PRIMARY KEY,
        `user_id`       VARCHAR(255) NOT NULL,
        `gen_time`      VARCHAR(64) NOT NULL,
        `image_count`   INT NOT NULL DEFAULT 1,
        `analysis_type` VARCHAR(64),
        `is_paid_quota` INT NOT NULL DEFAULT 0,
        `source_page`   VARCHAR(64)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS `event_paywall` (
        `id`           INT AUTO_INCREMENT PRIMARY KEY,
        `user_id`      VARCHAR(255) NOT NULL,
        `hit_time`     VARCHAR(64) NOT NULL,
        `action_after` VARCHAR(255) NOT NULL,
        `shown_price`  DOUBLE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS `event_payment` (
        `id`           INT AUTO_INCREMENT PRIMARY KEY,
        `order_id`     VARCHAR(255) NOT NULL,
        `user_id`      VARCHAR(255) NOT NULL,
        `pay_time`     VARCHAR(64) NOT NULL,
        `product_type` VARCHAR(64) NOT NULL,
        `amount`       DOUBLE NOT NULL,
        UNIQUE KEY `idx_event_payment_order` (`order_id`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
]

# ---- 幂等升级：时间列统一为 VARCHAR(64)（业务契约，见模块 docstring） ----
_时间列: dict = {
    "users": ["created_at", "updated_at"],
    "datasets": ["created_at", "updated_at"],
    "reports": ["created_at"],
    "share_links": ["expires_at", "created_at"],
    "dashboards": ["created_at", "updated_at"],
    "audit_log": ["created_at"],
    "email_codes": ["expires_at", "last_sent_at", "created_at"],
    "favorites": ["created_at"],
    "feedback": ["created_at"],
    "llm_usage": ["created_at"],
    "report_templates": ["created_at", "updated_at"],
    "scheduled_jobs": ["last_run_at", "created_at"],
    "event_register": ["register_time"],
    "event_gen": ["gen_time"],
    "event_paywall": ["hit_time"],
    "event_payment": ["pay_time"],
}

# 需加索引的 user_id 列先转 VARCHAR(255)（longtext 无法建索引）
_宽列: dict = {
    "users": ["username", "email", "password_hash"],
    "datasets": ["user_id"],
    "reports": ["user_id"],
    "dashboards": ["user_id"],
    "report_templates": ["user_id"],
    "share_links": ["user_id", "report_id"],
    "event_payment": ["order_id"],
}

# 需确保存在的索引：(表, 索引名, 列片段, 是否唯一)
_索引: List[tuple] = [
    ("users", "idx_users_username", "(username)", True),
    ("users", "idx_users_email", "(email)", True),
    ("datasets", "idx_datasets_created_at", "(created_at)", False),
    ("datasets", "idx_datasets_user_created", "(user_id, created_at)", False),
    ("reports", "idx_reports_user_created_at", "(user_id, created_at)", False),
    ("share_links", "idx_share_links_report", "(report_id)", False),
    ("dashboards", "idx_dashboards_user_created_at", "(user_id, created_at)", False),
    ("report_templates", "idx_templates_user_created", "(user_id, created_at)", False),
    ("audit_log", "idx_audit_created", "(created_at)", False),
    ("llm_usage", "idx_llm_usage_created", "(created_at)", False),
    ("scheduled_jobs", "idx_jobs_enabled", "(enabled)", False),
    ("event_payment", "idx_event_payment_order", "(order_id)", True),
]

# favorites 列宽对齐：users/reports 主键都是 VARCHAR(255)，favorites 迁移产物是 191
_宽列改: dict = {
    "favorites": ["user_id", "report_id"],
}

# 文本列升级：audit_log.detail / feedback.correction 存任意长度（SQLite TEXT 无限），
# MySQL 窄 VARCHAR（512/1024）有截断风险 → 统一升 TEXT（对齐 llm_custom_providers 先例）
_文本列改: dict = {
    "audit_log": ["detail"],
    "feedback": ["correction"],
}


def _列信息(cur, 表: str, 列: str):
    """返回 (DATA_TYPE, IS_NULLABLE, CHARACTER_MAXIMUM_LENGTH)；列不存在返回 None。"""
    cur.execute(
        "SELECT DATA_TYPE, IS_NULLABLE, CHARACTER_MAXIMUM_LENGTH FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
        (表, 列),
    )
    row = cur.fetchone()
    return row


def _确保列宽(cur, 表: str, 列: str, 目标宽: int = 255) -> None:
    """把 TEXT/longtext/窄 varchar 列改成 VARCHAR(255)（可空保持，有数据时 255 兜底截断风险由调用方权衡）。"""
    row = _列信息(cur, 表, 列)
    if row is None:
        return
    data_type, _nullable, char_len = (row[0] or "").lower(), row[1], row[2]
    if data_type == "varchar" and char_len is not None and int(char_len) >= 目标宽:
        return
    extra = "" if row[1] == "YES" else "NOT NULL"
    cur.execute(f"ALTER TABLE `{表}` MODIFY COLUMN `{列}` VARCHAR({目标宽}) {extra}".strip())
    logger.info("MySQL schema 升级：%s.%s → VARCHAR(%d)", 表, 列, 目标宽)


def _确保时间列(cur, 表: str, 列: str) -> None:
    """时间列统一为 VARCHAR(64)：repo 层时间是 ISO 字符串原文（见模块 docstring）。"""
    row = _列信息(cur, 表, 列)
    if row is None:
        return
    data_type = (row[0] or "").lower()
    if data_type == "varchar":
        return
    cur.execute(f"ALTER TABLE `{表}` MODIFY COLUMN `{列}` VARCHAR(64)")
    logger.info("MySQL schema 升级：%s.%s %s → VARCHAR(64)", 表, 列, data_type)


def _确保文本列(cur, 表: str, 列: str) -> None:
    """窄 VARCHAR 文本列升级为 TEXT（Fix M2：audit_log.detail / feedback.correction
    存任意长度，防截断；对齐 SQLite TEXT 无限语义与 llm_custom_providers 的 TEXT 先例）。

    已是 text 家族（text/mediumtext/longtext）则不动——不把已扩容列降级，避免截断既有长内容。
    """
    row = _列信息(cur, 表, 列)
    if row is None:
        return
    data_type = (row[0] or "").lower()
    if data_type in ("text", "mediumtext", "longtext"):
        return
    extra = "" if row[1] == "YES" else "NOT NULL"
    cur.execute(f"ALTER TABLE `{表}` MODIFY COLUMN `{列}` TEXT {extra}".strip())
    logger.info("MySQL schema 升级：%s.%s %s → TEXT", 表, 列, data_type)


def _确保大小写敏感列(cur, 表: str, 列: str) -> None:
    """把 varchar 列 collation 升为 utf8mb4_bin（大小写敏感），对齐 SQLite 语义。

    Fix F2（阶段 54-10）：MySQL utf8mb4_unicode_ci 大小写不敏感——'Alice'/'alice'
    互斥互等，注册更严/登录匹配更宽，与 SQLite 不同。产品确认后统一走
    utf8mb4_bin：唯一约束与等值比较都大小写敏感（'Alice' 与 'alice' 可并存）。
    **必须先确保列是 VARCHAR(255) 再改 collation**（ALTER MODIFY 会重置 collation），
    故本函数在列宽升级之后调用（见 初始化数据库 顺序）。
    """
    row = _列信息(cur, 表, 列)
    if row is None:
        return
    data_type = (row[0] or "").lower()
    # _列信息 返回 (DATA_TYPE, IS_NULLABLE, CHARACTER_MAXIMUM_LENGTH)，不含 collation——单独查
    cur.execute(
        "SELECT COLLATION_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
        (表, 列))
    row2 = cur.fetchone()
    collation = row2[0] if row2 else None
    if data_type != "varchar":
        logger.info("MySQL schema 跳过大小写敏感升级：%s.%s 非 varchar（%s）", 表, 列, data_type)
        return
    if collation and collation.endswith("_bin"):
        return
    extra = "" if row[1] == "YES" else "NOT NULL"
    cur.execute(f"ALTER TABLE `{表}` MODIFY COLUMN `{列}` VARCHAR(255) COLLATE utf8mb4_bin {extra}".strip())
    logger.info("MySQL schema 升级：%s.%s collation → utf8mb4_bin（大小写敏感）", 表, 列)


def _确保索引(cur, 表: str, 索引名: str, 列片段: str, 唯一: bool) -> None:
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND INDEX_NAME = %s",
        (表, 索引名),
    )
    if int(cur.fetchone()[0]) > 0:
        return
    关键字 = "UNIQUE" if 唯一 else ""
    cur.execute(f"ALTER TABLE `{表}` ADD {关键字} INDEX `{索引名}` {列片段}")
    logger.info("MySQL schema 升级：%s 添加索引 %s%s %s", 表, 关键字, 索引名, 列片段)


def 初始化数据库() -> None:
    """创建/升级全部业务表（幂等）。走 mysql_backend 原生连接（不经包装，避免循环依赖）。"""
    from 后端_核心.存储 import mysql_backend

    with mysql_backend.get_conn() as conn:
        with conn.cursor() as cur:
            # 1) 建表（缺的表直接按正确 DDL 建；已存在的 no-op）
            for ddl in _建表DDL:
                cur.execute(ddl)
            # 2) 幂等升级既有迁移产物表
            for 表, 列清单 in _宽列.items():
                for 列 in 列清单:
                    if 表 == "users" and 列 == "email":
                        # email 可空（未绑邮箱的用户）
                        row = _列信息(cur, 表, 列)
                        if row is not None and (row[0] or "").lower() != "varchar":
                            cur.execute(f"ALTER TABLE `users` MODIFY COLUMN `email` VARCHAR(255)")
                        continue
                    _确保列宽(cur, 表, 列)
            for 表, 列清单 in _宽列改.items():
                for 列 in 列清单:
                    _确保列宽(cur, 表, 列)
            for 表, 列清单 in _文本列改.items():
                for 列 in 列清单:
                    _确保文本列(cur, 表, 列)
            # 阶段 54-10 F2：users.username/email 大小写敏感（对齐 SQLite）——
            # 必须在列宽升级之后（ALTER MODIFY 会重置 collation）
            for 列 in ("username", "email"):
                _确保大小写敏感列(cur, "users", 列)
            for 表, 列清单 in _时间列.items():
                for 列 in 列清单:
                    _确保时间列(cur, 表, 列)
            for 表, 索引名, 列片段, 唯一 in _索引:
                _确保索引(cur, 表, 索引名, 列片段, 唯一)
    logger.info("MySQL 数据库已初始化/升级（16 张业务表）")